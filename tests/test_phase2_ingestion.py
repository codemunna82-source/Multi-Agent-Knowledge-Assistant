import datetime
import http.server
import io
import socket
import ssl
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.api import create_app
from app.config import Settings
from app.core import IngestError
from app.ingestion import web

from .conftest import ask, make_docx, make_pdf, make_xlsx, upload

H = {"X-Session-ID": "s1"}


def scan_png(text: str) -> bytes:
    img = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(img).text((20, 40), text, fill="black", font=ImageFont.load_default(size=56))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def scanned_pdf(text: str) -> bytes:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 200))
    c.drawImage(ImageReader(io.BytesIO(scan_png(text))), 0, 20, width=600, height=107)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def ocr_client(tmp_path):
    return TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), ocr_enabled=True, _env_file=None)))


def test_scanned_pdf_rejected_without_ocr_and_read_with_ocr(client, ocr_client):
    data = scanned_pdf("Invoice for Anjali Sharma")
    r = upload(client, "scan.pdf", data)
    assert r["status"] == "failed" and "OCR" in r["error"]
    r = upload(ocr_client, "scan.pdf", data)
    assert r["status"] == "ready" and any("OCR" in w for w in r["source"]["warnings"])
    a = ask(ocr_client, "Does Sharma appear in the document?")
    assert a["details"]["count"] == 1 and a["citations"][0]["location"] == "page 1"


def test_image_upload_is_ocr_indexed(ocr_client):
    r = upload(ocr_client, "receipt.png", scan_png("Total due 4520 rupees"))
    assert r["status"] == "ready"
    a = ask(ocr_client, 'find "rupees"')
    assert a["details"]["count"] == 1 and "image (OCR)" in a["citations"][0]["location"]
    blank = Image.new("RGB", (200, 100), "white")
    buf = io.BytesIO()
    blank.save(buf, "PNG")
    assert upload(ocr_client, "blank.png", buf.getvalue())["status"] == "failed"


def test_image_vision_caption_pipeline(tmp_path):
    from app.service import Knowledge
    from tests.fakes import FakeLLM

    s = Settings(data_dir=str(tmp_path / "d"), vision_captions=True, _env_file=None)
    llm = FakeLLM(image_caption="A bar chart showing quarterly revenue growth")
    c = TestClient(create_app(s, Knowledge(s, llm=llm)))
    assert upload(c, "chart.png", scan_png("Q1 Q2 Q3"))["status"] == "ready"
    a = ask(c, 'find "quarterly revenue"')
    assert a["details"]["count"] == 1 and "image caption" in a["citations"][0]["location"]


def test_file_validation(client):
    pdf_as_docx = make_pdf(["x"])
    assert "match its extension" in upload(client, "fake.docx", pdf_as_docx)["error"]
    assert "match its extension" in upload(client, "fake.xlsx", make_docx(["hello"]))["error"]  # docx zip renamed to xlsx
    assert "binary" in upload(client, "bin.txt", b"abc\x00\x01\x02def")["error"]
    assert "match" in upload(client, "evil.csv", b"MZ\x90 not csv")["error"] or "binary" in upload(client, "evil2.csv", b"MZ\x90\x00not csv")["error"]
    assert "match its extension" in upload(client, "photo.png", b"GIF89a....")["error"]
    # macro-enabled office file
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", "<x/>")
        z.writestr("word/vbaProject.bin", b"macro")
    assert "macros" in upload(client, "m.docx", buf.getvalue())["error"]


def test_zip_bomb_rejected(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), max_zip_uncompressed_mb=1, _env_file=None)
    c = TestClient(create_app(s))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", b"\0" * (5 * 1024 * 1024))
    assert "zip bomb" in upload(c, "bomb.docx", buf.getvalue())["error"]


def test_pdf_page_limit(tmp_path):
    c = TestClient(create_app(Settings(data_dir=str(tmp_path / "d"), max_pdf_pages=3, _env_file=None)))
    assert "limit" in upload(c, "long.pdf", make_pdf([f"page {i}" for i in range(5)]))["error"]


