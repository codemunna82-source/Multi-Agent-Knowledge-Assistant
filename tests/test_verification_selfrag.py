import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agents.citations import validate
from app.api import create_app
from app.config import Settings
from app.rag import selfrag
from app.security.auth import ANONYMOUS
from app.service import Knowledge
from app.storage import Scope

from .conftest import SALES_ROWS, ask, make_pdf, make_xlsx, upload
from .fakes import FakeLLM

SCOPE = Scope("default", "s1")


def app_with(tmp_path, llm=None, **kw):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None, **kw)
    k = Knowledge(s, llm=llm)
    return TestClient(create_app(s, k)), k


def cite(src, loc, location, excerpt):
    return {"source_id": src["id"], "source": src["name"], "location": location, "excerpt": excerpt, "loc": loc}


# ----------------------------------------------------------------------------- citation validation
def test_validate_citations_checks_page_row_and_text(tmp_path):
    c, k = app_with(tmp_path)
    pdf = upload(c, "policy.pdf", make_pdf(["Alpha clause about leave days.", "Beta clause about travel claims and receipts."]))["source"]
    xls = upload(c, "sales.xlsx", make_xlsx({"Q1": SALES_ROWS}))["source"]
    st = k.store(SCOPE)
    good = [cite(pdf, {"page": 2}, "page 2", "Beta clause about travel claims"), cite(xls, {"sheet": "Q1", "row": 3}, "sheet 'Q1', row 3", "Employee: Bob; Region: South; Sales: 3400.5")]
    bad = [cite(pdf, {"page": 1}, "page 1", "Beta clause about travel claims and receipts"),  # real page, text is elsewhere
           cite(pdf, {"page": 99}, "page 99", "Alpha clause"),  # page does not exist
           cite(xls, {"sheet": "Q1", "row": 400}, "sheet 'Q1', row 400", "Employee: Zed; Sales: 1"),
           {"source_id": "nope", "source": "ghost.pdf", "location": "page 1", "excerpt": "x y z", "loc": {"page": 1}}]
    web = {"source_id": "web", "source": "https://x", "location": "https://x", "excerpt": "anything", "loc": None}
    keep, rep = validate(st, ANONYMOUS, good + bad + [web])
    assert keep == good + [web]
    assert (rep["checked"], rep["valid"], len(rep["invalid"]), rep["unchecked"], rep["accuracy"]) == (6, 2, 4, 1, 0.3333)
    assert sorted(i["location"] for i in rep["invalid"]) == ["page 1", "page 1", "page 99", "sheet 'Q1', row 400"]


def test_citation_check_is_reported_and_perfect_for_normal_answers(client):
    upload(client, "policy.pdf", make_pdf(["Employees accrue 25 days of annual leave per year.", "Expense reports are due in 30 days."]))
    upload(client, "sales.xlsx", make_xlsx({"Q1": SALES_ROWS}))
    for q in ("How many days of annual leave do employees get?", 'find "expense"', "Which employee has the highest sales?"):
        r = ask(client, q)
        ck = r["details"]["citation_check"]
        assert r["citations"] and ck["accuracy"] == 1.0 and ck["invalid"] == [], q


def test_citation_to_a_source_in_another_workspace_is_invalid(tmp_path):
    c, k = app_with(tmp_path)
    src = upload(c, "p.txt", b"secret text here for the test", session="alice")["source"]
    keep, rep = validate(k.store(Scope("default", "bob")), ANONYMOUS, [cite(src, {"line": 1}, "line 1", "secret text here")])
    assert keep == [] and rep["invalid"][0]["reason"] == "source not found or not accessible"
    keep, rep = validate(k.store(Scope("default", "alice")), ANONYMOUS, [cite(src, {"line": 1}, "line 1", "secret text here")])
    assert len(keep) == 1 and rep["accuracy"] == 1.0


# ----------------------------------------------------------------------------- Self-RAG
EVIDENCE = [{"i": 1, "context": "Employees accrue 25 days of annual leave per year.", "text": "Employees accrue 25 days of annual leave per year."}]


