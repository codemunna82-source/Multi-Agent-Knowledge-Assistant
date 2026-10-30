"""A real 1,000-page PDF through the whole stack (background job, progress, exact search over every page, semantic search, tables, preview, delete)."""
import io
import json
import random
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

H = {"X-Session-ID": "big"}
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu "
         "budget policy review contract invoice payment report status schedule vendor customer region quarter forecast audit risk control process asset ledger tax account").split()
NAME = "Anjali"
PAGES = 1000


def build_pdf(pages: int = PAGES):
    """-> (pdf bytes, expected facts). Deterministic; the name 'Anjali' is planted on known pages, 'Anjalika' (a different word) as a decoy."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle

    plant: dict[int, int] = {p: 1 for p in range(37, pages + 1, 37)}  # 27 pages with one occurrence each
    plant[500], plant[501] = 3, 2  # pages with several occurrences
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for p in range(1, pages + 1):
        rng = random.Random(p)
        lines = [" ".join(rng.choice(WORDS) for _ in range(12)) for _ in range(34 if p != 250 else 20)]  # page 250 leaves room for the table
        for k in range(plant.get(p, 0)):
            lines[3 + 5 * k] += f" {NAME} approved item {p}.{k}"
        if p == 10:
            lines[7] += " Anjalika is a different person"
        if p == 777:
            lines[20] += " The unique launch codename is ZXQ-4821 and the board approved a budget of nine hundred thousand."
        c.setFont("Helvetica", 9)
        for i, ln in enumerate(lines):
            c.drawString(40, 800 - i * 22, ln)
        if p == 250:
            t = Table([["Item", "Qty", "Price"], ["Pen", "10", "5"], ["Book", "2", "40"]])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
            t.wrapOn(c, 300, 100)
            t.drawOn(c, 350, 40)
        c.showPage()
    c.save()
    return buf.getvalue(), {"count": sum(plant.values()), "pages": sorted(plant)}


@pytest.fixture(scope="module")
def big():
    t0 = time.perf_counter()
    data, facts = build_pdf()
    facts["generate_s"] = round(time.perf_counter() - t0, 1)
    return data, facts


def test_thousand_page_pdf_end_to_end(tmp_path, big):
    data, facts = big
    assert len(data) > 1_000_000
    s = Settings(data_dir=str(tmp_path / "d"), max_pdf_pages=5000, _env_file=None)
    c = TestClient(create_app(s))
    perf: dict = {"pdf_mb": round(len(data) / 1e6, 2), "pages": PAGES}

    # ---- upload as a background job and watch progress
    t0 = time.perf_counter()
    jid = c.post("/sources/upload?async=true", files=[("files", ("annual_report.pdf", data))], headers=H).json()[0]["job_id"]
    seen, job = [], {}
    while time.perf_counter() - t0 < 300:
        job = c.get(f"/jobs/{jid}", headers=H).json()
        seen.append((job["stage"], job["progress"]))
        if job["status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    perf["ingest_s"] = round(time.perf_counter() - t0, 1)
    assert job["status"] == "ready", job
    assert {st for st, _ in seen} >= {"extracting", "embedding"} and sorted(p for _, p in seen) == [p for _, p in seen]  # progress was visible and monotonic
    src = c.get("/sources", headers=H).json()[0]
    assert src["pages"] == PAGES and src["engine"] == "pymupdf" and src["chunks"] >= PAGES

    # ---- exact search across ALL pages: count, pages, excerpts (not a vector top-K)
    lat = []
    t0 = time.perf_counter()
    r = c.post("/ask", json={"question": f"Does {NAME} appear in this PDF?"}, headers=H).json()
    lat.append((time.perf_counter() - t0) * 1000)
    assert r["route"] == "exact" and r["details"]["count"] == facts["count"] == 32  # 27 pages x1 + page 500 x3 + page 501 x2
    assert r["details"]["pages"]["annual_report.pdf"] == facts["pages"] and r["details"]["locations_with_match"] == len(facts["pages"]) == 29
    assert not any(m["location"] == "page 10" for m in r["citations"])  # the decoy 'Anjalika' is not the name we searched for
    assert r["details"]["sources_searched"] == 1 and r["verified"]
    # counts are complete even though the citation list is capped
    for term, n, page in ((f'"{NAME}"', 32, None), ('"ZXQ-4821"', 1, 777)):
        t0 = time.perf_counter()
        a = c.post("/ask", json={"question": f"How many times does {term} appear?"}, headers=H).json()
        lat.append((time.perf_counter() - t0) * 1000)
        assert a["details"]["count"] == n
        if page:
            assert a["citations"][0]["location"] == f"page {page}" and a["details"]["pages"]["annual_report.pdf"] == [page]
    # whole-word rule: the decoy 'Anjalika' is not a match, but substring mode finds it
    sub = c.post("/ask", json={"question": f'How many times does "{NAME}" appear?', "whole_word": False}, headers=H).json()
    assert sub["details"]["count"] == 33  # + the decoy

    # ---- semantic question locates the single relevant page
    t0 = time.perf_counter()
    q = c.post("/ask", json={"question": "What did the board approve for the launch codename?"}, headers=H).json()
    lat.append((time.perf_counter() - t0) * 1000)
    assert q["verified"] and q["citations"][0]["location"] == "page 777" and "nine hundred thousand" in q["answer"]

    # ---- table on page 250, page preview, passage
    tabs = c.get(f"/sources/{src['id']}/tables", headers=H).json()
    assert any(t["location"]["page"] == 250 and t["header"] == ["Item", "Qty", "Price"] for t in tabs)
    img = c.get(f"/sources/{src['id']}/pages/777/image?highlight=ZXQ-4821", headers=H)
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert "ZXQ-4821" in c.get(f"/sources/{src['id']}/passage?page=777", headers=H).json()["text"]
    perf.update(exact_search_ms=[round(x) for x in lat], max_query_ms=round(max(lat)))
    assert max(lat) < 5000, f"queries too slow on a 1,000-page document: {lat}"

    # ---- delete removes text, chunks and vectors
    assert c.delete(f"/sources/{src['id']}", headers=H).status_code == 200
    assert not list((tmp_path / "d" / "tenants").rglob("vectors.npy")) and not list((tmp_path / "d" / "tenants").rglob("units.jsonl"))
    gone = c.post("/ask", json={"question": f'find "{NAME}"'}, headers=H).json()
    assert gone["details"].get("count", 0) == 0 and not gone["citations"]
    print("\nPERF 1000-page PDF:", json.dumps(perf))
    assert perf["ingest_s"] < 240
