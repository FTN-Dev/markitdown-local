import os

from .converters.pdf import convert_pdf
from .converters.markitdown_conv import convert_markitdown

# extensions handled by markitdown directly
MARKITDOWN_EXTS = {
    ".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".json",
    ".xml", ".txt", ".md", ".zip",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"}


def convert_file(in_path: str, ext: str, out_dir: str, original_name: str) -> dict:
    ext = ext.lower()
    if ext == ".pdf":
        return convert_pdf(in_path, out_dir, original_name)
    if ext in MARKITDOWN_EXTS:
        return convert_markitdown(in_path, out_dir, original_name)
    if ext in IMAGE_EXTS:
        from .config import DOCLING_URL
        if DOCLING_URL:
            from .converters.docling_client import convert_via_docling
            return convert_via_docling(in_path, out_dir, original_name)
        return {"ok": False, "error": "Gambar memerlukan OCR (DOCLING_URL tidak aktif)"}
    return {"ok": False, "error": "format tidak didukung"}
