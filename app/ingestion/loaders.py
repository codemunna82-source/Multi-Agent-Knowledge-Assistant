"""Format specific extraction. Every loader returns Units that carry source locations."""
from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Iterator, Optional

from ..config import Settings
from ..core import Extracted, IngestError, Unit

log = logging.getLogger("mka.loaders")

SUPPORTED = {".pdf": "pdf", ".csv": "csv", ".xlsx": "xlsx", ".xls": "xls", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md", ".json": "json",
             ".html": "html", ".htm": "html", ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image", ".webp": "image"}
TABULAR_KINDS = ("csv", "xlsx", "xls")


def kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise IngestError(f"Unsupported file type '{ext or filename}'. Supported: {', '.join(sorted(SUPPORTED))}")
    return SUPPORTED[ext]


def decode(data: bytes) -> str:
    """Bytes -> text without ever failing: BOMs, UTF-8, then statistical detection (cp1252, GBK, Shift-JIS, ...), then latin-1 with replacement."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data[:200_000]).best()
        if best is not None:
            return data.decode(best.encoding, errors="replace")
    except Exception:  # detection is best-effort
        pass
    return data.decode("cp1252", errors="replace")


# ----------------------------------------------------------------------------- tabular (shared with analysis)
def _dedupe_header(cells: list) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, c in enumerate(cells):
        name = str(c).strip() if c is not None and str(c).strip() else f"column_{i + 1}"
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_sheets(path: Path, kind: str) -> list[tuple[Optional[str], list[str], list[tuple[int, list[str]]]]]:
    """-> [(sheet_name, header, [(row_number, cells)])]. Row numbers match the spreadsheet (header row counts)."""
    sheets = []
    if kind == "csv":
        text = decode(path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = ((i, [_cell(c) for c in r]) for i, r in enumerate(csv.reader(text.splitlines(), dialect), 1))
        sheets.append((None, rows))
    elif kind == "xls":
        try:
            import xlrd

            book = xlrd.open_workbook(str(path), on_demand=True)
        except Exception as e:
            raise IngestError(f"Could not open legacy Excel workbook: {e}") from e

        def xls_rows(sh):
            for i in range(sh.nrows):
                row = []
                for c in sh.row(i):
                    if c.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(xlrd.xldate_as_datetime(c.value, book.datemode).date().isoformat())
                        except Exception:
                            row.append(str(c.value))
                    elif c.ctype == xlrd.XL_CELL_ERROR:
                        row.append("")
                    else:
                        row.append(_cell(c.value))
                yield i + 1, row

        for sh in book.sheets():
            sheets.append((sh.name, xls_rows(sh)))
    else:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as e:  # corrupt / not an xlsx
            raise IngestError(f"Could not open workbook: {e}") from e
        for ws in wb.worksheets:
            sheets.append((ws.title, ((i, [_cell(c) for c in r]) for i, r in enumerate(ws.iter_rows(values_only=True), 1))))
    out = []
    for name, rows in sheets:
        header: Optional[list[str]] = None
        data: list[tuple[int, list[str]]] = []
        for rn, cells in rows:
            if not any(cells):
                continue
            if header is None:
                header = _dedupe_header(cells)
                continue
            data.append((rn, cells))
        if header is not None and data:
            out.append((name, header, data))
    return out


def _load_tabular(path: Path, kind: str) -> Extracted:
    sheets = read_sheets(path, kind)
    if not sheets:
        raise IngestError("The spreadsheet has no data rows")
    units: list[Unit] = []
    for name, header, data in sheets:
        for rn, cells in data:
            text = "; ".join(f"{h}: {c}" for h, c in zip(header, cells) if c != "")
            if text:
                loc = {"row": rn} if name is None else {"sheet": name, "row": rn}
                units.append(Unit(text, loc))
    if not units:
        raise IngestError("The spreadsheet has no data rows")
    meta = {"tables": [{"sheet": n, "columns": h, "rows": len(d)} for n, h, d in sheets]}
    return Extracted(units, meta=meta)


# ----------------------------------------------------------------------------- PDF
def _ocr_image(img, lang: str) -> str:
    try:
        import pytesseract
    except ImportError as e:
        raise IngestError("OCR requires the 'pytesseract' package and the Tesseract binary") from e
    try:
        return pytesseract.image_to_string(img, lang=lang)
    except pytesseract.TesseractNotFoundError as e:
        raise IngestError("OCR requires the Tesseract binary (apt install tesseract-ocr)") from e
    except pytesseract.TesseractError as e:
        raise IngestError(f"OCR failed: {e}") from e


def _ocr_page(path: Path, index: int, lang: str) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise IngestError("OCR requires pypdfium2") from e
    pdf = pdfium.PdfDocument(str(path))
    try:
        return _ocr_image(pdf[index].render(scale=2).to_pil(), lang)
    finally:
        pdf.close()


def _outline(reader) -> list[tuple[int, str]]:
    """Flattened bookmarks -> [(page_index, title)] sorted by page; used as PDF section/heading metadata."""
    out: list[tuple[int, str]] = []

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                try:
                    out.append((reader.get_destination_page_number(it), str(it.title).strip()))
                except Exception:
                    pass

    try:
        walk(reader.outline)
    except Exception:
        return []
    return sorted((p, t) for p, t in out if p is not None and p >= 0 and t)


def _pdf_tables(path: Path, max_pages: int) -> tuple[list[dict], list[str]]:
    try:
        import pdfplumber
    except ImportError:
        return [], ["PDF table extraction skipped (pdfplumber not installed)"]
    tables, warns = [], []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for pi, page in enumerate(pdf.pages[:max_pages], 1):
                try:
                    for ti, t in enumerate(page.extract_tables(), 1):
                        rows = [[(c or "").strip() for c in r] for r in t if any(c for c in r)]
                        if len(rows) >= 2:
                            tables.append({"location": {"page": pi, "table": ti}, "header": rows[0], "rows": rows[1:]})
                except Exception as e:
                    warns.append(f"page {pi}: table extraction failed ({e})")
            if len(pdf.pages) > max_pages:
                warns.append(f"table extraction limited to the first {max_pages} pages")
    except Exception as e:
        warns.append(f"table extraction failed ({e})")
    return tables, warns


def _load_pdf_pypdf(path: Path, st: Settings, on_page=None) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise IngestError("The PDF is password protected")
        pages = list(reader.pages)
    except IngestError:
        raise
    except (PyPdfError, Exception) as e:
        raise IngestError(f"Could not read PDF (corrupt or unsupported): {e}") from e
    if len(pages) > st.max_pdf_pages:
        raise IngestError(f"The PDF has {len(pages)} pages; the limit is {st.max_pdf_pages}")
    outline = _outline(reader)
    units, warnings, empty, ocr_pages = [], [], [], []
    oi, section = 0, None
    for i, page in enumerate(pages, 1):
        if on_page:
            on_page(i, len(pages))
        while oi < len(outline) and outline[oi][0] <= i - 1:
            section = outline[oi][1]
            oi += 1
        try:
            text = (page.extract_text() or "").strip()
        except Exception as e:
            warnings.append(f"page {i}: extraction failed ({e})")
            text = ""
        if not text and st.ocr_enabled:
            try:
                text = _ocr_page(path, i - 1, st.ocr_languages).strip()
                if text:
                    ocr_pages.append(i)
            except IngestError:
                raise
            except Exception as e:
                warnings.append(f"page {i}: OCR failed ({e})")
        if text:
            loc = {"page": i}
            if section:
                loc["section"] = section
            units.append(Unit(text, loc))
        else:
            empty.append(i)
    if ocr_pages:
        warnings.append(f"{len(ocr_pages)} page(s) were read with OCR (accuracy depends on scan quality): {_ranges(ocr_pages)}")
    if empty:
        warnings.append(f"{len(empty)} of {len(pages)} page(s) had no extractable text (scanned images?): {_ranges(empty)}")
    if not units:
        raise IngestError("The PDF contains no extractable text (it may be scanned; enable OCR with MKA_OCR_ENABLED=true)")
    tables = []
    if st.pdf_tables:
        tables, tw = _pdf_tables(path, st.pdf_tables_max_pages)
        warnings.extend(tw)
    title = (reader.metadata.title if reader.metadata else None) or None
    props = {k: str(v) for k, v in {"author": getattr(reader.metadata, "author", None), "subject": getattr(reader.metadata, "subject", None), "creator": getattr(reader.metadata, "creator", None)}.items() if v}
    return Extracted(units, title=title, warnings=warnings, meta={"pages": len(pages), "ocr_pages": ocr_pages, "properties": props, "engine": "pypdf"}, tables=tables)


def _ocr_pixmap(page, lang: str) -> str:
    from PIL import Image

    pix = page.get_pixmap(dpi=200)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples) if pix.n == 3 else Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).convert("RGB")
    return _ocr_image(img, lang)


def _body_font_size(doc, sample: int = 20) -> float:
    from collections import Counter

    c: Counter = Counter()
    for i in range(min(sample, len(doc))):
        for b in doc[i].get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    c[round(sp["size"], 1)] += len(sp["text"].strip())
    return c.most_common(1)[0][0] if c else 0.0


def _page_headings(page, body: float) -> list[str]:
    """Lines set noticeably larger than body text (>= 1.2x), short, not sentences -> section headings (used when the PDF has no bookmarks)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [sp for sp in ln["spans"] if sp["text"].strip()]
            if not spans:
                continue
            text = " ".join(sp["text"].strip() for sp in spans)
            if max(sp["size"] for sp in spans) >= body * 1.2 and 2 <= len(text) <= 100 and not text.endswith((".", ",", ";")):
                out.append(text)
    return out


def _load_pdf_mupdf(path: Path, st: Settings, on_page=None) -> Extracted:
    import pymupdf

    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise IngestError(f"Could not read PDF (corrupt or unsupported): {e}") from e
    try:
        if doc.needs_pass and not doc.authenticate(""):
            raise IngestError("The PDF is password protected")
        n = len(doc)
        if n == 0:
            raise IngestError("The PDF has no pages")
        if n > st.max_pdf_pages:
            raise IngestError(f"The PDF has {n} pages; the limit is {st.max_pdf_pages}")
        toc = [(max(p - 1, 0), t.strip()) for lvl, t, p in doc.get_toc(simple=True) if lvl <= 3 and t.strip()]
        toc.sort(key=lambda x: x[0])
        body = 0.0 if (toc or n > st.pdf_heading_max_pages) else _body_font_size(doc)
        units, warnings, empty, ocr_pages = [], [], [], []
        ti, section = 0, None
        tables: list[dict] = []
        want_tables = st.pdf_tables and hasattr(pymupdf.Page, "find_tables")
        for i, page in enumerate(doc, 1):
            if on_page:
                on_page(i, n)
            while ti < len(toc) and toc[ti][0] <= i - 1:
                section = toc[ti][1]
                ti += 1
            try:
                # INFINITE_RECT: by default MuPDF silently drops glyphs outside the page box (e.g. very long un-wrapped lines);
                # the text is still part of the document, and an "exact search over the complete text" must not lose it
                text = page.get_text("text", clip=pymupdf.INFINITE_RECT(), flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_MEDIABOX_CLIP).strip()  # content-stream order = reading order (sort=True would interleave columns and is 20x slower)
            except Exception as e:
                warnings.append(f"page {i}: extraction failed ({e})")
                text = ""
            if body and text:
                try:
                    heads = _page_headings(page, body)
                    if heads:
                        section = heads[0]
                except Exception:
                    pass
            if not text and st.ocr_enabled:
                try:
                    text = _ocr_pixmap(page, st.ocr_languages).strip()
                    if text:
                        ocr_pages.append(i)
                except IngestError:
                    raise
                except Exception as e:
                    warnings.append(f"page {i}: OCR failed ({e})")
            if text:
                loc = {"page": i}
                if section:
                    loc["section"] = section
                units.append(Unit(text, loc))
            else:
                empty.append(i)
            # find_tables costs 60-140 ms/page; ruled tables always have vector line/rect drawings, so text-only pages are skipped
            # (borderless tables are therefore not detected - documented limitation)
            if want_tables and i <= st.pdf_tables_max_pages and text and len(page.get_drawings()) >= 6:
                try:
                    for tn, t in enumerate(page.find_tables().tables, 1):
                        rows = [[(c or "").strip() for c in r] for r in t.extract() if any(c for c in r)]
                        if len(rows) >= 2 and len(rows[0]) >= 2:
                            tables.append({"location": {"page": i, "table": tn}, "header": rows[0], "rows": rows[1:]})
                except Exception as e:
                    warnings.append(f"page {i}: table extraction failed ({e})")
        if want_tables and n > st.pdf_tables_max_pages:
            warnings.append(f"table extraction limited to the first {st.pdf_tables_max_pages} pages")
        if ocr_pages:
            warnings.append(f"{len(ocr_pages)} page(s) were read with OCR (accuracy depends on scan quality): {_ranges(ocr_pages)}")
        if empty:
            warnings.append(f"{len(empty)} of {n} page(s) had no extractable text (scanned images?): {_ranges(empty)}")
        if not units:
            raise IngestError("The PDF contains no extractable text (it may be scanned; enable OCR with MKA_OCR_ENABLED=true)")
        md = doc.metadata or {}
        props = {k: v for k, v in {"author": md.get("author"), "subject": md.get("subject"), "creator": md.get("creator"), "producer": md.get("producer"), "created": md.get("creationDate")}.items() if v}
        return Extracted(units, title=(md.get("title") or None), warnings=warnings, meta={"pages": n, "ocr_pages": ocr_pages, "properties": props, "engine": "pymupdf"}, tables=tables)
    finally:
        doc.close()


def _load_pdf(path: Path, st: Settings, on_page=None) -> Extracted:
    """PyMuPDF (fast, headings, tables, page images) when available; pypdf + pdfplumber as fallback. MKA_PDF_ENGINE=pypdf forces the fallback."""
    if st.pdf_engine != "pypdf":
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            pass
        else:
            return _load_pdf_mupdf(path, st, on_page)
    return _load_pdf_pypdf(path, st, on_page)


def _ranges(nums: list[int], limit: int = 20) -> str:
    return ", ".join(map(str, nums[:limit])) + ("..." if len(nums) > limit else "")


# ----------------------------------------------------------------------------- DOCX
def _load_docx(path: Path) -> Extracted:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = docx.Document(str(path))
    except Exception as e:
        raise IngestError(f"Could not read DOCX (corrupt or unsupported): {e}") from e
    units: list[Unit] = []
    tables: list[dict] = []
    section, pn, tn = None, 0, 0
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            pn += 1
            if (p.style.name or "").lower().startswith("heading") or (p.style.name or "").lower() == "title":
                section = text
            loc = {"paragraph": pn}
            if section:
                loc["section"] = section
            units.append(Unit(text, loc))
        elif tag == "tbl":
            tn += 1
            t = Table(child, doc)
            header = [c.text.strip() for c in t.rows[0].cells] if t.rows else []
            if len(t.rows) >= 2:
                tables.append({"location": {"table": tn}, "header": header, "rows": [[c.text.strip() for c in r.cells] for r in t.rows[1:]]})
            for ri, row in enumerate(t.rows, 1):
                cells = [c.text.strip() for c in row.cells]
                if ri > 1 and header and any(header):
                    text = "; ".join(f"{h or 'col'}: {c}" for h, c in zip(header, cells) if c)
                else:
                    text = " | ".join(c for c in cells if c)
                if text:
                    units.append(Unit(text, {"table": tn, "row": ri}))
    if not units:
        raise IngestError("The DOCX file is empty")
    cp = doc.core_properties
    props = {k: str(v) for k, v in {"author": cp.author, "created": cp.created, "modified": cp.modified, "subject": cp.subject, "title": cp.title}.items() if v}
    return Extracted(units, title=(cp.title or None), tables=tables, meta={"properties": props})


# ----------------------------------------------------------------------------- TXT / MD
def _load_text(path: Path, kind: str) -> Extracted:
    text = decode(path.read_bytes())
    if not text.strip():
        raise IngestError("The file is empty")
    units: list[Unit] = []
    section: Optional[str] = None
    buf: list[str] = []
    start = 1
    size = 0

    def flush():
        nonlocal buf, size
        body = "\n".join(buf).strip()
        if body:
            loc = {"line": start}
            if section:
                loc["section"] = section
            units.append(Unit(body, loc))
        buf, size = [], 0

    for ln, line in enumerate(text.splitlines(), 1):
        if kind == "md" and (m := re.match(r"^#{1,6}\s+(.*\S)", line)):
            flush()
            section = m.group(1).strip()
            start = ln
            buf.append(line)
            size += len(line)
            continue
        if not line.strip():
            flush()
            start = ln + 1
            continue
        if not buf:
            start = ln
        buf.append(line)
        size += len(line) + 1
        if size > 2000:
            flush()
            start = ln + 1
    flush()
    return Extracted(units)


# ----------------------------------------------------------------------------- JSON
def _walk(node, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if re.fullmatch(r"\w+", str(k)) else f"{path}[{json.dumps(k)}]")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    elif node is not None and str(node).strip() != "":
        yield path, str(node)


def _load_json(path: Path) -> Extracted:
    try:
        data = json.loads(decode(path.read_bytes()))
    except (json.JSONDecodeError, RecursionError) as e:
        raise IngestError(f"Invalid JSON: {e}") from e
    units = [Unit(f"{p}: {v}", {"path": p}) for p, v in _walk(data, "$")]
    if not units:
        raise IngestError("The JSON file contains no values")
    return Extracted(units)


# ----------------------------------------------------------------------------- images (multimodal: OCR text; captions are added by the service)
def _load_image(path: Path, st: Settings) -> Extracted:
    try:
        from PIL import Image

        img = Image.open(path)
        img.load()
    except Exception as e:
        raise IngestError(f"Could not read image: {e}") from e
    if img.width * img.height > 100_000_000:
        raise IngestError("Image is too large")
    text = _ocr_image(img.convert("RGB"), st.ocr_languages).strip() if not st.vision_captions else ""
    if st.vision_captions:  # OCR is best-effort alongside captions
        try:
            text = _ocr_image(img.convert("RGB"), st.ocr_languages).strip()
        except IngestError:
            text = ""
    units = [Unit(text, {"image": 1})] if text else []
    return Extracted(units, meta={"image_size": [img.width, img.height]}, warnings=[] if text else ["No text recognised in the image"])


# ----------------------------------------------------------------------------- HTML files
def _load_html_file(path: Path) -> Extracted:
    from .web import extract_html

    body = decode(path.read_bytes())
    if "<" not in body:
        raise IngestError("The file does not contain HTML")
    return extract_html(path.name, "text/html", body, as_file=True)


# ----------------------------------------------------------------------------- dispatcher
def extract(path: Path, kind: str, st: Optional[Settings] = None, on_page=None) -> Extracted:
    """`on_page(done, total)` reports progress for page-based formats."""
    st = st or Settings(_env_file=None)
    try:
        if kind == "image":
            return _load_image(path, st)
        if kind == "html":
            return _load_html_file(path)
        if kind == "pdf":
            return _load_pdf(path, st, on_page)
        if kind in TABULAR_KINDS:
            return _load_tabular(path, kind)
        if kind == "docx":
            return _load_docx(path)
        if kind in ("txt", "md"):
            return _load_text(path, kind)
        if kind == "json":
            return _load_json(path)
    except IngestError:
        raise
    except Exception as e:
        log.exception("extraction failed")
        raise IngestError(f"Extraction failed: {e}") from e
    raise IngestError(f"Unsupported kind '{kind}'")