def test_critique_flags_unsupported_sentences_and_numbers():
    ans = "Employees accrue 25 days of annual leave per year [1]. The company also offers free lunches on Fridays. Leave is 40 days."
    c = selfrag.critique(ans, EVIDENCE)
    assert c["support"] == "partial" and c["unsupported"] == ["The company also offers free lunches on Fridays.", "Leave is 40 days."] and c["method"] == "lexical"
    assert selfrag.critique("Employees accrue 25 days of annual leave per year [1].", EVIDENCE)["support"] == "full"
    assert selfrag.critique("Free lunches are offered on Fridays.", EVIDENCE)["support"] == "none"


def test_refine_regenerates_once_then_drops_what_stays_unsupported():
    calls = []

    def regen(unsupported):
        calls.append(unsupported)
        return "Employees accrue 25 days of annual leave per year [1]. Free lunches are offered."

    out, rep = selfrag.refine("Employees accrue 25 days of annual leave per year [1]. Free lunches are offered.", EVIDENCE, regen, None, rounds=1)
    assert out == "Employees accrue 25 days of annual leave per year [1]." and rep["rounds"] == 1 and rep["dropped"] == ["Free lunches are offered."] and len(calls) == 1
    fixed, rep2 = selfrag.refine("Free lunches are offered.", EVIDENCE, lambda u: "Employees accrue 25 days of annual leave per year [1].", None, rounds=1)
    assert fixed.startswith("Employees accrue 25") and rep2["dropped"] == [] and rep2["final"] == "full"
    none, rep3 = selfrag.refine("Free lunches.", EVIDENCE, lambda u: "More free lunches.", None, rounds=2)
    assert none is None and rep3["rounds"] == 2 and rep3["final"] == "none"
    zero, rep4 = selfrag.refine("Free lunches.", EVIDENCE, lambda u: pytest.fail("no regeneration with rounds=0"), None, rounds=0)
    assert zero is None


def test_llm_critique_can_add_unsupported_and_degrades_on_outage():
    ans = "Employees accrue 25 days of annual leave per year [1]. They may carry over leave."
    llm = FakeLLM(lambda s, u: '{"unsupported": [1], "useful": 4}')
    c = selfrag.critique(ans, EVIDENCE, llm)
    assert c["unsupported"] == ["They may carry over leave."] and c["useful"] == 4 and c["method"] == "llm+lexical"
    assert selfrag.critique(ans, EVIDENCE, FakeLLM(fail=True))["method"] == "lexical"
    assert selfrag.critique(ans, EVIDENCE, FakeLLM(lambda s, u: "not json"))["method"] == "lexical"


def test_grade_passages_filters_and_never_empties():
    ev = [{"i": 1, "text": "a"}, {"i": 2, "text": "b"}, {"i": 3, "text": "c"}]
    keep, dropped = selfrag.grade_passages("q", ev, FakeLLM(lambda s, u: '{"relevant": [1, 3]}'))
    assert [e["i"] for e in keep] == [1, 3] and dropped == [2]
    assert [e["i"] for e in selfrag.grade_passages("q", ev, FakeLLM(lambda s, u: '{"relevant": []}'))[0]] == [1]
    assert selfrag.grade_passages("q", ev, FakeLLM(lambda s, u: "garbage"))[0] == ev and selfrag.grade_passages("q", ev, None)[0] == ev


def test_should_retrieve_skips_small_talk_only():
    assert selfrag.should_retrieve("Thanks!")[0] is False and selfrag.should_retrieve("hello")[0] is False and selfrag.should_retrieve("नमस्ते")[0] is False
    assert selfrag.should_retrieve("What is the refund window?")[0] is True
    assert selfrag.should_retrieve("Hi there, status?", FakeLLM(lambda s, u: '{"retrieve": false}'))[0] is False
    assert selfrag.should_retrieve("Hi there, status?", FakeLLM(fail=True))[0] is True


def test_self_rag_end_to_end_drops_unsupported_claim(tmp_path):
    drafts = []

    def script(sy, u):
        if "Answer the question" in sy:
            drafts.append(sy)
            return "Employees accrue 25 days of annual leave per year [1]. Remote work is unlimited."
        if "relevant to answering" in sy:
            return '{"relevant": [1]}'
        return None

    c, k = app_with(tmp_path, llm=FakeLLM(script))
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    r = ask(c, "How many days of annual leave do employees get?", retrieval={"self_rag": True})
    sr = r["details"]["retrieval"]["self_rag"]
    assert "Remote work" not in r["answer"] and "25 days" in r["answer"] and sr["retrieve"] is True and sr["dropped"] == ["Remote work is unlimited."]
    assert len(drafts) == 2 and "NOT supported" in drafts[1] and any("Self-RAG removed 1" in x for x in r["limitations"])
    off = ask(c, "How many days of annual leave do employees get?")  # default: Self-RAG off -> the unsupported sentence is NOT removed here (verification handles it)
    assert "self_rag" not in off["details"]["retrieval"]


