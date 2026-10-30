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

SUPPORTED = {".pdf": "pdf", ".csv": "csv", ".xlsx": "xlsx", ".docx": "docx", ".txt": "txt", ".md": "md", ".markdown": "md", ".json": "json",
             ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image", ".webp": "image"}
TABULAR_KINDS = ("csv", "xlsx")


def kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise IngestError(f"Unsupported file type '{ext or filename}'. Supported: {', '.join(sorted(SUPPORTED))}")
    return SUPPORTED[ext]


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


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


def _load_pdf(path: Path, st: Settings) -> Extracted:
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
    return Extracted(units, title=title, warnings=warnings, meta={"pages": len(pages), "ocr_pages": ocr_pages}, tables=tables)


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
    return Extracted(units, tables=tables)


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


# ----------------------------------------------------------------------------- dispatcher
def extract(path: Path, kind: str, st: Optional[Settings] = None) -> Extracted:
    st = st or Settings(_env_file=None)
    try:
        if kind == "image":
            return _load_image(path, st)
        if kind == "pdf":
            return _load_pdf(path, st)
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
