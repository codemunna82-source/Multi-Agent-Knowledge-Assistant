"""Academy content access (cached), validation, and learner progress logic."""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Optional

from sqlalchemy import delete, func, select

from ..db import AcademyActivity, AcademyExercise, AcademyProgress, AcademyProject, AcademyQuizAttempt
from .catalog import CATEGORIES, LANGS, LEVELS, ROADMAP

TEXT_FIELDS = ("definition", "analogy", "technical", "why", "example", "interview", "mistakes")
SECRET_LESSON_KEYS = ("answer", "why", "why_not")           # quiz fields revealed only after submitting
TERM_RE = re.compile(r"\{\{([a-z0-9-]+)\|([^}]+)\}\}")


@lru_cache(maxsize=1)
def lessons() -> dict[str, dict]:
    from .content import load_lessons

    return {x["id"]: x for x in load_lessons()}


@lru_cache(maxsize=1)
def glossary() -> dict[str, dict]:
    from .content.glossary import GLOSSARY

    return GLOSSARY


@lru_cache(maxsize=1)
def projects() -> dict[str, dict]:
    try:
        from .content.projects import PROJECTS
    except ModuleNotFoundError:
        return {}
    return {p["id"]: p for p in PROJECTS}


@lru_cache(maxsize=1)
def extra_interview() -> list[dict]:
    try:
        from .content.interview_extra import EXTRA
    except ModuleNotFoundError:
        return []
    return EXTRA


def category_ids() -> list[str]:
    return [c[0] for c in CATEGORIES]


# ----------------------------------------------------------------------------- validation (used by tests and at import in dev)
def validate() -> list[str]:
    """Returns a list of problems; an empty list means every lesson is complete in all three languages and internally consistent."""
    bad: list[str] = []
    ls, gl = lessons(), glossary()
    cats = set(category_ids())
    for lid, x in ls.items():
        p = f"lesson {lid}"
        if x["category"] not in cats:
            bad.append(f"{p}: unknown category {x['category']}")
        if x["level"] not in LEVELS:
            bad.append(f"{p}: bad level")
        for k in ("title", *TEXT_FIELDS):
            v = x.get(k) if k == "title" else x["text"].get(k)
            if not isinstance(v, dict) or any(not v.get(lang) for lang in LANGS):
                bad.append(f"{p}: '{k}' is missing a language")
        for k in ("mistakes",):
            for lang in LANGS:
                if not isinstance(x["text"][k].get(lang), list) or len(x["text"][k][lang]) < 2:
                    bad.append(f"{p}: mistakes[{lang}] needs a list of at least 2")
            if len({len(x["text"][k][lang]) for lang in LANGS}) != 1:
                bad.append(f"{p}: mistakes lists differ in length across languages")
        for k in ("objectives", "sources", "quiz", "interview_questions", "assignment", "minutes"):
            if not x.get(k):
                bad.append(f"{p}: missing {k}")
        if not x.get("code"):
            bad.append(f"{p}: needs at least one code example")
        for i, c in enumerate(x.get("code", [])):
            if c.get("runnable") and "expected_output" not in c:
                bad.append(f"{p}: runnable code[{i}] needs expected_output")
            if not c.get("runnable") and not c.get("setup"):
                bad.append(f"{p}: non-runnable code[{i}] needs setup instructions (what is needed to run it)")
            if not c.get("explain"):
                bad.append(f"{p}: code[{i}] needs a line-by-line explanation")
        ex = x.get("exercise")
        if not ex or not all(ex.get(k) is not None for k in ("prompt", "starter", "expected_output", "solution", "hint")):
            bad.append(f"{p}: exercise incomplete")
        for q in x.get("quiz", []):
            n = len(q["options"])
            if not (2 <= n <= 5) or not (0 <= q["answer"] < n) or not q.get("why") or set(q["why_not"]) != {str(i) for i in range(n) if i != q["answer"]}:
                bad.append(f"{p}: quiz {q.get('id')} is inconsistent (answer / why / why_not)")
        qids = [q["id"] for q in x.get("quiz", [])]
        if len(qids) != len(set(qids)) or any(not i.startswith(lid + ".") for i in qids):
            bad.append(f"{p}: quiz ids must be unique and prefixed '{lid}.'")
        for ref in x.get("prereq", []) + x.get("next", []):
            if ref not in ls:
                bad.append(f"{p}: unknown related lesson {ref}")
        for u in x.get("sources", []):
            if not str(u.get("url", "")).startswith("https://"):
                bad.append(f"{p}: source needs an https url")
        blob = " ".join(_all_text(x["text"]))
        for tid, _ in TERM_RE.findall(blob):
            if tid not in gl:
                bad.append(f"{p}: glossary term '{tid}' is not defined")
    for tid, g in gl.items():
        if any(not g.get(lang) for lang in LANGS):
            bad.append(f"glossary {tid}: missing language")
    for lvl, items in ROADMAP.items():
        for title, lid in items:
            if lid and lid not in ls:
                bad.append(f"roadmap {lvl}/{title}: lesson {lid} does not exist")
    return bad


