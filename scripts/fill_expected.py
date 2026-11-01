"""Authoring helper: runs every example whose expected_output is the placeholder "__FILL__" and writes the REAL output into the content file.
Usage: python scripts/fill_expected.py app/academy/content/c03_prompting.py   (review the diff: the output must also make pedagogical sense)"""
import importlib
import json
import subprocess
import sys

sys.path.insert(0, ".")

path = sys.argv[1]
mod = importlib.import_module(path.replace("/", ".").removesuffix(".py"))
src = open(path, encoding="utf-8").read()
for x in mod.LESSONS:
    jobs = [(c["code"], c["language"]) for c in x["code"] if c.get("runnable")]
    jobs += [(x[k]["solution"], "python") for k in ("exercise", "debug") if x.get(k)]
    for code, lang in jobs:
        # only examples whose expected output is the placeholder are run
        pass
marker = '"expected_output": "__FILL__"'
for x in mod.LESSONS:
    entries = [(c["code"], c["language"], c.get("expected_output")) for c in x["code"] if c.get("runnable")]
    entries += [(x[k]["solution"], "python", x[k]["expected_output"]) for k in ("exercise", "debug") if x.get(k)]
    for code, lang, exp in entries:
        if exp != "__FILL__":
            continue
        cmd = ["node", "-e", code] if lang == "javascript" else [sys.executable, "-I", "-c", code]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if r.returncode:
            sys.exit(f"{x['id']}: example failed:\n{r.stderr[-600:]}")
        out = r.stdout.rstrip("\n")
        print(f"--- {x['id']}\n{out}")
        i = src.index(marker)
        src = src[:i] + '"expected_output": ' + json.dumps(out, ensure_ascii=False) + src[i + len(marker):]
open(path, "w", encoding="utf-8").write(src)
