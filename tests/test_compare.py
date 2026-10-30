from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.core import Unit
from app.intel import compare as cmp
from app.intel import contradict as contra
from app.service import Knowledge

from .conftest import ask, upload
from .fakes import FakeLLM

POLICY_V1 = (b"Employees accrue 25 days of annual leave per year. Expense reports must be filed within 30 days.\n\n"
             b"Remote work is allowed three days per week. Managers approve all schedules. The office closes at 6 pm.")
POLICY_V2 = (b"Employees accrue 30 days of annual leave per year. Expense reports must be filed within 30 days.\n\n"
             b"Remote work is allowed three days per week. Managers approve all schedules. A new wellness stipend of 500 dollars is offered.")


def units(text):
    return [Unit(p, {"paragraph": i + 1}) for i, p in enumerate(text.split("\n\n"))]


def test_segment_diff_pairs_edits_and_reports_number_changes():
    d = cmp.compare_units(units(POLICY_V1.decode()), units(POLICY_V2.decode()))
    s = d["summary"]
    assert (s["unchanged"], s["changed"], s["added"], s["removed"], s["similarity"]) == (3, 1, 1, 1, 0.6)
    ch = [c for c in d["changed"] if c["number_changes"]]
    assert ch and ch[0]["number_changes"] == [{"from": "25", "to": "30"}]
    assert "office closes" in d["removed"][0]["text"] and "wellness stipend" in d["added"][0]["text"]
    assert cmp.compare_units(units("a b c d. e f g h."), units("a b c d. e f g h."))["summary"]["similarity"] == 1.0
    assert cmp.compare_units([], units("Hello world here."))["summary"]["added"] == 1


def test_whole_document_compare_through_chat(client):
    upload(client, "a.txt", POLICY_V1)
    upload(client, "b.txt", POLICY_V2)
    r = ask(client, "Compare a.txt and b.txt")
    assert r["route"] == "compare" and "25 → 30" in r["answer"] and "wellness stipend" in r["answer"] and "office closes" in r["answer"]
    d = r["details"]["diff"]
    assert d["summary"]["changed"] >= 1 and d["summary"]["unchanged"] >= 2
    assert {c["source"] for c in r["citations"]} == {"a.txt", "b.txt"} and all(c["loc"] for c in r["citations"])


def test_version_change_detection_after_reupload(client):
    upload(client, "policy.txt", POLICY_V1)
    second = upload(client, "policy.txt", POLICY_V2)
    assert second["source"]["version"] == 2
    r = ask(client, "What changed in policy.txt?")
    assert r["route"] == "compare" and "v1 → policy.txt v2" in r["answer"] and "25 → 30" in r["answer"]
    assert {c["version"] for c in r["citations"] if c.get("version")} == {1, 2}


# ----------------------------------------------------------------------------- contradictions
def P(src, text, n=1):
    return {"source_id": src, "source": src, "loc": {"paragraph": n}, "text": text}


def test_contradiction_candidates_by_kind():
    ps = [P("hr", "Employees accrue 25 days of annual leave every year."), P("faq", "Employees accrue 30 days of annual leave every year."),
          P("a", "Contractors are allowed to work remotely from other countries."), P("b", "Contractors are not allowed to work remotely from other countries."),
          P("c", "Attendance at the quarterly review meeting is mandatory for all managers."), P("d", "Attendance at the quarterly review meeting is optional for all managers."),
          P("x", "The cafeteria serves lunch between noon and two in the afternoon every day.")]
    out = contra.candidates(ps)
    kinds = {(c["a"]["source"], c["b"]["source"]): c["type"] for c in out}
    assert kinds[("hr", "faq")] == "numeric" and kinds[("a", "b")] == "negation" and kinds[("c", "d")] == "antonym"
    assert not any("x" in (c["a"]["source"], c["b"]["source"]) for c in out)


def test_no_false_positive_for_agreeing_or_unrelated_text():
    ps = [P("a", "Employees accrue 25 days of annual leave every year."), P("b", "Every year employees accrue 25 days of annual leave."), P("c", "Totally different subject about parking spaces and bicycles.")]
    assert contra.candidates(ps) == []
    same_doc = [P("a", "Leave is 25 days per year for staff members.", 1), P("a", "Leave is 30 days per year for staff members.", 2)]
    assert contra.candidates(same_doc, cross_only=True) == [] and len(contra.candidates(same_doc, cross_only=False)) == 1


def test_hindi_negation_is_detected():
    ps = [P("a", "कर्मचारियों को घर से काम करने की अनुमति है सप्ताह में तीन दिन"), P("b", "कर्मचारियों को घर से काम करने की अनुमति नहीं है सप्ताह में तीन दिन")]
    assert [c["type"] for c in contra.candidates(ps)] == ["negation"]


def test_llm_judge_filters_candidates_and_degrades_on_failure():
    ps = [P("hr", "Employees accrue 25 days of annual leave every year."), P("faq", "Employees accrue 30 days of annual leave every year.")]
    yes = contra.find(ps, FakeLLM(lambda s, u: '{"contradiction": true, "reason": "25 vs 30 days"}'))
    assert yes["method"] == "llm" and yes["contradictions"][0]["verdict"] == "confirmed" and yes["contradictions"][0]["reason"] == "25 vs 30 days"
    no = contra.find(ps, FakeLLM(lambda s, u: '{"contradiction": false}'))
    assert no["contradictions"] == []
    down = contra.find(ps, FakeLLM(fail=True))
    assert down["method"] == "heuristic" and down["contradictions"][0]["verdict"] == "candidate"


def test_contradiction_question_through_chat_is_honest_about_heuristics(client):
    upload(client, "hr.txt", b"Employees accrue 25 days of annual leave every year.")
    upload(client, "faq.txt", b"Employees accrue 30 days of annual leave every year.")
    r = ask(client, "Do hr.txt and faq.txt contradict each other?")
    assert r["route"] == "compare" and "candidate contradiction" in r["answer"] and "25 days" in r["answer"] and "30 days" in r["answer"]
    assert "candidates to review" in " ".join(r["limitations"]) and r["details"]["method"] == "heuristic"
    assert {c["source"] for c in r["citations"]} == {"hr.txt", "faq.txt"}


def test_contradiction_question_with_llm_confirms(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, llm=FakeLLM(lambda sy, u: '{"contradiction": true, "reason": "different leave"}' if "contradict" in sy else "OK"))))
    upload(c, "hr.txt", b"Employees accrue 25 days of annual leave every year.")
    upload(c, "faq.txt", b"Employees accrue 30 days of annual leave every year.")
    r = ask(c, "Are there contradictions between hr.txt and faq.txt?")
    assert "1 confirmed contradiction" in r["answer"] and "different leave" in r["answer"]


def test_topic_comparison_flags_conflicts(client):
    upload(client, "hr.txt", b"Remote work policy. Employees may work remotely three days per week with manager approval.")
    upload(client, "faq.txt", b"Remote work policy. Employees may work remotely five days per week with manager approval.")
    r = ask(client, "Compare hr.txt and faq.txt on remote work days per week")
    assert r["route"] == "compare" and {c["source"] for c in r["citations"]} == {"hr.txt", "faq.txt"}