def _all_text(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [t for v in node.values() for t in _all_text(v)]
    if isinstance(node, list):
        return [t for v in node for t in _all_text(v)]
    return []


# ----------------------------------------------------------------------------- views
def public_lesson(x: dict) -> dict:
    """The lesson as the learner may see it: quiz answers/explanations, exercise solutions stay on the server."""
    y = copy.deepcopy(x)
    for k in ("viz", "prereq", "sources", "code", "projects", "tags"):
        if y.get(k) is None:
            y[k] = []                             # lists are always lists on the wire; a lesson that has no animation must not send null
    for q in y["quiz"]:
        for k in SECRET_LESSON_KEYS:
            q.pop(k, None)
    for k in ("exercise", "debug"):
        if y.get(k):
            y[k].pop("solution", None)          # the target output stays visible (the learner needs a goal); the solution is revealed on request after an attempt
    return y


def lesson_card(x: dict) -> dict:
    return {"id": x["id"], "category": x["category"], "level": x["level"], "minutes": x["minutes"], "title": x["title"], "summary": x["summary"], "has_viz": bool(x.get("viz")),
            "has_exercise": bool(x.get("exercise")), "prereq": x.get("prereq", []), "tags": x.get("tags", [])}


def catalog() -> dict:
    ls = lessons()
    return {
        "categories": [{"id": c[0], "title": {"en": c[1], "hi": c[2]}, "summary": c[3], "lessons": [lesson_card(x) for x in ls.values() if x["category"] == c[0]]} for c in CATEGORIES],
        "roadmap": {lvl: [{"title": t, "lesson": lid, "planned": lid is None} for t, lid in items] for lvl, items in ROADMAP.items()},
        "languages": list(LANGS),
    }


def search(q: str, limit: int = 20) -> list[dict]:
    terms = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]
    if not terms:
        return []
    out = []
    for x in lessons().values():
        hay = " ".join([x["title"]["en"], x["summary"], " ".join(x.get("tags", [])), x["text"]["definition"]["en"], x["text"]["definition"]["hinglish"], x["title"]["hi"]]).lower()
        score = sum(3 if t in x["title"]["en"].lower() else 1 for t in terms if t in hay)
        if score:
            out.append((score, lesson_card(x)))
    for tid, g in glossary().items():
        if any(t in (tid + " " + g["term"] + " " + g["en"]).lower() for t in terms):
            out.append((1, {"glossary": tid, "term": g["term"]}))
    out.sort(key=lambda r: -r[0])
    return [r for _, r in out[:limit]]


# ----------------------------------------------------------------------------- progress
def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def touch_activity(s, user_id: str, n: int = 1) -> None:
    row = s.scalar(select(AcademyActivity).where(AcademyActivity.user_id == user_id, AcademyActivity.day == _today()))
    if row:
        row.count += n
    else:
        s.add(AcademyActivity(user_id=user_id, day=_today(), count=n))


