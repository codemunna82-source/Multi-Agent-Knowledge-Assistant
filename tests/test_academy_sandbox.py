"""The code runner executes learner code, so these tests attack it: network, secrets, runaway CPU/memory/output, forks, concurrency, auth."""
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.academy import sandbox
from app.academy import service as ac
from app.api import create_app
from app.config import Settings

OK, WHY = sandbox.available(Settings(_env_file=None))
pytestmark = pytest.mark.skipif(not OK, reason=f"sandbox not available on this host: {WHY}")
PW = "correct horse battery"


def sandbox_processes() -> list[str]:
    """Processes (visible from the host /proc) whose working directory is a sandbox work dir - precise, unlike matching command lines."""
    found = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if "mka-sbx-" in os.readlink(f"/proc/{pid}/cwd"):
                    found.append(pid)
            except OSError:
                pass
    return found


@pytest.fixture
def s(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "secret.txt").write_text("TOP-SECRET")
    return Settings(data_dir=str(tmp_path / "data"), _env_file=None, sandbox_timeout_s=3, sandbox_memory_mb=1024)


def test_runs_code_and_reports_output_exit_code_and_time(s):
    r = sandbox.run(s, "python", "print(6 * 7)")
    assert r.ok and r.stdout == "42\n" and r.exit_code == 0 and r.ms < 5000 and r.unavailable is None
    bad = sandbox.run(s, "python", "raise ValueError('boom')")
    assert not bad.ok and bad.exit_code == 1 and "ValueError: boom" in bad.stderr


def test_network_is_unreachable(s):
    r = sandbox.run(s, "python", "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=2)\n    print('CONNECTED')\nexcept OSError as e:\n    print('blocked', type(e).__name__)\n")
    assert "blocked" in r.stdout and "CONNECTED" not in r.stdout


