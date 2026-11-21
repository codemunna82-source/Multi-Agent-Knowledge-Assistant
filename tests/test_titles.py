import pytest
from fastapi.testclient import TestClient

from app.agents.titles import MAX, make_title
from app.api import create_app
from app.config import Settings
from app.service import Knowledge

H = {"X-Session-ID": "s1"}


@pytest.mark.parametrize("q,title", [
    ("hi, can you please tell me how many days of annual leave employees get?", "How many days of annual leave employees get"),
    ("What is the parental leave policy?", "What is the parental leave policy"),
    ("tell me about the termination clause", "The termination clause"),
    ("Please summarize the contract", "Summarize the contract"),
    ("hi", "Greeting"), ("thanks!", "Thanks"), ("what can you do", "What can you do?"), ("who are you", "About the assistant"),
    ("", "New conversation"), ("   ", "New conversation"),
    ("Compare policy_v1.pdf and policy_v2.pdf", "Compare policy_v1.pdf and policy_v2.pdf"),
    ("छुट्टी की नीति क्या है?", "छुट्टी की नीति क्या है"),
])
def test_titles(q, title):
    assert make_title(q) == title


def test_long_questions_are_cut_at_a_word_boundary():
    t = make_title("Explain in detail how the quarterly revenue figures differ between the regional sales spreadsheets for every country")
    assert len(t) <= MAX + 1 and t.endswith("…") and " " not in t[-2:] and t.startswith("Explain in detail how the quarterly")
    assert make_title("x" * 200).endswith("…") and len(make_title("x" * 200)) == MAX + 1


def test_a_new_conversation_gets_the_clean_title(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s)))
    cid = c.post("/ask", json={"question": "hi, can you tell me what the policy says about leave?"}, headers=H).json()["conversation_id"]
    items = c.get("/conversations", headers=H).json()
    items = items["items"] if isinstance(items, dict) else items
    assert [x["title"] for x in items if x["id"] == cid] == ["What the policy says about leave"]