def streak(days: set[str], today: Optional[date] = None) -> int:
    d = today or datetime.now(UTC).date()
    if d.isoformat() not in days:
        d -= timedelta(days=1)         # a streak is still alive until the end of the next day
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def set_progress(s, user_id: str, lesson_id: str, status: Optional[str], step: Optional[int], bookmarked: Optional[bool]) -> AcademyProgress:
    row = s.scalar(select(AcademyProgress).where(AcademyProgress.user_id == user_id, AcademyProgress.lesson_id == lesson_id))
    if row is None:
        row = AcademyProgress(user_id=user_id, lesson_id=lesson_id, status="in_progress", step=0, bookmarked=False)
        s.add(row)
    if step is not None:
        row.step = max(row.step, step)          # progress only moves forward: scrolling back up never loses the resume point
    if bookmarked is not None:
        row.bookmarked = bookmarked
    if status is not None:
        row.status = status
        row.completed_at = datetime.now(UTC) if status == "done" else None
    row.updated_at = datetime.now(UTC)
    if status or step is not None:
        touch_activity(s, user_id)
    return row


def grade(s, user_id: str, answers: dict[str, int]) -> dict:
    """Grades answers server-side and records the attempts. Unknown question ids are ignored."""
    index = {q["id"]: (x["id"], q) for x in lessons().values() for q in x["quiz"]}
    results, now_ok = [], 0
    for qid, sel in answers.items():
        if qid not in index:
            continue
        lid, q = index[qid]
        ok = sel == q["answer"]
        now_ok += ok
        s.add(AcademyQuizAttempt(user_id=user_id, lesson_id=lid, question_id=qid, correct=ok))
        results.append({"id": qid, "lesson": lid, "selected": sel, "correct": ok, "answer": q["answer"], "why": q["why"], "why_not": q["why_not"], "options": q["options"]})
    if results:
        touch_activity(s, user_id, len(results))
    return {"results": results, "score": now_ok, "total": len(results), "percent": round(100 * now_ok / len(results)) if results else None}


def overview(s, user_id: str) -> dict:
    ls = lessons()
    prog = {r.lesson_id: r for r in s.scalars(select(AcademyProgress).where(AcademyProgress.user_id == user_id))}
    done = {k for k, r in prog.items() if r.status == "done"}
    ex = {(r.lesson_id, r.kind): r for r in s.scalars(select(AcademyExercise).where(AcademyExercise.user_id == user_id))}
    attempts = s.execute(select(AcademyQuizAttempt.lesson_id, AcademyQuizAttempt.question_id, AcademyQuizAttempt.correct, AcademyQuizAttempt.id).where(AcademyQuizAttempt.user_id == user_id).order_by(AcademyQuizAttempt.id)).all()
    latest: dict[str, tuple[str, bool]] = {}
    for lid, qid, ok, _ in attempts:
        latest[qid] = (lid, ok)              # only the most recent attempt of each question counts
    by_lesson: dict[str, list[bool]] = {}
    for _qid, (lid, ok) in latest.items():
        by_lesson.setdefault(lid, []).append(ok)
    quiz = {lid: {"correct": sum(v), "total": len(v), "percent": round(100 * sum(v) / len(v))} for lid, v in by_lesson.items()}
    days = {d for (d,) in s.execute(select(AcademyActivity.day).where(AcademyActivity.user_id == user_id))}
    cats = []
    for cid, title, _hi, _sum in CATEGORIES:
        members = [x for x in ls.values() if x["category"] == cid]
        n_done = sum(1 for x in members if x["id"] in done)
        cats.append({"id": cid, "title": title, "lessons": len(members), "done": n_done, "percent": round(100 * n_done / len(members)) if members else 0})
    weak = sorted([lid for lid, q in quiz.items() if q["total"] >= 2 and q["percent"] < 70], key=lambda lid: quiz[lid]["percent"])
    weak += [lid for (lid, kind), r in ex.items() if not r.passed and r.attempts >= 2 and lid not in weak]
    last = max(prog.values(), key=lambda r: r.updated_at, default=None)
    cont = None
    if last and last.status != "done":
        cont = {"lesson": last.lesson_id, "step": last.step}
    else:
        nxt = next((x["id"] for x in ls.values() if x["id"] not in done and all(p in done for p in x.get("prereq", []))), None)
        cont = {"lesson": nxt, "step": 0} if nxt else None
    recommended = [x["id"] for x in ls.values() if x["id"] not in done and all(p in done for p in x.get("prereq", []))][:4]
    return {"lessons": {k: {"status": r.status, "step": r.step, "bookmarked": r.bookmarked, "updated_at": r.updated_at.isoformat()} for k, r in prog.items()},
            "done": len(done), "total": len(ls), "percent": round(100 * len(done) / len(ls)) if ls else 0, "categories": cats, "quiz": quiz,
            "exercises": {f"{lid}:{kind}": {"passed": r.passed, "attempts": r.attempts} for (lid, kind), r in ex.items()}, "streak": streak(days), "active_days": len(days),
            "weak": weak[:6], "bookmarks": [k for k, r in prog.items() if r.bookmarked], "continue": cont, "recommended": recommended}


