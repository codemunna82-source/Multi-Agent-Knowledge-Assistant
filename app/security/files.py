"""Upload validation: extension allow-list, magic bytes vs. claimed type, zip-bomb limits, binary-in-text detection.
Runs BEFORE any parser touches the file."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..core import IngestError

TEXT_KINDS = {"txt", "md", "csv", "json", "html"}
IMAGE_MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "tiff_le": b"II*\x00", "tiff_be": b"MM\x00*"}
_SAFE = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = _SAFE.sub("_", name).strip(" .")[:200]
    return name or "upload"


def _zip_check(path: Path, required: str, max_uncompressed: int) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > 10000:
                raise IngestError("Archive has too many entries")
            total = sum(i.file_size for i in infos)
            comp = max(1, sum(i.compress_size for i in infos))
            if total > max_uncompressed:
                raise IngestError("Document expands to an unreasonable size (possible zip bomb)")
            if total / comp > 200 and total > 50 * 1024 * 1024:
                raise IngestError("Document has a suspicious compression ratio (possible zip bomb)")
            names = {i.filename for i in infos}
            if "[Content_Types].xml" not in names or required not in names:
                raise IngestError("File content does not match its extension")
            if any(n.startswith(("/", "..")) or ".." in Path(n).parts for n in names):
                raise IngestError("Archive contains unsafe paths")
            if "word/vbaProject.bin" in names or "xl/vbaProject.bin" in names:
                raise IngestError("Documents containing macros are not accepted")
    except zipfile.BadZipFile as e:
        raise IngestError("File content does not match its extension (not a valid Office document)") from e


def validate_upload(path: Path, kind: str, max_uncompressed_mb: int = 500) -> None:
    with open(path, "rb") as f:
        head = f.read(8192)
    if not head:
        raise IngestError("The file is empty")
    if kind == "pdf":
        if not head.lstrip(b"\x00 \t\r\n")[:5] == b"%PDF-":
            raise IngestError("File content does not match its extension (not a PDF)")
    elif kind == "docx":
        _zip_check(path, "word/document.xml", max_uncompressed_mb * 1024 * 1024)
    elif kind == "xlsx":
        _zip_check(path, "xl/workbook.xml", max_uncompressed_mb * 1024 * 1024)
    elif kind == "xls":
        if not head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise IngestError("File content does not match its extension (not a legacy Excel workbook)")
    elif kind == "image":
        if not any(head.startswith(m) for m in IMAGE_MAGIC.values()) and not (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
            raise IngestError("File content does not match its extension (not a supported image)")
    elif kind in TEXT_KINDS:
        if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise IngestError("File looks binary, not text")
        if head.startswith((b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF-")):
            raise IngestError("File content does not match its extension")
