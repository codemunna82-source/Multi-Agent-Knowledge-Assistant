"""Authoring check for Academy content: structural validation + executes every runnable example, exercise solution and debug solution
(in-process here for speed; tests/test_academy_content.py runs the same code inside the sandbox) and compares the output."""
import contextlib
import io
import subprocess
import sys

sys.path.insert(0, ".")
from app.academy import service as ac  # noqa: E402

bad = ac.validate()
for lid, x in ac.lessons().items():
    jobs = [(f"{lid}:code{i}", c["code"], c["expected_output"], c["language"]) for i, c in enumerate(x["code"]) if c.get("runnable")]
    for k in ("exercise", "debug"):
        if x.get(k):
            jobs.append((f"{lid}:{k}", x[k]["solution"], x[k]["expected_output"], "python"))
    for name, code, exp, lang in jobs:
        if lang == "javascript":
            r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=20)
            out = r.stdout
        else:
            r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
            out = r.stdout
        if out.strip() != exp.strip():
            bad.append(f"{name}: output differs\n--- expected\n{exp}\n--- got\n{out}\n{r.stderr[-300:]}")
# a starter must NOT already pass, or the challenge teaches nothing
for lid, x in ac.lessons().items():
    for k in ("exercise", "debug"):
        if x.get(k):
            r = subprocess.run([sys.executable, "-I", "-c", x[k]["starter"]], capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip() == x[k]["expected_output"].strip():
                bad.append(f"{lid}:{k}: the starter code already produces the expected output")
print("lessons:", len(ac.lessons()), "glossary:", len(ac.glossary()))
print("\n".join(bad) if bad else "OK: all lessons valid and all runnable code produces its expected output")
sys.exit(1 if bad else 0)
