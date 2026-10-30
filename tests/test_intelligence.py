
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.intel.entities import entities_in
from app.intel.language import detect_language
from app.service import Knowledge

from .conftest import ask, make_docx, make_xlsx, upload
from .fakes import FakeLLM

H = {"X-Session-ID": "s1"}

TEXT = ("Anjali Rao of Acme Corp emailed anjali@acme.io on 12 March 2024 about invoice INV-2024-0042 for $1,200.50 (15% discount). "
        "Call +91 98765 43210. See https://acme.io/terms")


def test_entity_heuristics():
    got = {(t, v) for t, v in entities_in(TEXT)}
    assert {("NAME", "Anjali Rao"), ("ORG", "Acme Corp"), ("EMAIL", "anjali@acme.io"), ("DATE", "12 March 2024"), ("ID", "INV-2024-0042"), ("MONEY", "$1,200.50"),
            ("PERCENT", "15%"), ("URL", "https://acme.io/terms")} <= got
    assert any(t == "PHONE" and "98765" in v for t, v in got)
    assert not any(v in ("The", "See") for _, v in got)
    assert ("NAME", "March") not in got and not [e for e in entities_in("Monday Tuesday January Friday") if e[0] == "NAME"]


def test_entities_endpoint_and_agent(client):
    sid = upload(client, "memo.txt", (TEXT + "\n\nAnjali Rao approved it.\n\nAnjali Rao also met Bob Mehta of Acme Corp.").encode())["source"]["id"]
    r = client.get(f"/sources/{sid}/entities", headers=H).json()
    names = {e["value"]: e["count"] for e in r["entities"]["NAME"]}
    assert names["Anjali Rao"] == 3 and names["Bob Mehta"] == 1 and r["method"] == "heuristic"
    a = ask(client, "Extract all the entities from memo.txt")
    assert a["route"] == "summarize" and "Anjali Rao ×3" in a["answer"] and a["limitations"] and "heuristic" in a["limitations"][0]
    assert client.get(f"/sources/{sid}/entities?types=email", headers=H).json()["entities"].keys() == {"EMAIL"}


def test_llm_entities_must_appear_verbatim(tmp_path):
    llm = FakeLLM(lambda sy, u: '{"entities": [{"type": "PERSON", "value": "Anjali Rao"}, {"type": "PERSON", "value": "Elon Musk"}, {"type": "ORG", "value": "अकमे कंपनी"}]}' if "Extract named" in sy else None)
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, llm=llm)))
    sid = upload(c, "m.txt", "Anjali Rao met अकमे कंपनी partners. Anjali Rao left.".encode())["source"]["id"]
    r = c.get(f"/sources/{sid}/entities", headers=H).json()
    vals = {e["value"] for ents in r["entities"].values() for e in ents}
    assert "अकमे कंपनी" in vals and "Elon Musk" not in vals  # hallucinated entity rejected, non-Latin entity accepted
    assert next(e for e in r["entities"]["ORG"] if e["value"] == "अकमे कंपनी")["count"] == 1 and r["method"].startswith("heuristic+llm")


def test_question_generation(tmp_path):
    c = TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), _env_file=None)))
    md = b"# Refund policy\n\nRefunds are issued by Priya Natarajan within 14 days.\n\n# Shipping\n\nShipping costs $5.00 on orders."
    sid = upload(c, "policy.md", md)["source"]["id"]
    q = c.get(f"/sources/{sid}/questions", headers=H).json()
    assert q["method"] == "template" and "What does the document say about Refund policy?" in q["questions"] and any("Priya Natarajan" in x for x in q["questions"])
    assert all(x.endswith("?") for x in q["questions"])
    sx = upload(c, "t.xlsx", make_xlsx({"S": [["a", "b"], [1, 2]]}))["source"]["id"]
    assert any("duplicate" in x for x in c.get(f"/sources/{sx}/questions", headers=H).json()["questions"])
    r = ask(c, "Generate questions about policy.md")
    assert r["route"] == "summarize" and "1." in r["answer"] and r["details"]["questions"]["policy.md"]["questions"]
    llm = FakeLLM(lambda sy, u: '{"questions": ["How long do refunds take?", "bad question without mark", "Who issues refunds?"]}' if "diverse questions" in sy else None)
    s = Settings(data_dir=str(tmp_path / "e"), _env_file=None)
    c2 = TestClient(create_app(s, Knowledge(s, llm=llm)))
    sid = upload(c2, "policy.md", md)["source"]["id"]
    q = c2.get(f"/sources/{sid}/questions", headers=H).json()
    assert q["method"] == "llm" and q["questions"] == ["How long do refunds take?", "Who issues refunds?"]


