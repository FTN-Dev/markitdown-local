import os
from pathlib import Path

import requests

from ..config import DOCLING_URL, CONVERT_TIMEOUT_S


def convert_via_docling(in_path: str, out_dir: str, original_name: str) -> dict:
    if not DOCLING_URL:
        return {"ok": False, "error": "DOCLING_URL tidak di-set"}
    url = DOCLING_URL + "/v1/convert/file"
    try:
        with open(in_path, "rb") as f:
            files = {"files": (os.path.basename(in_path), f)}
            r = requests.post(url, files=files, timeout=CONVERT_TIMEOUT_S)
        if r.status_code != 200:
            return {"ok": False, "error": f"docling HTTP {r.status_code}: {r.text[:300]}"}
        # docling returns markdown in document.md_content or similar; try common fields
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        text = None
        if data:
            # try nested
            doc = data.get("document") or data
            text = doc.get("md_content") or doc.get("markdown") or doc.get("text")
            if text is None and isinstance(data, dict):
                # search
                for v in data.values():
                    if isinstance(v, str) and len(v) > 50:
                        text = v
                        break
        if text is None:
            text = r.text
        base = Path(original_name).stem
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip() or "output"
        out_path = os.path.join(out_dir, safe + ".md")
        i = 1
        while os.path.exists(out_path):
            out_path = os.path.join(out_dir, f"{safe}_{i}.md")
            i += 1
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "converter": "docling", "out_path": out_path}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