def test_self_rag_small_talk_does_not_retrieve(tmp_path):
    c, k = app_with(tmp_path)
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    r = ask(c, "thanks", retrieval={"self_rag": True})
    assert r["citations"] == [] and r["details"]["retrieval"]["self_rag"]["retrieve"] is False
    assert ask(c, "thanks")["answer"].startswith("I could not verify")  # without Self-RAG the same message is treated as a document question


# ----------------------------------------------------------------------------- cross-document diversity
def test_cross_document_questions_include_every_relevant_document(tmp_path):
    c, k = app_with(tmp_path)
    upload(c, "a.txt", b"The refund window for online purchases is 14 days. Refund requests need a receipt. Refund approvals take two days.")
    upload(c, "b.txt", b"Store purchases may be refunded within 30 days of the purchase date.")
    one = ask(c, "refund purchases", retrieval={"top_k": 1})
    assert {x["source"] for x in one["citations"]} == {"a.txt"}
    both = ask(c, "refund purchases across all documents", retrieval={"top_k": 1})
    assert {x["source"] for x in both["citations"]} == {"a.txt", "b.txt"} and both["details"]["retrieval"]["diversified_with"] == ["b.txt"]


# ----------------------------------------------------------------------------- Hindi
HINDI_A = "भारत की राजधानी नई दिल्ली है। कर्मचारियों को साल में पच्चीस दिन की छुट्टी मिलती है।\nघर से काम करने की अनुमति सप्ताह में तीन दिन है।"


def test_hindi_exact_search_semantic_and_routes(client):
    upload(client, "नीति.txt", HINDI_A.encode())
    ex = ask(client, '"छुट्टी" कितनी बार आया है')
    assert ex["route"] == "exact" and ex["details"]["count"] == 1
    sem = ask(client, "कर्मचारियों को कितनी छुट्टी मिलती है")
    assert sem["route"] in ("semantic", "exact") and "छुट्टी" in sem["answer"] and sem["citations"]
    assert ask(client, "इस दस्तावेज़ का सारांश दें")["route"] == "summarize"
    assert sem["language"] == "hi"


def test_hindi_answer_language_is_requested_from_the_model(tmp_path):
    seen = []
    c, k = app_with(tmp_path, llm=FakeLLM(lambda sy, u: seen.append(sy) or ("कर्मचारियों को पच्चीस दिन की छुट्टी मिलती है [1]." if "Answer the question" in sy else None)))
    upload(c, "नीति.txt", HINDI_A.encode())
    r = ask(c, "कर्मचारियों को कितनी छुट्टी मिलती है?")
    assert any("Answer in Hindi" in s for s in seen) and "छुट्टी" in r["answer"]


def test_hindi_table_questions(client):
    df = pd.DataFrame({"कर्मचारी": ["अमित", "बीना", "चेतन"], "बिक्री": [1200, 3400, 900]})
    upload(client, "bikri.csv", df.to_csv(index=False).encode())
    r = ask(client, "बिक्री का कुल योग क्या है?")
    assert r["route"] == "data" and r["details"]["result"]["value"] == 5500
    r = ask(client, "सबसे अधिक बिक्री किस कर्मचारी की है?")
    assert r["route"] == "data" and r["details"]["result"]["value"] == 3400 and "बीना" in r["answer"]
    assert ask(client, "बिक्री का औसत क्या है?")["details"]["result"]["value"] == pytest.approx(5500 / 3)


def test_hindi_negation_contradiction_and_compare_route(client):
    upload(client, "a.txt", "कर्मचारियों को घर से काम करने की अनुमति है सप्ताह में तीन दिन".encode())
    upload(client, "b.txt", "कर्मचारियों को घर से काम करने की अनुमति नहीं है सप्ताह में तीन दिन".encode())
    r = ask(client, "a.txt और b.txt की तुलना करें")
    assert r["route"] == "compare"
