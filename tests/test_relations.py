import pytest

from app.intel.entities import chunk_relations

from .conftest import upload

H = {"X-Session-ID": "s1"}


@pytest.mark.parametrize("text,expect", [
    ("Priya Nair reports to Anjali Rao every Monday.", [("Priya Nair", "reports_to", "Anjali Rao")]),
    ("The Q3 budget was approved by Anjali Rao.", []),                                   # 'Q3 budget' is not an entity: no relation invented
    ("Ravi Kumar works at Acme Corp.", [("Ravi Kumar", "works_for", "Acme Corp")]),
    ("Globex Corp was acquired by Acme Corp.", [("Acme Corp", "acquired", "Globex Corp")]),
    ("Meera Shah was approved by Anjali Rao.", [("Anjali Rao", "approved", "Meera Shah")]),
    ("Anjali Rao manages Priya Nair.", [("Anjali Rao", "manages", "Priya Nair")]),
    ("Anjali Rao met Priya Nair yesterday.", []),                                        # a plain co-mention stays untyped
    ("Anjali Rao thanked the team. Priya Nair left.", []),                               # different sentences never relate
    ("Anjali Rao, who reports to Sunil Verma, approved it.", [("Anjali Rao", "reports_to", "Sunil Verma")]),
])
def test_chunk_relations_patterns(text, expect):
    got = [(s, r, o) for _, s, r, _, o in chunk_relations(text)]
    assert got == expect


def test_relation_requires_close_neighbours():
    far = "Priya Nair " + "x " * 40 + "reports to Anjali Rao."
    assert chunk_relations(far) == []


def test_graph_endpoint_and_answer_name_the_relation_with_a_citation(client):
    upload(client, "org.txt", b"Priya Nair reports to Anjali Rao. Ravi Kumar works at Acme Corp. Anjali Rao met Ravi Kumar at Acme Corp.\n")
    g = client.get("/graph", params={"entity": "Priya Nair"}, headers=H).json()
    assert {"subject": "Priya Nair", "relation": "reports_to", "object": "Anjali Rao", "evidence": 1} in g["relations"]
    r = client.post("/ask", json={"question": "How are Priya Nair and Anjali Rao connected?"}, headers=H).json()
    assert "Priya Nair reports to Anjali Rao" in r["answer"] and r["citations"] and r["citations"][0]["source"] == "org.txt"
    assert any("co-mentions" in x for x in r["limitations"])