def test_table_extraction_agent(client):
    upload(client, "t.docx", make_docx(["intro"], [["Item", "Qty"], ["Pen", "10"], ["Ink", "3"]]))
    r = ask(client, "Extract the tables from t.docx")
    assert r["route"] == "summarize" and "| Item | Qty |" in r["answer"] and "| Pen | 10 |" in r["answer"] and r["citations"][0]["location"] == "table 1"
    upload(client, "plain.txt", b"just text")
    assert "No tables" in ask(client, "extract tables from plain.txt")["answer"]


def test_language_detection():
    assert detect_language("The quick brown fox jumps over the lazy dog and the cat") == "en"
    assert detect_language("El gato se sienta en la casa y no quiere salir de ella") == "es"
    assert detect_language("कर्मचारियों को हर साल छुट्टी मिलती है") == "hi"
    assert detect_language("Le chat est dans la maison et il ne veut pas sortir") == "fr"
    assert detect_language("Der Hund ist nicht im Haus und die Katze auch nicht") == "de"
    assert detect_language("今日は天気がいいですね") in ("ja", "zh")
    assert detect_language("12345 !!!") == "en"


def test_language_tag_and_cross_lingual_retrieval(tmp_path):
    def script(sy, u):
        if "Translate the search query" in sy:
            return '{"translations": ["vacation days per year"]}'
        return None

    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, llm=FakeLLM(script))))
    src = upload(c, "en.txt", b"Employees receive twenty five vacation days per year.")["source"]
    meta = c.app.state.knowledge.store(__import__("app.storage", fromlist=["Scope"]).Scope("default", "s1")).get_source(src["id"])
    assert meta["language"] == "en"
    # Spanish question, English document: only the translated variant matches lexically
    r = ask(c, "¿Cuántos días de vacaciones hay por año?", retrieval={"mode": "keyword", "corrective": False})
    assert r["verified"] and r["citations"][0]["source"] == "en.txt"
    assert any(t.startswith("semantic") for t in r["details"]["trace"])
    r2 = TestClient(create_app(Settings(data_dir=str(tmp_path / "x"), _env_file=None)))
    upload(r2, "en.txt", b"Employees receive twenty five vacation days per year.")
    assert not ask(r2, "¿Cuántos días de vacaciones hay por año?", retrieval={"mode": "keyword", "corrective": False})["verified"]  # no LLM -> no translation


def test_multilingual_answering_prompt_language(tmp_path):
    seen = {}

    def script(sy, u):
        if "Answer the question" in sy:
            seen["sy"] = sy
            return "Los empleados reciben 25 días [1]."
        return None

    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, llm=FakeLLM(script))))
    upload(c, "es.txt", "Los empleados reciben 25 días de vacaciones al año.".encode())
    r = ask(c, "¿Cuántos días de vacaciones reciben los empleados al año?")
    assert "Answer in Spanish" in seen["sy"] and r["language"] == "es" and r["verified"]


# ------------------------------------------------------------------------------------ knowledge graph / Graph RAG
GRAPH_DOCS = {
    "a.txt": "Anjali Rao leads the Mumbai office together with Bob Mehta.\n\nBob Mehta reports to Carol Singh at Acme Corp.",
    "b.txt": "Carol Singh signed the contract with Delta Systems.\n\nDelta Systems was founded by Dev Patel.",
    "c.txt": "Unrelated gardening notes by Zed Zimmer about tulips.",
}


@pytest.fixture
def gclient(client):
    for n, t in GRAPH_DOCS.items():
        upload(client, n, t.encode())
    return client


