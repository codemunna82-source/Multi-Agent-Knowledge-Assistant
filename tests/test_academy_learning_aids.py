"""Learning aids: goal paths, spaced repetition, task test cases, bigger hints and lesson feedback."""
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.academy import service as ac
from app.academy import tasktests
from app.api import create_app
from app.config import Settings
from app.db import AcademyExercise, AcademyQuizAttempt, User
from app.service import Knowledge

PW = "correct horse battery"


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", _env_file=None)
    k = Knowledge(s)
    c = TestClient(create_app(s, k))
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    adm = {"Authorization": "Bearer " + t["access_token"]}
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=adm)
    u = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"]}
    return c, adm, u, k


def test_goal_paths_are_in_the_catalog_and_every_lesson_exists():
    cat = ac.catalog()
    assert {p["id"] for p in cat["paths"]} >= {"new-to-ai", "doc-chatbot", "agent-builder", "go-live", "interview-ready"}
    ls = ac.lessons()
    for p in cat["paths"]:
        assert len(p["lessons"]) >= 5 and all(l in ls for l in p["lessons"]) and all(p["title"][lang] for lang in ("en", "hi", "hinglish"))


# ----------------------------------------------------------------------------- spaced repetition
def test_review_schedule_wrong_comes_back_now_and_right_answers_wait_longer(env):
    c, adm, u, k = env
    qs = [q["id"] for x in ac.lessons().values() for q in x["quiz"]][:4]
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    with k.db.session() as s:
        s.add(AcademyQuizAttempt(user_id="u1", lesson_id="l", question_id=qs[0], correct=False, created_at=t0))                                   # wrong: due at once
        s.add(AcademyQuizAttempt(user_id="u1", lesson_id="l", question_id=qs[1], correct=True, created_at=t0))                                    # 1 correct: due after 1 day
        for i in range(3):                                                                                                                        # 3 correct in a row: due after 7 days
            s.add(AcademyQuizAttempt(user_id="u1", lesson_id="l", question_id=qs[2], correct=True, created_at=t0))
        s.add(AcademyQuizAttempt(user_id="u1", lesson_id="l", question_id=qs[3], correct=False, created_at=t0))                                   # wrong then right: box 1
        s.add(AcademyQuizAttempt(user_id="u1", lesson_id="l", question_id=qs[3], correct=True, created_at=t0))
    with k.db.session() as s:
        r = ac.due_reviews(s, "u1", now=t0 + timedelta(hours=1))
        assert [d["id"] for d in r["due"]] == [qs[0]] and r["scheduled_later"] == 3
        r = ac.due_reviews(s, "u1", now=t0 + timedelta(days=1, hours=1))
        assert {d["id"] for d in r["due"]} == {qs[0], qs[1], qs[3]} and r["scheduled_later"] == 1
        r = ac.due_reviews(s, "u1", now=t0 + timedelta(days=8))
        assert {d["id"] for d in r["due"]} == set(qs) and r["scheduled_later"] == 0
        assert all("answer" not in d and "why" not in d for d in r["due"])                        # review questions never reveal answers


def test_review_endpoint_is_private_and_a_wrong_answer_shows_up(env):
    c, adm, u, k = env
    assert c.get("/academy/review", headers=u).json() == {"due": [], "due_total": 0, "scheduled_later": 0}
    q = next(iter(ac.lessons().values()))["quiz"][0]
    c.post("/academy/quiz/submit", json={"answers": {q["id"]: (q["answer"] + 1) % len(q["options"])}}, headers=u)
    r = c.get("/academy/review", headers=u).json()
    assert [d["id"] for d in r["due"]] == [q["id"]] and r["due"][0]["box"] == 0
    assert c.get("/academy/review", headers=adm).json()["due"] == []                            # another user sees nothing
    assert c.get("/academy/review").status_code == 401


# ----------------------------------------------------------------------------- task tests
TESTS = [{"name": "double", "call": "f(2)", "expect": "4"}, {"name": "none", "call": "f(None)", "expect": "None", "hidden": True}, {"name": "boom", "call": "1/0", "expect": "1"}]


