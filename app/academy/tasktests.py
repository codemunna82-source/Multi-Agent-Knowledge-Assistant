"""Extra checks for practice tasks: a task may list `tests` = [{name, call, expect, hidden?}].

Each `call` is an expression written by the course author (trusted content) that is evaluated AFTER the learner's code in the same sandbox run;
its repr() is compared with `expect`. A call that raises counts as a failed test and the other tests still run. Hidden tests show only
their name and pass/fail, so learners cannot special-case the answer."""
from __future__ import annotations

MARK = "@@T"


def build_script(code: str, tests: list[dict]) -> str:
    lines = [code.rstrip("\n"), ""]
    for i, t in enumerate(tests):
        lines += ["try:", f"    print({MARK + str(i) + ' '!r} + repr({t['call']}), flush=True)",
                  "except BaseException as _e:", f"    print({MARK + str(i) + ' !'!r} + type(_e).__name__, flush=True)"]
    return "\n".join(lines) + "\n"


def parse(stdout: str, tests: list[dict]) -> tuple[str, list[dict]]:
    """-> (stdout without the check lines, one result per test: {name, passed, hidden, got?, expect?})"""
    got: dict[int, str] = {}
    keep = []
    for line in stdout.splitlines():
        if line.startswith(MARK):
            head, _, val = line[len(MARK):].partition(" ")
            if head.isdigit():
                got[int(head)] = val
                continue
        keep.append(line)
    results = []
    for i, t in enumerate(tests):
        v = got.get(i)
        ok = v is not None and v == t["expect"]
        r = {"name": t["name"], "passed": ok, "hidden": bool(t.get("hidden"))}
        if not t.get("hidden"):
            r.update(expect=t["expect"], got=v if v is not None else "(the program stopped before this check)")
        results.append(r)
    return "\n".join(keep) + ("\n" if keep else ""), results