def test_pdf_sections_from_bookmarks(client):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i, title in enumerate(["Introduction", "Termination", "Payment"], 1):
        c.bookmarkPage(f"p{i}")
        c.addOutlineEntry(title, f"p{i}", level=0)
        c.drawString(50, 800, f"Body of the {title.lower()} part with keyword{i}")
        c.showPage()
    c.save()
    upload(client, "contract.pdf", buf.getvalue())
    a = ask(client, 'find "keyword2"')
    assert a["citations"][0]["location"] == "page 2 (section: Termination)"


def test_table_extraction_pdf_docx_xlsx_html(client):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    t = Table([["Item", "Qty", "Price"], ["Pen", "10", "5"], ["Book", "2", "40"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([t])
    sid = upload(client, "inv.pdf", buf.getvalue())["source"]["id"]
    tabs = client.get(f"/sources/{sid}/tables", headers=H).json()
    assert tabs and tabs[0]["header"] == ["Item", "Qty", "Price"] and tabs[0]["rows"][1] == ["Book", "2", "40"] and tabs[0]["location"]["page"] == 1
    # table cell text is NOT duplicated as searchable units: exact counts stay correct
    assert ask(client, 'How many times does "Book" appear?')["details"]["count"] == 1

    sid = upload(client, "t.docx", make_docx(["intro"], [["k", "v"], ["a", "1"], ["b", "2"]]))["source"]["id"]
    assert client.get(f"/sources/{sid}/tables", headers=H).json()[0]["rows"] == [["a", "1"], ["b", "2"]]
    sid = upload(client, "s.xlsx", make_xlsx({"Q1": [["n", "v"], ["x", 1], ["y", 2]]}))["source"]["id"]
    tx = client.get(f"/sources/{sid}/tables", headers=H).json()[0]
    assert tx["location"] == {"sheet": "Q1"} and tx["total_rows"] == 2
    assert client.get("/sources/" + "0" * 32 + "/tables", headers=H).status_code == 404


# ---------------------------------------------------------------- SSRF: connect-by-IP pinning against DNS rebinding
def _selfsigned(host: str, tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False).sign(key, hashes.SHA256()))
    cp, kp = tmp_path / f"{host}.crt", tmp_path / f"{host}.key"
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return cp, kp


@pytest.fixture
def tls_server(tmp_path):
    cp, kp = _selfsigned("pin.test", tmp_path)

    class H_(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><title>Pinned</title><body><p>Served over verified TLS.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H_)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cp, kp)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], cp
    srv.shutdown()


def test_pinned_fetch_defeats_dns_rebinding_and_verifies_tls(tls_server, tmp_path, monkeypatch):
    port, cert = tls_server
    calls = []
    real = socket.getaddrinfo

    def rebinding(host, p, *a, **kw):
        if host == "pin.test":
            calls.append(host)
            ip = "127.0.0.1" if len(calls) == 1 else "10.255.255.1"  # attacker flips the answer after validation
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))]
        return real(host, p, *a, **kw)

    monkeypatch.setattr(web.socket, "getaddrinfo", rebinding)
    s = Settings(data_dir=str(tmp_path), allow_private_urls=True, url_ca_bundle=str(cert), url_timeout=5, _env_file=None)
    final, ctype, body = web.fetch(f"https://pin.test:{port}/", s)
    assert "verified TLS" in body and calls == ["pin.test"]  # resolved exactly once, connected to the vetted IP, cert verified for pin.test

    # certificate for a different name must be rejected (SNI/hostname verification still works when connecting by IP)
    other, _ = _selfsigned("other.test", tmp_path)
    s2 = Settings(data_dir=str(tmp_path), allow_private_urls=True, url_ca_bundle=str(other), url_timeout=5, _env_file=None)
    with pytest.raises(IngestError):
        web.fetch(f"https://pin.test:{port}/", s2)
