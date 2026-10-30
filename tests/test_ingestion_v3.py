"""Phase P2: PyMuPDF engine, headings, tables, XLS, HTML, encodings, classification, timeline, previews, progress, corrupt files."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import create_app
from app.config import Settings
from app.service import Knowledge
from app.storage import Scope

from .conftest import make_docx, make_pdf, make_xlsx
from .fakes import FakeLLM

H = {"X-Session-ID": "s1"}


@pytest.fixture
def client2(tmp_path):
    return TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), _env_file=None)))


def up(c, name, data, **form):
    r = c.post("/sources/upload", files=[("files", (name, data))], data=form, headers=H)
    assert r.status_code == 200, r.text
    return r.json()[0]


def ask(c, q, **kw):
    r = c.post("/ask", json={"question": q, **kw}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def meta_of(c, sid):
    return c.app.state.knowledge.store(Scope("default", "s1")).get_source(sid)


# ----------------------------------------------------------------------------------------------- PDF engine
def test_pymupdf_is_the_default_engine_and_pypdf_the_fallback(tmp_path):
    data = make_pdf(["Alpha page one about leave.", "Beta page two about expenses."])
    for engine, expect in (("auto", "pymupdf"), ("pypdf", "pypdf")):
        c = TestClient(create_app(Settings(data_dir=str(tmp_path / engine), pdf_engine=engine, _env_file=None)))
        sid = up(c, "x.pdf", data)["source"]["id"]
        assert meta_of(c, sid)["engine"] == expect
        assert ask(c, 'find "expenses"')["citations"][0]["location"] == "page 2"


def test_text_past_the_page_edge_is_not_lost(client2):
    long_line = " ".join(f"word{i}" for i in range(250))  # one 1,700-character line drawn on an A4 page runs far past the edge
    up(client2, "wide.pdf", make_pdf([long_line + " ENDMARKER"]))
    assert ask(client2, 'find "ENDMARKER"')["details"]["count"] == 1  # MuPDF drops such glyphs unless the clip is lifted


def test_headings_detected_from_font_size_without_bookmarks(client2):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for title, body in (("Termination Rights", "Either party may leave the contract with notice."), ("Payment Schedule", "Invoices fall due within forty five days.")):
        c.setFont("Helvetica-Bold", 22)
        c.drawString(50, 780, title)
        c.setFont("Helvetica", 11)
        for k in range(8):
            c.drawString(50, 740 - 16 * k, body + f" Filler line number {k} with ordinary body text to establish the base size.")
        c.showPage()
    c.save()
    up(client2, "c.pdf", buf.getvalue())
    assert ask(client2, 'find "forty five"')["citations"][0]["location"] == "page 2 (section: Payment Schedule)"


def test_pdf_properties_and_ruled_table(client2):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    t = Table([["Item", "Qty", "Price"], ["Pen", "10", "5"], ["Book", "2", "40"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4, title="Price list", author="Acme Procurement").build([t])
    src = up(client2, "prices.pdf", buf.getvalue())["source"]
    assert src["title"] == "Price list" and src["properties"]["author"] == "Acme Procurement" and src["engine"] == "pymupdf"
    tabs = client2.get(f"/sources/{src['id']}/tables", headers=H).json()
    assert tabs[0]["header"] == ["Item", "Qty", "Price"] and tabs[0]["rows"][1] == ["Book", "2", "40"] and tabs[0]["location"] == {"page": 1, "table": 1}


# ----------------------------------------------------------------------------------------------- XLS / HTML / encodings
def make_xls(sheets: dict) -> bytes:
    import xlwt

    wb = xlwt.Workbook()
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    import datetime

    for name, rows in sheets.items():
        ws = wb.add_sheet(name)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                ws.write(r, c, v, date_style) if isinstance(v, datetime.date) else ws.write(r, c, v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_legacy_xls_ingest_and_analysis(client2):
    import datetime

    rows = [["Employee", "Region", "Sales", "Date"], ["Alice", "North", 1200, datetime.date(2024, 1, 5)], ["Bob", "South", 3400.5, datetime.date(2024, 2, 9)], ["Carol", "North", 900, datetime.date(2024, 3, 1)]]
    r = up(client2, "legacy.xls", make_xls({"Q1": rows}))
    assert r["status"] == "ready" and r["source"]["tabular"] and r["source"]["kind"] == "xls"
    a = ask(client2, "Which employee has the highest sales?")
    assert a["route"] == "data" and "Bob" in a["answer"] and a["citations"][0]["location"] == "sheet 'Q1', row 3"
    assert ask(client2, 'find "2024-02-09"')["details"]["count"] == 1  # dates are rendered as ISO text
    assert client2.get(f"/sources/{r['source']['id']}/tables", headers=H).json()[0]["header"] == ["Employee", "Region", "Sales", "Date"]
    assert "not a legacy Excel" in up(client2, "fake.xls", make_xlsx({"S": [["a"], [1]]}))["error"]
    assert up(client2, "broken.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1garbage")["status"] == "failed"


def test_html_file_ingest(client2):
    html = ("<html><head><title>Quarterly update</title><style>.x{color:red}</style><script>alert('x')</script></head><body><nav>menu</nav>"
            "<h1>Results</h1><p>Revenue grew 12 percent in the north.</p><h2>Outlook</h2><p>We expect steady demand.</p>"
            "<table><tr><th>Region</th><th>Growth</th></tr><tr><td>North</td><td>12</td></tr><tr><td>South</td><td>4</td></tr></table></body></html>").encode("cp1252")
    r = up(client2, "update.html", html)
    assert r["status"] == "ready" and r["source"]["title"] == "Quarterly update"
    a = ask(client2, 'find "steady demand"')
    assert a["citations"][0]["location"].startswith("paragraph") and "section: Outlook" in a["citations"][0]["location"]
    assert ask(client2, 'find "alert"')["details"]["count"] == 0 and ask(client2, 'find "menu"')["details"]["count"] == 0
    assert client2.get(f"/sources/{r['source']['id']}/tables", headers=H).json()[0]["rows"] == [["North", "12"], ["South", "4"]]
    assert up(client2, "plain.html", b"no markup at all, just text")["status"] == "failed"


@pytest.mark.parametrize("name,payload,needle", [
    ("cp1252.txt", "Café société – naïve résumé".encode("cp1252"), "café"),
    ("gbk.txt", "这是一个关于合同终止的文档".encode("gbk"), "合同"),
    ("utf16.txt", "Ünïcode in UTF-16 with BOM".encode("utf-16"), "ünïcode"),
    ("sjis.txt", "契約の終了に関する通知書です".encode("shift_jis"), "契約"),
    ("bom8.csv", "﻿name,city\nZoë,Zürich\n".encode(), "zürich"),
])
def test_encodings_are_decoded_not_rejected(client2, name, payload, needle):
    r = up(client2, name, payload)
    assert r["status"] == "ready", r
    assert ask(client2, f'find "{needle}"', retrieval={"corrective": False})["details"]["count"] >= 1


def test_mojibake_garbage_does_not_crash(client2):
    r = up(client2, "weird.txt", bytes(range(32, 127)) * 3 + b"\xff\xfe\xfd valid tail words")
    assert r["status"] in ("ready", "failed")  # must be a clean result either way


# ----------------------------------------------------------------------------------------------- classification
def test_classification(client2):
    contract = b"This Agreement is made between the parties. The termination clause and governing law apply. Whereas the confidentiality obligations and liability are agreed."
    invoice = b"INVOICE No 4411. Bill to Acme. Subtotal 900. Tax 18. Total due 1,062. Payment terms net 30. Due date 2024-05-01. Unit price and qty below."
    resume = b"Curriculum Vitae. Work experience: engineer. Education: BSc. Skills: python. References available. Objective: grow."
    sheet = make_xlsx({"S": [["a", "b"], [1, 2]]})
    got = {}
    for name, data in (("c.txt", contract), ("i.txt", invoice), ("r.txt", resume), ("d.xlsx", sheet), ("n.txt", b"Lunch menu: pasta on friday and fruit")):
        src = up(client2, name, data)["source"]
        got[name] = src["classification"]
        assert client2.get(f"/sources/{src['id']}/classification", headers=H).json()["label"] == got[name]["label"]
    assert {k: v["label"] for k, v in got.items()} == {"c.txt": "contract", "i.txt": "invoice", "r.txt": "resume", "d.xlsx": "dataset", "n.txt": "other"}
    assert got["c.txt"]["method"] == "keywords" and 0 < got["c.txt"]["confidence"] <= 1 and got["d.xlsx"]["method"] == "structure"


def test_llm_classification_is_restricted_to_the_taxonomy(tmp_path):
    for reply, expect in (('{"label": "policy", "confidence": 0.9}', "policy"), ('{"label": "top-secret-plan", "confidence": 0.99}', "other"), ("not json", "other")):
        s = Settings(data_dir=str(tmp_path / expect / str(hash(reply) % 999)), _env_file=None)
        c = TestClient(create_app(s, Knowledge(s, llm=FakeLLM(lambda sy, u, r=reply: r if "Classify the document" in sy else None))))
        src = up(c, "mystery.txt", b"Some neutral prose about weather.")["source"]
        assert src["classification"]["label"] == expect, reply
        assert src["classification"]["method"] == ("llm" if expect == "policy" else "keywords")


# ----------------------------------------------------------------------------------------------- timeline
def test_timeline_extraction_and_api(client2):
    text = ("Project Falcon kicked off on 12 March 2024. The first review was held on 2024-04-18 with all leads.\n\n"
            "Phase two starts in Q3 2024. A follow-up is due 05/06/2024 per the agreement. The company was founded in 2019.")
    sid = up(client2, "plan.txt", text.encode())["source"]["id"]
    ev = client2.get(f"/sources/{sid}/timeline", headers=H).json()["events"]
    dates = [(e["date"], e["precision"]) for e in ev]
    assert dates == [("2019-01-01", "year"), ("2024-03-12", "day"), ("2024-04-18", "day"), ("2024-06-05", "day"), ("2024-07-01", "quarter")]
    first = next(e for e in ev if e["date"] == "2024-03-12")
    assert "Project Falcon kicked off" in first["event"] and first["location"].startswith("line") and first["source"] == "plan.txt"
    assert next(e for e in ev if e["date"] == "2024-06-05")["ambiguous"] is True  # 05/06 could be 5 June or 6 May


def test_timeline_over_spreadsheet_rows_and_cross_document(client2):
    up(client2, "a.txt", b"The audit started on 1 February 2024.")
    up(client2, "b.txt", b"The audit ended on 15 January 2024 earlier than planned.")
    from app.intel.timeline import build_timeline

    k = client2.app.state.knowledge
    st = k.store(Scope("default", "s1"))
    items = [(m, u) for m, u in st.iter_units()]
    ev = build_timeline(items)
    assert [(e["date"], e["source"]) for e in ev] == [("2024-01-15", "b.txt"), ("2024-02-01", "a.txt")]  # merged chronologically across documents


# ----------------------------------------------------------------------------------------------- previews
def test_passage_and_page_image_endpoints(client2):
    sid = up(client2, "p.pdf", make_pdf(["First page text.", "Second page mentions the quarterly budget of five thousand dollars."]))["source"]["id"]
    p = client2.get(f"/sources/{sid}/passage?page=2", headers=H).json()
    assert "quarterly budget" in p["text"] and p["before"] == "First page text." and p["after"] is None and p["location"] == "page 2"
    assert client2.get(f"/sources/{sid}/passage?page=9", headers=H).status_code == 404 and client2.get(f"/sources/{sid}/passage", headers=H).status_code == 422
    plain = client2.get(f"/sources/{sid}/pages/2/image", headers=H)
    hl = client2.get(f"/sources/{sid}/pages/2/image?highlight=quarterly budget", headers=H)
    assert plain.status_code == 200 and plain.content[:8] == b"\x89PNG\r\n\x1a\n" and hl.content[:4] == b"\x89PNG"
    assert plain.content != hl.content  # the highlight was drawn
    im = Image.open(io.BytesIO(hl.content))
    assert im.width > 500 and any(px[0] >= 250 and px[1] >= 200 and px[2] <= 190 for px in im.convert("RGB").getdata())  # translucent yellow pixels
    assert client2.get(f"/sources/{sid}/pages/3/image", headers=H).status_code == 404
    t = up(client2, "n.txt", b"plain text document")["source"]["id"]
    assert client2.get(f"/sources/{t}/pages/1/image", headers=H).status_code == 415
    sx = up(client2, "d.xlsx", make_xlsx({"S": [["k", "v"], ["alpha", 7]]}))["source"]["id"]
    row = client2.get(f"/sources/{sx}/passage?sheet=S&row=2", headers=H).json()
    assert "alpha" in row["text"] and row["loc"] == {"sheet": "S", "row": 2}


def test_citations_carry_machine_readable_locations(client2):
    up(client2, "p.pdf", make_pdf(["Alpha leave policy gives twenty five days."]))
    up(client2, "d.xlsx", make_xlsx({"S": [["name", "sales"], ["Zed", 10], ["Amy", 99]]}))
    assert ask(client2, "How many days of leave policy?")["citations"][0]["loc"] == {"page": 1}
    c = ask(client2, "Which name has the highest sales?")["citations"][0]
    assert c["loc"] == {"sheet": "S", "row": 3} and c["location"] == "sheet 'S', row 3"
    assert ask(client2, 'find "Zed"')["citations"][0]["loc"] == {"sheet": "S", "row": 2}


def test_preview_respects_document_permissions(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="v" * 40, rate_limit_ingest="1000/minute", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    adm = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Tenant", "email": "a@a.io", "password": "long enough pw"}).json()["access_token"]}
    c.post("/admin/users", json={"email": "u@a.io", "password": "long enough pw", "role": "user"}, headers=adm)
    usr = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@a.io", "password": "long enough pw"}).json()["access_token"]}
    sid = c.post("/sources/upload", files=[("files", ("s.pdf", make_pdf(["Confidential salary table"])))], data={"visibility": "private"}, headers={**adm, **H}).json()[0]["source"]["id"]
    for path in (f"/sources/{sid}/passage?page=1", f"/sources/{sid}/pages/1/image", f"/sources/{sid}/timeline", f"/sources/{sid}/classification"):
        assert c.get(path, headers={**adm, **H}).status_code == 200
        assert c.get(path, headers={**usr, **H}).status_code == 404, path


# ----------------------------------------------------------------------------------------------- progress, corrupt input
def test_ingestion_reports_fine_grained_progress(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), embed_batch=2, _env_file=None)
    k = Knowledge(s)
    p = tmp_path / "big.pdf"
    p.write_bytes(make_pdf([f"Page {i} " + "filler words " * 40 for i in range(60)]))
    seen = []
    r = k.ingest_file(Scope("t", "w"), p, "big.pdf", progress=lambda stage, pct: seen.append((stage, pct)))
    assert r["status"] == "ready"
    stages = [s_ for s_, _ in seen]
    assert stages[0] == "extracting" and "chunking" in stages and stages.count("embedding") >= 5 and stages[-1] == "indexing"
    pcts = [p_ for _, p_ in seen]
    assert pcts == sorted(pcts) and max(pcts) <= 99  # monotonic, never claims 100% before the commit


@pytest.mark.parametrize("name,data", [
    ("trunc.docx", None), ("bad.png", b"\x89PNG\r\n\x1a\nnot really a png"), ("trunc.xlsx", None), ("html.pdf", b"<html>not a pdf</html>"), ("zero.csv", b""),
    ("cut.pdf", None), ("bin.json", b"\x00\x01\x02binary"), ("ws.csv", b"\n\n\n   \n"),
])
def test_corrupt_files_fail_cleanly(client2, name, data):
    if data is None:
        data = {"trunc.docx": make_docx(["hello world"])[:200], "trunc.xlsx": make_xlsx({"S": [["a"], [1]]})[:300], "cut.pdf": make_pdf(["some text here"])[:300]}[name]
    r = up(client2, name, data)
    assert r["status"] == "failed" and r["error"] and "Traceback" not in r["error"]
    assert client2.get("/sources", headers=H).json() == []  # nothing half-indexed
