from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.academy import service as ac
from app.academy.catalog import CATEGORIES, LANGS
from app.api import create_app
from app.config import Settings
from app.db import AcademyProgress

PW = "correct horse battery"


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_auth="10000/minute", _env_file=None)
    c = TestClient(create_app(s))
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    adm = {"Authorization": "Bearer " + t["access_token"]}
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=adm)
    u = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"]}
    return c, adm, u


def first_lesson():
    return next(iter(ac.lessons().values()))


def test_catalog_has_fifteen_categories_roadmap_and_languages(env):
    c, adm, u = env
    cat = c.get("/academy/catalog", headers=u).json()
    assert [x["id"] for x in cat["categories"]] == [x[0] for x in CATEGORIES] and len(cat["categories"]) == 15
    assert set(cat["roadmap"]) == {"beginner", "intermediate", "advanced", "production"} and cat["languages"] == list(LANGS)
    assert any(t["planned"] for t in cat["roadmap"]["production"])                      # honest: some roadmap topics have no lesson yet


def test_lesson_has_three_languages_and_hides_answers_and_solutions(env):
    c, adm, u = env
    x = first_lesson()
    r = c.get(f"/academy/lessons/{x['id']}", headers=u)
    assert r.status_code == 200
    j = r.json()
    assert set(j["text"]["definition"]) == set(LANGS) and j["title"]["hi"]
    for q in j["quiz"]:
        assert not ({"answer", "why", "why_not"} & set(q))
    assert "solution" not in j["exercise"] and j["exercise"]["expected_output"] and "solution" not in j.get("debug", {})
    assert c.get("/academy/lessons/nope", headers=u).status_code == 404


def test_quiz_is_graded_on_the_server_with_explanations(env):
    c, adm, u = env
    q = first_lesson()["quiz"][0]
    right = c.post("/academy/quiz/submit", json={"answers": {q["id"]: q["answer"]}}, headers=u).json()
    assert right["score"] == 1 and right["results"][0]["correct"] and right["results"][0]["why"]
    wrong_idx = next(i for i in range(len(q["options"])) if i != q["answer"])
    bad = c.post("/academy/quiz/submit", json={"answers": {q["id"]: wrong_idx}}, headers=u).json()
    r = bad["results"][0]
    assert not r["correct"] and r["answer"] == q["answer"] and r["why_not"][str(wrong_idx)] and bad["percent"] == 0
    assert c.post("/academy/quiz/submit", json={"answers": {"zzz.q9": 1}}, headers=u).status_code == 422


def test_progress_resume_bookmark_completion_and_continue(env):
    c, adm, u = env
    x = first_lesson()["id"]
    assert c.get("/academy/progress", headers=u).json()["continue"]["lesson"] == x      # nothing started: begin at the first lesson
    c.put(f"/academy/progress/{x}", json={"step": 4}, headers=u)
    c.put(f"/academy/progress/{x}", json={"step": 2, "bookmarked": True}, headers=u)    # going back does not lose the resume point
    p = c.get("/academy/progress", headers=u).json()
    assert p["lessons"][x]["step"] == 4 and p["lessons"][x]["bookmarked"] and p["bookmarks"] == [x] and p["continue"] == {"lesson": x, "step": 4}
    c.put(f"/academy/progress/{x}", json={"status": "done"}, headers=u)
    p = c.get("/academy/progress", headers=u).json()
    assert p["done"] == 1 and p["percent"] == round(100 / p["total"]) and p["streak"] == 1
    cat = next(k for k in p["categories"] if k["id"] == first_lesson()["category"])
    assert cat["done"] == 1 and cat["percent"] > 0
    assert c.put("/academy/progress/nope", json={"step": 1}, headers=u).status_code == 404
    assert c.put(f"/academy/progress/{x}", json={"status": "weird"}, headers=u).status_code == 422


def test_weak_topics_use_the_latest_answer_of_each_question(env):
    c, adm, u = env
    x = first_lesson()
    qs = x["quiz"]
    wrong = {q["id"]: (q["answer"] + 1) % len(q["options"]) for q in qs}
    c.post("/academy/quiz/submit", json={"answers": wrong}, headers=u)
    assert x["id"] in c.get("/academy/progress", headers=u).json()["weak"]
    c.post("/academy/quiz/submit", json={"answers": {q["id"]: q["answer"] for q in qs}}, headers=u)
    p = c.get("/academy/progress", headers=u).json()
    assert x["id"] not in p["weak"] and p["quiz"][x["id"]]["percent"] == 100               # corrected answers replace the old ones


def test_progress_is_private_per_user(env):
    c, adm, u = env
    x = first_lesson()["id"]
    c.put(f"/academy/progress/{x}", json={"status": "done"}, headers=u)
    assert c.get("/academy/progress", headers=adm).json()["done"] == 0
    assert c.get("/academy/progress", headers=u).json()["done"] == 1


def test_daily_questions_are_stable_for_a_day_and_never_reveal_answers(env):
    c, adm, u = env
    a = c.get("/academy/daily", headers=u).json()["questions"]
    b = c.get("/academy/daily", headers=u).json()["questions"]
    assert a == b and 1 <= len(a) <= 5 and all(not ({"answer", "why"} & set(q)) for q in a)


def test_search_finds_lessons_and_glossary_terms(env):
    c, adm, u = env
    word = first_lesson()["title"]["en"].split()[0]
    assert any(h.get("id") for h in c.get(f"/academy/search?q={word}", headers=u).json())
    assert any(h.get("glossary") == "rag" for h in c.get("/academy/search?q=retrieval", headers=u).json())
    assert c.get("/academy/search?q=x", headers=u).status_code in (200, 422)


def test_academy_requires_login_and_user_deletion_erases_progress(env):
    c, adm, u = env
    assert c.get("/academy/catalog").status_code == 401 and c.post("/academy/quiz/submit", json={"answers": {"a.q1": 0}}).status_code == 401
    x = first_lesson()["id"]
    c.put(f"/academy/progress/{x}", json={"status": "done"}, headers=u)
    uid = c.get("/auth/me", headers=u).json()["id"]
    assert c.delete(f"/admin/users/{uid}", headers=adm).status_code == 200
    with c.app.state.svc.db.session() as s:
        assert s.scalar(select(AcademyProgress).where(AcademyProgress.user_id == uid)) is None


def test_streak_counts_consecutive_days_and_survives_until_the_end_of_tomorrow():
    d = lambda *x: {date(2026, 11, n).isoformat() for n in x}  # noqa: E731
    today = date(2026, 11, 5)
    assert ac.streak(d(3, 4, 5), today) == 3 and ac.streak(d(3, 4), today) == 2 and ac.streak(d(1, 2), today) == 0 and ac.streak(d(5), today) == 1 and ac.streak(set(), today) == 0
