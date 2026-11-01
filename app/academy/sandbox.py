"""Runs learner code in a throw-away Linux sandbox. NEVER executes learner code inside the server process.

What the child sees and can do (all enforced by the kernel, none by Python):
  * its own user, network, mount and PID namespaces: no network at all, its own process table, no way to signal or inspect other processes
  * a MINIMAL ROOT FILESYSTEM built per run: only read-only bind mounts of the interpreter, system libraries and the installed Python packages, the learner's code
    mounted read-only at /code, a size-limited tmpfs as the only writable place (/tmp, also the working directory), and /dev/null, /dev/urandom, /proc.
    The server's source code, data directory, home, secrets and .env files simply do not exist in that view, and nothing outside the tmpfs can be modified.
  * resource limits (`prlimit`): CPU seconds, address space, per-file size, open files, no core dumps
  * a wall-clock timeout that kills the whole process tree; output goes to files the child cannot reach and is read back with a size cap
  * a minimal environment (no API keys, no MKA_* settings) and `python -I`
NOT provided (be honest about it): CPU/memory cgroups, seccomp syscall filtering, disk quota beyond the tmpfs size. If the host does not allow unprivileged
user namespaces (default Docker seccomp, locked-down VMs) the runner reports itself as unavailable and nothing is executed - it never falls back to running unsandboxed."""
from __future__ import annotations

import os
import re
import shutil
import signal
import site
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import Settings

MAX_CODE_BYTES = 20_000
MAX_OUTPUT_BYTES = 64_000
FILE_LIMIT_BYTES = 256_000
LANGS = {"python": ("main.py", None), "javascript": ("main.js", "node")}
_probe: dict[str, tuple[bool, str]] = {}
_sem: Optional[threading.BoundedSemaphore] = None
_sem_lock = threading.Lock()

SETUP_HELP = ("The code runner needs a Linux host that allows unprivileged user namespaces and has util-linux `unshare`/`prlimit` and coreutils `chroot`. "
              "Check: `unshare --user --map-root-user --net --mount --pid --fork true`. In Docker the default seccomp profile blocks this; "
              "either run the container with a profile that allows `unshare`/`clone(CLONE_NEWUSER)` (for example `--security-opt seccomp=<profile.json>`) or run the runner as a separate hardened service. "
              "Until then the lesson code is shown with its expected output - copy it and run it on your own machine (Python 3.10+).")


@dataclass
class RunResult:
    ok: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    unavailable: Optional[str] = None
    notes: list[str] = field(default_factory=list)


TMPFS_MB = 32
_ETC = ["/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/alternatives", "/etc/localtime"]
_SYSTEM = ["/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin"]


def _real(p: str) -> str:
    return os.path.realpath(p)


def _python() -> str:
    return _real(shutil.which("python3") or sys.executable)


def _ro_paths(language: str) -> list[str]:
    """Host paths that are bound read-only into the sandbox root: system dirs plus wherever the interpreter and its packages live."""
    cand = _SYSTEM + _ETC
    if language == "python":
        py = _python()
        cand += [os.path.dirname(py), sys.prefix, sys.base_prefix, sys.exec_prefix, _real(sys.prefix), _real(sys.base_prefix)]
        try:
            cand += site.getsitepackages()
        except Exception:  # noqa: BLE001
            pass
    else:
        node = shutil.which("node")
        if node:
            cand += [str(Path(_real(node)).parent.parent)]
    out: list[str] = []
    for p in cand:
        if not os.path.exists(p) or re.search(r'["\\$`\n ]', p):
            continue
        rp = p if os.path.islink(p) is False else p      # symlinks (/bin -> usr/bin) are bound through their target
        if any(rp == q or rp.startswith(q.rstrip("/") + "/") for q in out):
            continue
        out = [q for q in out if not q.startswith(rp.rstrip("/") + "/")] + [rp]
    return out


_SCRIPT = r"""set -eu
R="$1"; CODE="$2"; shift 2
mount --make-rprivate /
mount -t tmpfs -o size=8m tmpfs "$R"
bind_ro() {
  src="$1"
  if [ -d "$src" ]; then mkdir -p "$R$src"; else mkdir -p "$R$(dirname "$src")"; : > "$R$src"; fi
  mount --bind "$src" "$R$src"
  mount -o remount,ro,bind "$R$src"
}
while [ "$1" != "--" ]; do bind_ro "$1"; shift; done
shift
mkdir -p "$R/dev" "$R/proc" "$R/tmp" "$R/code"
for d in null urandom zero; do : > "$R/dev/$d"; mount --bind "/dev/$d" "$R/dev/$d"; done
mount -t proc proc "$R/proc"
mount -t tmpfs -o size=__TMPFS__m,mode=1777 tmpfs "$R/tmp"
mount --bind "$CODE" "$R/code"
mount -o remount,ro,bind "$R/code"
exec "$@"
"""