def run(code, tests):
    r = subprocess.run([sys.executable, "-I", "-c", tasktests.build_script(code, tests)], capture_output=True, text=True, timeout=60)
    return tasktests.parse(r.stdout, tests)


def test_task_tests_report_each_check_hide_hidden_values_and_survive_exceptions():
    out, res = run("def f(x):\n    return x * 2\nprint('learner output')", TESTS)
    assert out == "learner output\n"                                                                 # check lines never leak into the learner's console
    assert [(t["name"], t["passed"]) for t in res] == [("double", True), ("none", False), ("boom", False)]
    assert res[0]["got"] == "4" and "got" not in res[1] and "expect" not in res[1] and res[2]["got"] == "!ZeroDivisionError"


def test_a_program_that_crashes_early_fails_every_check_without_hanging():
    out, res = run("raise SystemExit(3)\ndef f(x):\n    return x", TESTS)
    assert all(not t["passed"] for t in res)


def test_every_lesson_with_tests_passes_them_with_the_solution_and_fails_with_the_starter():
    seen = 0
    for lid, x in ac.lessons().items():
        for k in ("exercise", "debug"):
            tests = (x.get(k) or {}).get("tests")
            if not tests:
                continue
            seen += 1
            assert all(t["passed"] for t in run(x[k]["solution"], tests)[1]), (lid, k)
            assert not all(t["passed"] for t in run(x[k]["starter"], tests)[1]), (lid, k)
    assert seen >= 5


def test_public_lesson_never_sends_hidden_expectations_or_solutions():
    x = ac.lessons()["docker-basics"]
    pub = ac.public_lesson(x)["exercise"]
    assert "solution" not in pub
    hidden = [t for t in pub["tests"] if t["hidden"]]
    assert hidden and all(set(t) == {"name", "hidden"} for t in hidden)
    assert all("expect" in t and "call" in t for t in pub["tests"] if not t["hidden"])


# ----------------------------------------------------------------------------- bigger hint
def test_bigger_hint_unlocks_after_an_attempt_and_shows_only_part_of_the_solution(env):
    c, adm, u, k = env
    assert c.get("/academy/lessons/docker-basics/hint/exercise", headers=u).status_code == 403
    with k.db.session() as s:
        uid = s.scalar(select(User.id).where(User.email == "u@acme.io"))
        s.add(AcademyExercise(user_id=uid, lesson_id="docker-basics", kind="exercise", passed=False, attempts=1))
    r = c.get("/academy/lessons/docker-basics/hint/exercise", headers=u)
    assert r.status_code == 200
    j = r.json()
    sol = ac.lessons()["docker-basics"]["exercise"]["solution"]
    assert j["lines_total"] >= 1 and j["lines_shown"] <= j["lines_total"] and j["hint"].strip().splitlines()[0].strip() in sol


# ----------------------------------------------------------------------------- feedback
def test_feedback_is_saved_summarised_for_admins_only_and_erased_with_the_user(env):
    c, adm, u, k = env
    lid = next(iter(ac.lessons()))
    assert c.post("/academy/feedback", json={"lesson_id": lid, "helpful": False, "step": "code", "comment": "the output was confusing"}, headers=u).status_code == 201
    assert c.post("/academy/feedback", json={"lesson_id": lid, "helpful": True}, headers=u).status_code == 201
    assert c.post("/academy/feedback", json={"lesson_id": "nope", "helpful": True}, headers=u).status_code == 404
    assert c.post("/academy/feedback", json={"lesson_id": lid, "helpful": False, "step": "bogus"}, headers=u).status_code == 422
    assert c.get("/academy/feedback/summary", headers=u).status_code == 403
    summary = c.get("/academy/feedback/summary", headers=adm).json()
    assert summary[0] == {"lesson": lid, "helpful": 1, "not_helpful": 1, "confusing_steps": {"code": 1}, "comments": ["the output was confusing"]}
    uid = next(x["id"] for x in c.get("/admin/users", headers=adm).json() if x["email"] == "u@acme.io")
    assert c.delete(f"/admin/users/{uid}", headers=adm).status_code in (200, 204)
    assert c.get("/academy/feedback/summary", headers=adm).json() == []