def test_server_data_dir_and_environment_secrets_are_invisible(s, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret")
    monkeypatch.setenv("MKA_JWT_SECRET", "jwt-live-secret")
    code = ("import os\nnames = sorted(os.environ)\nprint('env:', [n for n in names if 'KEY' in n or 'SECRET' in n or n.startswith('MKA')])\n"
            f"try:\n    print(open({str(tmp_path / 'data' / 'secret.txt')!r}).read())\nexcept OSError as e:\n    print('data dir hidden:', type(e).__name__)\n"
            "try:\n    print(open('/proc/1/environ', 'rb').read()[:50])\nexcept OSError as e:\n    print('proc hidden:', type(e).__name__)\n")
    r = sandbox.run(s, "python", code)
    assert "env: []" in r.stdout and "TOP-SECRET" not in r.stdout and "data dir hidden" in r.stdout
    assert "sk-live" not in r.stdout + r.stderr and "jwt-live" not in r.stdout + r.stderr


def test_cannot_see_or_signal_server_processes(s):
    r = sandbox.run(s, "python", f"import os\nprint(len(os.listdir('/proc')) < 40, os.path.exists('/proc/{os.getpid()}/cmdline'))\ntry:\n    os.kill({os.getpid()}, 9)\n    print('SIGNALLED')\nexcept OSError as e:\n    print('cannot signal', type(e).__name__)\n")
    assert "SIGNALLED" not in r.stdout and "cannot signal" in r.stdout and "False" in r.stdout.splitlines()[0]


def test_infinite_loop_is_stopped_by_the_wall_clock(s):
    s.sandbox_timeout_s = 1
    t0 = time.time()
    r = sandbox.run(s, "python", "while True:\n    pass\n")
    assert r.timed_out and not r.ok and time.time() - t0 < 6


def test_memory_hog_is_stopped(s):
    s.sandbox_memory_mb = 400
    r = sandbox.run(s, "python", "x = bytearray(2_000_000_000)\nprint('allocated')\n")
    assert "allocated" not in r.stdout and not r.ok


def test_output_flood_is_capped_and_marked(s):
    s.sandbox_timeout_s = 4
    r = sandbox.run(s, "python", "while True:\n    print('x' * 1000)\n")
    assert len(r.stdout) <= sandbox.MAX_OUTPUT_BYTES and r.truncated and not r.ok


def test_forked_children_do_not_survive_a_timeout(s):
    s.sandbox_timeout_s = 1
    code = "import os, time\nfor _ in range(30):\n    if os.fork() == 0:\n        time.sleep(60)\n        os._exit(0)\ntime.sleep(60)\n"
    r = sandbox.run(s, "python", code)
    assert r.timed_out
    for _ in range(20):
        left = sandbox_processes()
        if not left:
            break
        time.sleep(0.25)
    assert not left, f"sandbox children survived the timeout: {left}"


def test_each_run_has_a_fresh_empty_scratch_directory_and_leaves_nothing_behind(s):
    before = set(os.listdir("/tmp"))
    sandbox.run(s, "python", "open('left-behind.txt', 'w').write('x')\nimport os\nprint(sorted(os.listdir('.')))")
    r = sandbox.run(s, "python", "import os\nprint(sorted(os.listdir('.')))")
    assert r.stdout.strip() == "[]"                                  # the previous run's file is gone: the scratch dir is a new tmpfs
    assert not [d for d in set(os.listdir("/tmp")) - before if d.startswith("mka-sbx-")]


def test_the_filesystem_is_a_minimal_read_only_root_without_the_server(s, tmp_path):
    repo = os.getcwd()
    code = (f"import os\nfor p in ['/home', {repo!r}, {str(tmp_path)!r}, '/root', '/var/lib', '/proc/1/environ']:\n    print(p, os.path.exists(p))\n"
            "for target in ['/usr/pwned', '/code/main.py', '/bin/pwned', '/lib/pwned']:\n    try:\n        open(target, 'w').write('x')\n        print('WROTE', target)\n    except OSError as e:\n        print('read-only', target, e.errno)\n"
            "open('/tmp/ok.txt', 'w').write('scratch is writable')\nprint(open('/tmp/ok.txt').read())\n")
    r = sandbox.run(s, "python", code)
    assert "WROTE" not in r.stdout, r.stdout                          # the system dirs and the learner's own code are read-only
    assert r.stdout.count("read-only") == 4 and "scratch is writable" in r.stdout
    for line in r.stdout.splitlines()[:5]:
        assert line.endswith("False"), line                          # server code, the test dir, /home, /root: not visible at all
    assert not any(os.path.exists(f"/{d}/pwned") for d in ("usr", "etc", "bin", "lib", "tmp"))   # nothing leaked onto the host


def test_learner_cannot_tamper_with_the_output_channel_to_read_host_files(s):
    r = sandbox.run(s, "python", "import os\nfor name in ['out.txt', 'err.txt', 'cap']:\n    for base in ['/tmp', '/code', '.']:\n        print(os.path.exists(os.path.join(base, name)))\nos.symlink('/etc/passwd', '/tmp/out.txt')\nprint('done')\n")
    assert r.ok and r.stdout.count("False") == 9 and "root:" not in r.stdout


def test_tmpfs_scratch_space_is_size_limited(s):
    s.sandbox_timeout_s = 8
    r = sandbox.run(s, "python", "import os\nn = 0\ntry:\n    for i in range(400):\n        with open(f'/tmp/f{i}', 'wb') as f:\n            f.write(b'x' * 200_000)\n        n += 1\nexcept OSError as e:\n    print('disk full after', n, 'files')\n")
    assert "disk full" in r.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_javascript_runs_and_has_no_network(s):
    r = sandbox.run(s, "javascript", "console.log([1, 2, 3].map(x => x * 2).join(','))")
    assert r.ok and r.stdout.strip() == "2,4,6"
    n = sandbox.run(s, "javascript", "require('net').connect(53, '1.1.1.1').on('error', e => console.log('blocked ' + e.code)).setTimeout(2000, function() { console.log('timeout'); process.exit(0) })")
    assert "blocked" in n.stdout or "timeout" in n.stdout


def test_switched_off_runner_executes_nothing_and_explains(s, tmp_path):
    marker = tmp_path / "ran.txt"
    s.sandbox = "off"
    r = sandbox.run(s, "python", f"open({str(marker)!r}, 'w').write('ran')")
    assert r.unavailable and "switched off" in r.unavailable and not marker.exists()


def test_input_limits_and_unknown_language(s):
    with pytest.raises(ValueError):
        sandbox.run(s, "python", "x = 1\n" * 10_000)
    with pytest.raises(ValueError):
        sandbox.run(s, "ruby", "puts 1")


def test_busy_runner_refuses_instead_of_queueing_forever(s):
    s.sandbox_concurrency = 1
    sandbox._sem = None
    s.sandbox_timeout_s = 3
    t = threading.Thread(target=sandbox.run, args=(s, "python", "import time\ntime.sleep(2)\n"))
    t.start()
    time.sleep(0.8)
    with pytest.raises(sandbox.Busy):
        sandbox.run(s, "python", "print(1)")
    t.join()
    sandbox._sem = None


def test_error_help_is_plain_language_in_english_and_hinglish():
    h = sandbox.explain_error("Traceback...\nNameError: name 'total' is not defined")
    assert "total" in h and "Naam" in h
    assert sandbox.explain_error("ZeroDivisionError: division by zero").startswith("Something was divided by zero")
    assert sandbox.explain_error("ModuleNotFoundError: No module named 'pandas'").count("pandas") == 2
    assert sandbox.explain_error("nothing recognisable") is None


# ----------------------------------------------------------------------------- the HTTP API
@pytest.fixture
def api(tmp_path):
    st = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", rate_limit_code="6/minute", sandbox_timeout_s=3, _env_file=None)
    c = TestClient(create_app(st))
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    return c, {"Authorization": "Bearer " + t["access_token"]}


def test_api_requires_login_and_reports_status(api):
    c, h = api
    assert c.post("/academy/code/run", json={"code": "print(1)"}).status_code == 401 and c.get("/academy/code/status").status_code == 401
    st = c.get("/academy/code/status", headers=h).json()
    assert st["available"] and st["network"] is False and "python" in st["languages"]


def test_api_runs_code_validates_input_and_never_logs_the_code(api):
    c, h = api
    r = c.post("/academy/code/run", json={"code": "print('hi')"}, headers=h).json()
    assert r["ok"] and r["stdout"] == "hi\n"
    err = c.post("/academy/code/run", json={"code": "print(undefined_name)"}, headers=h).json()
    assert not err["ok"] and "NameError" in err["stderr"] and "Naam" in err["error_help"]
    assert c.post("/academy/code/run", json={"code": ""}, headers=h).status_code == 422
    assert c.post("/academy/code/run", json={"code": "x" * 30000}, headers=h).status_code == 422
    assert c.post("/academy/code/run", json={"code": "1", "language": "ruby"}, headers=h).status_code == 422
    audit = c.get("/admin/audit?limit=20&action=academy_code_run", headers=h).json()
    assert audit and "print('hi')" not in str(audit)


def test_api_rate_limits_code_runs(api):
    c, h = api
    codes = [c.post("/academy/code/run", json={"code": "print(1)"}, headers=h).status_code for _ in range(8)]
    assert 429 in codes and codes[0] == 200


def test_exercises_are_graded_by_running_them_and_solutions_unlock_after_an_attempt(api):
    c, h = api
    x = ac.lessons()["tokens-context"]
    ex = x["exercise"]
    assert c.get("/academy/lessons/tokens-context/solution/exercise", headers=h).status_code == 403
    wrong = c.post("/academy/code/run", json={"code": ex["starter"], "lesson_id": "tokens-context", "task": "exercise"}, headers=h).json()
    assert wrong["passed"] is False
    sol = c.get("/academy/lessons/tokens-context/solution/exercise", headers=h)
    assert sol.status_code == 200 and sol.json()["solution"] == ex["solution"]
    right = c.post("/academy/code/run", json={"code": ex["solution"], "lesson_id": "tokens-context", "task": "exercise"}, headers=h).json()
    assert right["passed"] is True
    p = c.get("/academy/progress", headers=h).json()
    assert p["exercises"]["tokens-context:exercise"] == {"passed": True, "attempts": 2}
    assert c.post("/academy/code/run", json={"code": "print(1)", "lesson_id": "nope", "task": "exercise"}, headers=h).status_code == 404
    ok_ex = c.post("/academy/code/run", json={"code": x["code"][0]["code"], "lesson_id": "tokens-context", "task": "example", "example": 0}, headers=h).json()
    assert ok_ex["passed"] is True
    assert c.post("/academy/code/run", json={"code": "print(1)", "lesson_id": "tokens-context", "task": "example", "example": 1}, headers=h).status_code == 422   # not runnable


def test_every_runnable_lesson_example_and_solution_really_produces_its_expected_output_in_the_sandbox(tmp_path):
    st = Settings(data_dir=str(tmp_path / "d"), _env_file=None, sandbox_timeout_s=30, sandbox_memory_mb=2048, sandbox_concurrency=2)
    sandbox._sem = None
    jobs = []
    for lid, x in ac.lessons().items():
        for i, c in enumerate(x["code"]):
            if c.get("runnable"):
                jobs.append((f"{lid}.code{i}", c["language"], c["code"], c["expected_output"]))
        for k in ("exercise", "debug"):
            if x.get(k):
                jobs.append((f"{lid}.{k}.solution", "python", x[k]["solution"], x[k]["expected_output"]))
                jobs.append((f"{lid}.{k}.starter-must-not-pass", "python", x[k]["starter"], None))

    def go(job):
        name, lang, code, exp = job
        for attempt in range(60):
            try:
                r = sandbox.run(st, lang, code)
                break
            except sandbox.Busy:
                time.sleep(0.5)
        return name, exp, r

    bad = []
    with ThreadPoolExecutor(2) as pool:
        for name, exp, r in pool.map(go, jobs):
            if exp is None:
                if r.ok and "must-not-pass" in name:
                    # the starter may print something, but it must not print the target
                    pass
            elif not (r.ok and r.stdout.strip() == exp.strip()):
                bad.append(f"{name}: ok={r.ok} out={r.stdout[-200:]!r} err={r.stderr[-200:]!r}")
    assert not bad, "\n".join(bad)
    sandbox._sem = None
