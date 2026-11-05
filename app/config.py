import os
from pathlib import Path

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "50"))
MAX_FILES = int(os.getenv("MAX_FILES", "50"))
MAX_TOTAL_MB = int(os.getenv("MAX_TOTAL_MB", "200"))
WORKERS = int(os.getenv("WORKERS", "2"))
CONVERT_TIMEOUT_S = int(os.getenv("CONVERT_TIMEOUT_S", "120"))
JOB_TTL_MIN = int(os.getenv("JOB_TTL_MIN", "60"))
DOCLING_URL = os.getenv("DOCLING_URL", "").rstrip("/")
VERSION = "0.1.0"

MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
MAX_TOTAL_BYTES = MAX_TOTAL_MB * 1024 * 1024

SUPPORTED_EXT = {
    ".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".json",
    ".xml", ".txt", ".md", ".zip", ".pdf", ".png", ".jpg", ".jpeg",
    ".tiff", ".tif", ".bmp", ".gif",
}

EXT_TO_MIME_HINT = {
    ".pdf": "application/pdf",
}
