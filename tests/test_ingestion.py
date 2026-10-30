import json

from .conftest import SALES_ROWS, make_docx, make_pdf, make_xlsx, upload


def test_pdf_pages_and_metadata(client):
    r = upload(client, "contract.pdf", make_pdf(["Intro page about nothing", "Clause 8 covers termination rights", "Closing words"]))
    assert r["status"] == "ready"
    assert r["source"]["pages"] == 3 and r["source"]["chunks"] >= 3
    assert client.get("/sources", headers={"X-Session-ID": "s1"}).json()[0]["name"] == "contract.pdf"


def test_all_formats_ingest(client):
    files = {
        "a.txt": b"First paragraph.\n\nSecond paragraph about budgets.",
        "b.md": b"# Title\n\nSome text\n\n## Details\n\nMore text here",
        "c.csv": b"name,amount\nx,1\ny,2\n",
        "d.json": json.dumps({"users": [{"name": "Zed", "age": 3}]}).encode(),
        "e.xlsx": make_xlsx({"Sheet1": SALES_ROWS}),
        "f.docx": make_docx(["Hello docx world"], [["k", "v"], ["a", "b"]]),
    }
    for n, d in files.items():
        r = upload(client, n, d)
        assert r["status"] == "ready", (n, r)
    assert len(client.get("/sources", headers={"X-Session-ID": "s1"}).json()) == 6


def test_errors_are_clear(client):
    assert "Unsupported" in upload(client, "x.exe", b"MZ")["error"]
    assert "not a PDF" in upload(client, "bad.pdf", b"not a pdf")["error"]
    assert "Could not read PDF" in upload(client, "trunc.pdf", b"%PDF-1.4\n1 0 obj\n<< /Broken")["error"]
    assert "empty" in upload(client, "e.txt", b"")["error"].lower()
    assert "Invalid JSON" in upload(client, "bad.json", b"{oops")["error"]
    assert upload(client, "blank.pdf", make_pdf([""]))["status"] == "failed"
    assert "does not match its extension" in upload(client, "bad.xlsx", b"junk")["error"]
    # failed ingestions leave nothing behind
    assert client.get("/sources", headers={"X-Session-ID": "s1"}).json() == []


def test_size_limit(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.api import create_app

    s = settings.model_copy(update={"max_upload_mb": 1})
    c = TestClient(create_app(s))
    r = upload(c, "big.txt", b"a" * (2 * 1024 * 1024))
    assert r["status"] == "failed" and "limit" in r["error"]


def test_delete_and_reindex(client):
    r = upload(client, "a.txt", b"alpha beta gamma delta")
    sid = r["source"]["id"]
    h = {"X-Session-ID": "s1"}
    assert client.post(f"/sources/{sid}/reindex", headers=h).json()["status"] == "ready"
    assert len(client.get("/sources", headers=h).json()) == 1
    assert client.delete(f"/sources/{sid}", headers=h).status_code == 200
    assert client.get(f"/sources/{sid}", headers=h).status_code == 404
    assert client.delete(f"/sources/{sid}", headers=h).status_code == 404
    assert client.post("/ask", json={"question": "alpha"}, headers=h).json()["verified"] is False