def _wrap_cmd(root: str, code_dir: str, inner: list[str], mem_mb: int, cpu_s: int, language: str) -> list[str]:
    which = lambda n: shutil.which(n, path=os.environ.get("PATH", "") + ":/usr/sbin:/sbin:/usr/bin:/bin") or n  # noqa: E731  (absolute paths: the child runs with a minimal PATH)
    limits = [which("prlimit"), f"--cpu={cpu_s}", f"--fsize={FILE_LIMIT_BYTES}", "--nofile=64", "--core=0"]
    limits.append(f"--as={mem_mb * 1024 * 1024}" if language == "python" else f"--data={mem_mb * 1024 * 1024}")   # V8 reserves huge address space, so Node is limited by data size
    chroot = [which("chroot"), root, "/bin/sh", "-c", 'cd /tmp && exec "$@"', "sandbox", *inner]
    return [which("unshare"), "--user", "--map-root-user", "--net", "--mount", "--pid", "--fork", "--kill-child", "sh", "-c", _SCRIPT.replace("__TMPFS__", str(TMPFS_MB)), "sandbox",
            root, code_dir, *_ro_paths(language), "--", *limits, "--", *chroot]


def _probe_run(s: Settings, language: str) -> tuple[bool, str]:
    root, code = tempfile.mkdtemp(prefix="mka-sbx-root-"), tempfile.mkdtemp(prefix="mka-sbx-code-")
    try:
        probe = [_python(), "-I", "-c", "import sys; print(sys.version_info[0])"] if language == "python" else [shutil.which("node") or "node", "-e", "console.log(1)"]
        r = subprocess.run(_wrap_cmd(root, code, probe, 512, 5, language), capture_output=True, timeout=15, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if r.returncode == 0:
            return True, ""
        return False, f"the sandbox could not start ({r.stderr.decode(errors='replace').strip()[-200:]})"
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"sandbox probe failed: {e}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(code, ignore_errors=True)


def available(s: Settings, language: str = "python") -> tuple[bool, str]:
    """(usable?, reason). The result of the first real probe per language is cached for the life of the process; any doubt means unavailable (fail closed)."""
    if s.sandbox == "off":
        return False, "Code execution is switched off (MKA_SANDBOX=off)."
    if not sys.platform.startswith("linux") or not shutil.which("unshare") or not shutil.which("prlimit") or not shutil.which("chroot"):
        return False, "This host has no Linux `unshare`, `prlimit` and `chroot`."
    if language not in _probe:
        _probe[language] = _probe_run(s, language)
    return _probe[language]


def _semaphore(s: Settings) -> threading.BoundedSemaphore:
    global _sem
    with _sem_lock:
        if _sem is None:
            _sem = threading.BoundedSemaphore(max(1, s.sandbox_concurrency))
        return _sem


class Busy(Exception):
    pass


def run(s: Settings, language: str, code: str) -> RunResult:
    if language not in LANGS:
        raise ValueError(f"unsupported language {language!r}")
    if len(code.encode()) > MAX_CODE_BYTES:
        raise ValueError(f"code is longer than {MAX_CODE_BYTES} bytes")
    ok, why = available(s, language)
    if not ok:
        return RunResult(unavailable=why + " " + SETUP_HELP)
    sem = _semaphore(s)
    if not sem.acquire(blocking=False):
        raise Busy("The code runner is busy; try again in a few seconds.")
    base = Path(tempfile.mkdtemp(prefix="mka-sbx-"))
    try:
        code_dir, root, cap = base / "code", base / "root", base / "cap"      # cap (the output files) is never mounted into the sandbox
        for d in (code_dir, root, cap):
            d.mkdir()
        fname, interp = LANGS[language]
        (code_dir / fname).write_text(code, encoding="utf-8")
        inner = [_python(), "-I", "-B", f"/code/{fname}"] if language == "python" else [shutil.which(interp) or interp, "--max-old-space-size=256", f"/code/{fname}"]
        cmd = _wrap_cmd(str(root), str(code_dir), inner, s.sandbox_memory_mb, int(s.sandbox_timeout_s) + 2, language)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0", "OPENBLAS_NUM_THREADS": "1",
               "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "TMPDIR": "/tmp", "NO_COLOR": "1"}
        res = RunResult()
        t0 = time.monotonic()
        with open(cap / "out.txt", "wb") as out, open(cap / "err.txt", "wb") as err:
            p = subprocess.Popen(cmd, cwd=str(base), env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                p.wait(timeout=s.sandbox_timeout_s)
            except subprocess.TimeoutExpired:
                res.timed_out = True
                try:
                    os.killpg(p.pid, signal.SIGKILL)       # kills unshare; --kill-child and the PID namespace take everything else down
                except ProcessLookupError:
                    pass
                p.wait(timeout=5)
        res.ms = int((time.monotonic() - t0) * 1000)
        res.exit_code = None if res.timed_out else p.returncode
        so, se = (cap / "out.txt").read_bytes(), (cap / "err.txt").read_bytes()
        res.truncated = len(so) > MAX_OUTPUT_BYTES or len(se) > MAX_OUTPUT_BYTES or (res.exit_code in (-signal.SIGXFSZ, 128 + signal.SIGXFSZ))
        res.stdout, res.stderr = so[:MAX_OUTPUT_BYTES].decode("utf-8", "replace"), se[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
        if res.exit_code in (-signal.SIGKILL, 128 + signal.SIGKILL) and not res.timed_out:
            res.notes.append("The program was killed (most likely it used more memory or CPU time than allowed).")
        if res.exit_code in (-signal.SIGXCPU, 128 + signal.SIGXCPU):
            res.notes.append("The program used more CPU time than allowed.")
        res.ok = res.exit_code == 0 and not res.timed_out
        return res
    finally:
        shutil.rmtree(base, ignore_errors=True)
        sem.release()


# ----------------------------------------------------------------------------- error help
_HELP = [
    (r"SyntaxError", "Python could not read the code: check brackets, quotes, colons and indentation near the line shown.", "Python code padh nahi paaya: line ke paas brackets, quotes, colon aur indentation check karo."),
    (r"IndentationError", "The indentation (spaces at the start of a line) is inconsistent. Use 4 spaces for each level.", "Indentation (line ke shuru ke spaces) galat hai. Har level ke liye 4 spaces use karo."),
    (r"NameError: name '([^']+)' is not defined", "The name '{0}' is used before it exists. Check the spelling, or define it above where you use it.", "Naam '{0}' bana hone se pehle use hua. Spelling check karo ya use upar define karo."),
    (r"ModuleNotFoundError: No module named '([^']+)'", "The package '{0}' is not installed in the runner. Only the Python standard library, numpy, pydantic, langchain-core and langgraph are available here; run other examples on your own machine.", "Package '{0}' runner mein installed nahi hai. Yahan sirf standard library, numpy, pydantic, langchain-core aur langgraph hain; baaki examples apni machine par chalao."),
    (r"ImportError: cannot import name '([^']+)'", "'{0}' cannot be imported from that module: the name is misspelled, or it was renamed or moved in the installed version.", "'{0}' us module se import nahi ho sakta: spelling galat hai, ya installed version mein naam badal gaya/move ho gaya."),
    (r"TypeError", "An operation got the wrong kind of value (for example adding a number to text, or the wrong number of arguments). Read the message: it names the types involved.", "Kisi operation ko galat type ki value mili (jaise number ko text mein jodna, ya arguments ki galat sankhya). Message padho: usme types ke naam hote hain."),
    (r"KeyError: (.+)", "The dictionary has no key {0}. Print the dictionary or use .get(key) to see what is inside.", "Dictionary mein key {0} nahi hai. Dictionary print karo ya .get(key) use karo."),
    (r"IndexError", "You asked for a list position that does not exist (the list is shorter than the index).", "Aapne list ki aisi position maangi jo exist nahi karti (list index se chhoti hai)."),
    (r"ZeroDivisionError", "Something was divided by zero. Check the denominator before dividing.", "Kisi cheez ko zero se divide kiya gaya. Divide karne se pehle denominator check karo."),
    (r"AttributeError: (.+)", "The object does not have that attribute or method ({0}). Check its type and the spelling.", "Object mein woh attribute ya method nahi hai ({0}). Uska type aur spelling check karo."),
    (r"ValueError", "The value has the right type but an unacceptable content (for example int('abc')).", "Value ka type sahi hai par content galat hai (jaise int('abc'))."),
    (r"(ValidationError|OutputParserException)", "The data did not match the schema: a field is missing, misnamed or of the wrong type. The message lists which field.", "Data schema se match nahi hua: koi field missing hai, uska naam galat hai ya type galat hai. Message batata hai kaunsi field."),
    (r"RecursionError", "A function (or graph) calls itself without stopping. Add a stop condition or a limit.", "Koi function (ya graph) bina ruke khud ko call karta hai. Stop condition ya limit lagao."),
    (r"MemoryError", "The program needed more memory than the runner allows.", "Program ko runner ki limit se zyada memory chahiye thi."),
    (r"ReferenceError: (.+) is not defined", "The name {0} is used before it exists (JavaScript). Check spelling and declare it with const or let.", "Naam {0} bane hone se pehle use hua (JavaScript). Spelling check karo aur const ya let se declare karo."),
]


def explain_error(stderr: str) -> Optional[str]:
    """Plain-language help for the last error in `stderr` (English, then Hinglish). None when nothing recognisable is found."""
    tail = "\n".join(stderr.strip().splitlines()[-12:])
    for pat, en, hing in _HELP:
        m = re.search(pat, tail)
        if m:
            g = [x for x in m.groups()] or [""]
            return en.format(*g[:1]) + "  |  " + hing.format(*g[:1])
    return None
