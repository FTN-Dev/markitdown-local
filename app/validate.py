import os
import struct
from pathlib import Path

from .config import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, SUPPORTED_EXT

MAGIC = {
    ".pdf": b"%PDF",
    ".zip": b"PK",
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".gif": b"GIF",
    ".bmp": b"BM",
    ".tiff": b"II*\x00",
    ".tif": b"II*\x00",
    ".docx": b"PK",
    ".pptx": b"PK",
    ".xlsx": b"PK",
    ".xls": b"\xd0\xcf\x11\xe0",
}


def safe_name(name: str) -> str:
    # keep only basename, strip traversal
    base = os.path.basename(name or "")
    base = base.replace("\x00", "")
    if not base:
        base = "file"
    # sanitize
    out = []
    for ch in base:
        if ch.isalnum() or ch in "._- ":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip()
    return s or "file"


def validate_file(name: str, size: int, head: bytes) -> tuple[bool, str, str]:
    """Return (ok, ext, error)."""
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXT:
        return False, ext, "format tidak didukung"
    if size <= 0:
        return False, ext, "file kosong"
    if size > MAX_FILE_BYTES:
        return False, ext, f"ukuran melebihi {MAX_FILE_BYTES // (1024*1024)} MB"
    # magic check (only where known)
    m = MAGIC.get(ext)
    if m is not None and not head.startswith(m):
        # some formats: tiff little/big endian; accept both
        if ext in (".tiff", ".tif"):
            if not (head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")):
                return False, ext, "magic bytes tidak cocok"
        else:
            # be lenient for text formats
            if ext not in (".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"):
                return False, ext, "magic bytes tidak cocok"
    return True, ext, ""


def validate_batch(files: list) -> tuple[bool, str]:
    if not files:
        return False, "tidak ada file"
    if len(files) > MAX_FILES:
        return False, f"jumlah file melebihi {MAX_FILES}"
    total = sum(f.get("size", 0) for f in files)
    if total > MAX_TOTAL_BYTES:
        return False, f"total ukuran melebihi {MAX_TOTAL_MB} MB"
    return True, ""