def test_graph_neighbors_path_and_overview(gclient):
    r = ask(gclient, "Who is Bob Mehta connected to?")
    assert r["route"] == "summarize" and "Anjali Rao" in r["answer"] and "Carol Singh" in r["answer"]
    assert r["verified"] and all(c["source"] == "a.txt" for c in r["citations"])
    r = ask(gclient, "How is Anjali Rao related to Dev Patel?")
    assert r["details"]["graph"]["path"] == ["Anjali Rao", "Bob Mehta", "Carol Singh", "Delta Systems", "Dev Patel"] and r["details"]["graph"]["hops"] == 4
    assert {c["source"] for c in r["citations"]} == {"a.txt", "b.txt"}
    r = ask(gclient, "How is Anjali Rao related to Zed Zimmer?")
    assert "No connection" in r["answer"] and r["verified"]
    r = ask(gclient, "Show the knowledge graph overview")
    assert "Most connected" in r["answer"]
    g = gclient.get("/graph?entity=Carol Singh", headers=H).json()
    assert {n["name"] for n in g["neighbors"]} >= {"Bob Mehta", "Delta Systems", "Acme Corp"}
    assert gclient.get("/graph?entity=Anjali Rao&to=Dev Patel", headers=H).json()["path"][-1] == "Dev Patel"
    assert gclient.get("/graph?entity=Nobody Known", headers=H).status_code == 404


def test_graph_rag_expansion_finds_linked_chunk(gclient):
    q = "Tell me about Carol Singh"
    base = ask(gclient, q, retrieval={"mode": "semantic", "graph": False, "corrective": False, "top_k": 10})
    g = ask(gclient, q, retrieval={"mode": "semantic", "graph": True, "corrective": False, "top_k": 10})
    assert any("graph-expand" == t["step"] for t in g["details"]["retrieval"]["trace"])
    assert {c["source"] for c in g["citations"]} >= {"a.txt", "b.txt"}


def test_graph_never_leaks_private_documents(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="g" * 40, rate_limit_ingest="1000/minute", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    adm = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Tenant", "email": "a@a.io", "password": "long enough pw"}).json()["access_token"]}
    c.post("/admin/users", json={"email": "v@a.io", "password": "long enough pw", "role": "editor"}, headers=adm)
    ed = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "v@a.io", "password": "long enough pw"}).json()["access_token"]}
    c.post("/sources/upload", files=[("files", ("secret.txt", b"Priya Natarajan secretly meets Rahul Verma about layoffs."))], data={"visibility": "private"}, headers={**adm, **H})
    c.post("/sources/upload", files=[("files", ("public.txt", b"Meera Joshi works with Sam Brown on the roadmap."))], headers={**adm, **H})
    assert "Priya" not in str(c.get("/graph", headers={**ed, **H}).json())
    assert c.get("/graph?entity=Priya Natarajan", headers={**ed, **H}).status_code == 404
    assert c.get("/graph?entity=Priya Natarajan", headers={**adm, **H}).status_code == 200
    r = c.post("/ask", json={"question": "Who is Priya Natarajan connected to?"}, headers={**ed, **H}).json()
    assert "Rahul" not in str(r) and "layoffs" not in str(r)


# ------------------------------------------------------------------------------------ multimodal / voice
def test_transcribe_endpoint_requires_provider_and_validates(client, monkeypatch):
    r = client.post("/transcribe", files={"audio": ("a.webm", b"123", "audio/webm")}, headers=H)
    assert r.status_code == 501
    s = Settings(data_dir=str(client.app.state.svc.settings.data_dir) + "x", llm_provider="openai", openai_api_key="sk-test", _env_file=None)
    c = TestClient(create_app(s))
    assert c.post("/transcribe", files={"audio": ("a.txt", b"123", "text/plain")}, headers=H).status_code == 415
    assert c.post("/transcribe", files={"audio": ("a.webm", b"", "audio/webm")}, headers=H).status_code == 422
    import app.providers as prov

    class R:
        status_code = 200
        def json(self): return {"text": " what is the refund window "}

    seen = {}
    monkeypatch.setattr(prov.httpx, "post", lambda url, **kw: seen.update(url=url, kw=kw) or R())
    r = c.post("/transcribe", files={"audio": ("a.webm", b"RIFFxxxx", "audio/webm")}, headers=H)
    assert r.json() == {"text": "what is the refund window"} and "audio/transcriptions" in seen["url"] and seen["kw"]["data"]["model"] == "whisper-1"
