"""Greetings and thanks get a normal reply and never touch the documents; real questions (even ones that start with 'hi') still do."""
import json

import pytest
from fastapi.testclient import TestClient

from app.agents import smalltalk
from app.api import create_app
from app.config import Settings
from app.service import Knowledge

from .conftest import upload

H = {"X-Session-ID": "s1"}
DOC = b"Employees accrue 25 days of annual leave per year. " * 3


@pytest.mark.parametrize("text,kind", [
    ("hi", "greeting"), ("Hi!", "greeting"), ("hello", "greeting"), ("heyyy", "greeting"), ("hii there", "greeting"), ("Hello bot", "greeting"), ("namaste", "greeting"), ("नमस्ते", "greeting"),
    ("good morning", "greeting"), ("Good evening!", "greeting"), ("how are you", "how_are_you"), ("hi how are you?", "how_are_you"), ("kaise ho", "how_are_you"), ("hello kaise ho", "how_are_you"),
    ("thanks", "thanks"), ("thank you so much", "thanks"), ("shukriya", "thanks"), ("dhanyavad", "thanks"), ("धन्यवाद", "thanks"), ("bye", "bye"), ("ok bye", "bye"),
    ("who are you", "identity"), ("what can you do", "capabilities"), ("help", "capabilities"), ("tum kya kar sakte ho", "capabilities"), ("ok", "ack"), ("theek hai", "ack"),
])
def test_small_talk_is_recognised(text, kind):
    assert smalltalk.detect(text) == kind


@pytest.mark.parametrize("text", [
    "hi, how many days of annual leave do employees get?", "What is the leave policy?", "thanks for the summary, now compare the two documents", "how are the sales figures this quarter",
    "help me find the clause about termination", "hello world program in python", "ok so what is the total revenue", "who are the signatories of the contract", "", "?!", "सारांश बताओ",
])
def test_real_questions_are_not_small_talk(text):
    assert smalltalk.detect(text) is None


def test_reply_language_follows_the_message_and_states_document_count():
    assert "Hello" in smalltalk.reply("greeting", "hi", 2)["answer"] and "2 documents" in smalltalk.reply("greeting", "hi", 2)["answer"]
    assert "1 document indexed" in smalltalk.reply("greeting", "hi", 1)["answer"]
    assert "Upload a file" in smalltalk.reply("greeting", "hi", 0)["answer"]
    h = smalltalk.reply("greeting", "namaste", 3)
    assert h["answer"].startswith("Namaste") and "3 documents hain" in h["answer"] and h["language"] == "en"
    d = smalltalk.reply("thanks", "धन्यवाद", 0)
    assert "कोई बात नहीं" in d["answer"] and d["language"] == "hi"


def make(tmp_path, docs=True):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    k = Knowledge(s)
    c = TestClient(create_app(s, k))
    if docs:
        upload(c, "a.txt", DOC)
    return c, k


def ask(c, q):
    r = c.post("/ask", json={"question": q}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_hi_gets_a_normal_reply_without_searching_documents(tmp_path):
    c, k = make(tmp_path)
    j = ask(c, "hi")
    assert j["route"] == "chat" and j["verified"] is True and j["citations"] == [] and j["limitations"] == [] and j["followups"] == []
    assert "could not verify" not in j["answer"].lower() and "1 document" in j["answer"]
    assert any("no documents searched" in t for t in j["details"]["trace"])


def test_hi_works_with_no_documents_too(tmp_path):
    c, k = make(tmp_path, docs=False)
    j = ask(c, "hello")
    assert j["route"] == "chat" and "No documents are indexed yet" in j["answer"]


def test_real_question_starting_with_hi_still_uses_the_documents(tmp_path):
    c, k = make(tmp_path)
    j = ask(c, "hi, how many days of annual leave do employees get?")
    assert j["route"] != "chat" and j["citations"] and "25" in j["answer"]


def test_stream_for_small_talk_has_no_retrieval_stages(tmp_path):
    c, k = make(tmp_path)
    ev, cur = [], None
    with c.stream("POST", "/ask/stream", json={"question": "thanks!"}, headers=H) as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev.append((cur, json.loads(line.split(":", 1)[1])))
    stages = [e[1]["stage"] for e in ev if e[0] == "status"]
    assert not {"retrieve", "grade", "rerank", "verify", "generate"} & set(stages)
    fin = [e for e in ev if e[0] == "final"][0][1]["response"]
    assert fin["route"] == "chat" and "welcome" in fin["answer"].lower() and ev[-1][0] == "done"


def test_a_client_chosen_route_is_never_overridden_by_small_talk(tmp_path):
    c, k = make(tmp_path)
    r = c.post("/ask", json={"question": "hi", "force_route": "semantic"}, headers=H)
    assert r.status_code == 200 and r.json()["route"] != "chat"
