"""User-requested attachments: private bytes, bounded inspection, no execution."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import stat
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 18000
MAX_ZIP_MEMBERS = 600
MAX_ZIP_BYTES = 32 * 1024 * 1024
TEXT_EXT = {".txt", ".md", ".rst", ".log", ".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".sh", ".sql", ".toml", ".ini", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".csv", ".tsv", ".html", ".htm", ".css", ".svg", ".rtf", ".ipynb"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ZIP_EXT = {".docx", ".pptx", ".xlsx", ".odt", ".epub", ".zip"}
ALLOWED = TEXT_EXT | IMAGE_EXT | ZIP_EXT | {".pdf"}
ID = re.compile(r"[0-9a-f]{32}\Z")

class StudioError(ValueError):
    pass


def private_root(path: Path) -> Path:
    for item in (path.parent, path):
        if not item.exists():
            item.mkdir(mode=0o700)
        st = item.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise StudioError("Studio file store must be a private, real directory")
    return path


def _name(name: str) -> str:
    if (not isinstance(name, str) or not 1 <= len(name) <= 160
            or name.startswith(".") or "/" in name or "\\" in name or "\x00" in name):
        raise StudioError("Invalid filename")
    return name


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def _package_text(data: bytes, extension: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_MEMBERS or sum(x.file_size for x in infos) > MAX_ZIP_BYTES:
            raise StudioError("Archive exceeds safe extraction budget")
        items = []
        for entry in infos:
            if entry.flag_bits & 1 or entry.file_size > 5_000_000:
                raise StudioError("Encrypted or oversized archive entry")
            path = entry.filename
            if path.startswith("/") or ".." in Path(path).parts:
                raise StudioError("Unsafe archive member")
            if extension == ".docx":
                use = path == "word/document.xml"
            elif extension == ".pptx":
                use = bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", path))
            elif extension == ".xlsx":
                use = path == "xl/sharedStrings.xml" or bool(re.fullmatch(r"xl/worksheets/sheet\d+\.xml", path))
            elif extension == ".odt":
                use = path == "content.xml"
            elif extension == ".epub":
                use = path.endswith((".html", ".xhtml", ".htm"))
            else:
                use = False
            if use:
                raw = archive.read(entry)[:2_000_000]
                if extension == ".epub":
                    parser = _HTMLText()
                    parser.feed(raw.decode("utf-8", errors="replace"))
                    items.append(" ".join(parser.chunks))
                else:
                    try:
                        # Only character-data nodes; never resolve external references.
                        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                            raise StudioError("Unsafe XML declaration")
                        root = ET.fromstring(raw)
                    except ET.ParseError as exc:
                        raise StudioError("Invalid document XML") from exc
                    items.append(" ".join(t.strip() for t in root.itertext() if t.strip()))
            if sum(len(x) for x in items) > MAX_TEXT:
                break
        if extension == ".zip":
            return "ZIP archive entries (not executed/extracted):\n" + "\n".join(x.filename for x in infos[:150])
        if not items:
            raise StudioError("This document contains no accessible text")
        return "\n".join(items)[:MAX_TEXT]


def inspect_bytes(data: bytes, filename: str) -> tuple[str, str]:
    """Return (kind, safe bounded extract); unsupported formats stay available as metadata."""
    extension = Path(filename).suffix.lower()
    if extension in IMAGE_EXT:
        signatures = {".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",),
                      ".jpeg": (b"\xff\xd8\xff",), ".gif": (b"GIF87a", b"GIF89a"),
                      ".webp": (b"RIFF",)}
        if not any(data.startswith(x) for x in signatures[extension]):
            raise StudioError("File contents are not a valid image signature")
        if extension == ".webp" and data[8:12] != b"WEBP":
            raise StudioError("Invalid WebP signature")
        return "image", "Image uploaded. Visual interpretation requires an installed Ollama vision model."
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise StudioError("Invalid PDF header")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise StudioError("PDF text extraction requires pypdf in the MioAgent venv") from exc
        try:
            doc = PdfReader(io.BytesIO(data), strict=False)
            if doc.is_encrypted:
                raise StudioError("Password-protected PDF requires a decrypted copy")
            extracted = "\n".join((p.extract_text() or "") for p in doc.pages[:30])[:MAX_TEXT]
            if not extracted.strip():
                raise StudioError("PDF has no selectable text; scanned PDF OCR is not enabled")
            return "document", extracted
        except Exception as exc:
            if isinstance(exc, StudioError):
                raise
            raise StudioError("PDF text extraction failed") from exc
    if extension in ZIP_EXT:
        if not data.startswith(b"PK"):
            raise StudioError("Invalid zipped document")
        try:
            return "document", _package_text(data, extension)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise StudioError("Invalid archive") from exc
    if extension in TEXT_EXT:
        if b"\x00" in data[:4096]:
            raise StudioError("Binary content does not match text filename")
        raw = data[:MAX_TEXT * 3].decode("utf-8", errors="replace")
        if extension in (".html", ".htm"):
            parser = _HTMLText()
            parser.feed(raw)
            return "text", " ".join(parser.chunks)[:MAX_TEXT]
        if extension == ".csv" or extension == ".tsv":
            separator = "\t" if extension == ".tsv" else ","
            rows = csv.reader(io.StringIO(raw), delimiter=separator)
            return "text", "\n".join(" | ".join(row[:35]) for _, row in zip(range(130), rows))[:MAX_TEXT]
        if extension == ".ipynb":
            try:
                notebook = json.loads(raw)
                cells = notebook.get("cells", [])
                return "text", "\n".join("".join(cell.get("source", [])) for cell in cells[:100])[:MAX_TEXT]
            except (ValueError, AttributeError):
                raise StudioError("Invalid notebook") from None
        return "text", raw[:MAX_TEXT]
    return "binary", "Unsupported binary format. Stored for reference; no content analysis available."


def save_attachment(root: Path, name: str, content_b64: str) -> dict:
    name = _name(name)
    if not isinstance(content_b64, str) or len(content_b64) > (MAX_FILE * 4 // 3) + 8:
        raise StudioError("Attachment too large (8 MiB maximum)")
    try:
        data = base64.b64decode(content_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise StudioError("Invalid attachment encoding") from exc
    if not data or len(data) > MAX_FILE:
        raise StudioError("Attachment must contain 1 byte to 8 MiB")
    kind, extract = inspect_bytes(data, name)
    store = private_root(root)
    file_id = uuid.uuid4().hex
    meta = {"id": file_id, "name": name, "kind": kind, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "extract": extract}
    for suffix, value in ((".bin", data), (".json", json.dumps(meta).encode())):
        handle = os.open(store / (file_id + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(handle, "wb") as f:
            f.write(value)
    return {k: v for k, v in meta.items() if k != "extract"}


def read_attachment(root: Path, file_id: str) -> tuple[dict, bytes]:
    if not isinstance(file_id, str) or not ID.fullmatch(file_id):
        raise StudioError("Unknown attachment")
    store = private_root(root)
    records = []
    for suffix in (".json", ".bin"):
        path = store / (file_id + suffix)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise StudioError("Unsafe stored attachment")
        records.append(path.read_bytes())
    meta, raw = json.loads(records[0]), records[1]
    if meta["id"] != file_id or len(raw) != meta["bytes"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
        raise StudioError("Attachment integrity verification failed")
    # Older PDFs were saved with a placeholder if pypdf was absent. Reinspect
    # the checksum-verified bytes without changing the private original.
    if (meta["name"].lower().endswith(".pdf") and
            meta.get("extract", "").startswith("PDF stored. Install optional pypdf")):
        kind, extracted = inspect_bytes(raw, meta["name"])
        meta = {**meta, "kind": kind, "extract": extracted}
    return meta, raw
