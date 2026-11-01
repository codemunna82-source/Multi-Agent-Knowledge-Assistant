import re

from app.academy import service as ac
from app.academy.catalog import CATEGORIES, LANGS, ROADMAP


def test_content_validates_with_no_problems():
    assert ac.validate() == []


def test_every_category_has_lessons_and_ids_are_unique():
    ls = ac.lessons()
    assert len(ls) >= 24
    assert {x["category"] for x in ls.values()} == {c[0] for c in CATEGORIES}          # all 15 categories have at least one real lesson
    assert len({q["id"] for x in ls.values() for q in x["quiz"]}) == sum(len(x["quiz"]) for x in ls.values())


def test_every_text_exists_in_english_hindi_and_hinglish_and_hindi_is_devanagari():
    for lid, x in ac.lessons().items():
        for field, v in x["text"].items():
            if field == "mistakes":
                continue
            assert all(v[lang].strip() for lang in LANGS), (lid, field)
            assert re.search(r"[ऀ-ॿ]", v["hi"]), (lid, field, "Hindi text must be in Devanagari")
            assert not re.search(r"[ऀ-ॿ]", v["hinglish"]), (lid, field, "Hinglish must be Roman script")


def test_lesson_graph_is_acyclic_and_roadmap_points_to_real_lessons():
    ls = ac.lessons()
    seen: set[str] = set()

    def visit(lid, stack):
        assert lid not in stack, f"prerequisite cycle through {lid}"
        if lid in seen:
            return
        for p in ls[lid]["prereq"]:
            visit(p, stack | {lid})
        seen.add(lid)

    for lid in ls:
        visit(lid, frozenset())
    for lvl, items in ROADMAP.items():
        assert all(lid in ls for _, lid in items if lid), lvl
    assert any(lid is None for items in ROADMAP.values() for _, lid in items)           # planned topics are honest, not hidden


def test_non_runnable_examples_say_what_they_need_and_do_not_claim_output():
    for lid, x in ac.lessons().items():
        for c in x["code"]:
            if not c["runnable"]:
                assert c["setup"] and "expected_output" not in c, (lid, c["title"])


def test_every_lesson_cites_official_looking_https_sources():
    for lid, x in ac.lessons().items():
        assert all(s["url"].startswith("https://") and s["title"] for s in x["sources"]), lid


def test_public_lessons_never_send_null_lists():
    for lid, x in ac.lessons().items():
        y = ac.public_lesson(x)
        for k in ("viz", "prereq", "sources", "code", "projects", "tags", "quiz"):
            assert isinstance(y[k], list), (lid, k)