def record_exercise(s, user_id: str, lesson_id: str, kind: str, passed: bool) -> None:
    row = s.scalar(select(AcademyExercise).where(AcademyExercise.user_id == user_id, AcademyExercise.lesson_id == lesson_id, AcademyExercise.kind == kind))
    if row is None:
        row = AcademyExercise(user_id=user_id, lesson_id=lesson_id, kind=kind, passed=False, attempts=0)
        s.add(row)
    row.attempts += 1
    row.passed = row.passed or passed
    touch_activity(s, user_id)


def daily_questions(s, user_id: str, n: int = 5) -> list[dict]:
    """Deterministic for (user, day): mostly questions from weak lessons, the rest from lessons the learner has started or any lesson. Answers are NOT included."""
    ov = overview(s, user_id)
    pool_weak = [q for lid in ov["weak"] for q in lessons()[lid]["quiz"]]
    started = [q for lid in ov["lessons"] for q in lessons()[lid]["quiz"] if lid in lessons()]
    rest = [q for x in lessons().values() for q in x["quiz"]]
    seen: set[str] = set()
    pool = [q for q in pool_weak + started + rest if not (q["id"] in seen or seen.add(q["id"]))]
    seed = int(hashlib.sha256(f"{user_id}:{_today()}".encode()).hexdigest(), 16)
    head = pool_weak[: min(3, n)]
    tail = [q for q in pool if q not in head]
    tail.sort(key=lambda q: hashlib.sha256(f"{seed}:{q['id']}".encode()).hexdigest())
    pick = (head + tail)[:n]
    return [{"id": q["id"], "lesson": q["id"].split(".")[0], "q": q["q"], "options": q["options"], "kind": q.get("kind", "concept")} for q in pick]


def interview_bank() -> list[dict]:
    out = []
    for x in lessons().values():
        for iq in x["interview_questions"]:
            out.append({"category": x["category"], "lesson": x["id"], "level": x["level"], "q": iq["q"], "a": iq["a"]})
    out.extend(extra_interview())
    return out


def project_progress(s, user_id: str) -> dict[str, list[int]]:
    return {r.project_id: list(r.done_steps or []) for r in s.scalars(select(AcademyProject).where(AcademyProject.user_id == user_id))}


def erase_user(s, user_id: str) -> None:
    for m in (AcademyProgress, AcademyQuizAttempt, AcademyExercise, AcademyActivity, AcademyProject):
        s.execute(delete(m).where(m.user_id == user_id))


def count_rows(s, user_id: str) -> int:
    return sum(s.scalar(select(func.count()).select_from(m).where(m.user_id == user_id)) or 0 for m in (AcademyProgress, AcademyQuizAttempt, AcademyExercise, AcademyActivity, AcademyProject))
