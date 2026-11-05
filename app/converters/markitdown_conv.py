import os
from pathlib import Path


def convert_markitdown(in_path: str, out_dir: str, original_name: str) -> dict:
    try:
        from markitdown import MarkItDown
    except Exception as e:
        return {"ok": False, "error": f"markitdown import error: {e}"}

    md = MarkItDown()
    try:
        # prefer convert_local to avoid URL/SSRF handling
        if hasattr(md, "convert_local"):
            result = md.convert_local(in_path)
        else:
            result = md.convert(in_path)
    except Exception as e:
        # fallback
        try:
            result = md.convert(in_path)
        except Exception as e2:
            return {"ok": False, "error": str(e2)[:500]}

    text = getattr(result, "text_content", None)
    if text is None:
        text = str(result)

    base = Path(original_name).stem
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip() or "output"
    out_path = os.path.join(out_dir, safe + ".md")
    # avoid collision
    i = 1
    while os.path.exists(out_path):
        out_path = os.path.join(out_dir, f"{safe}_{i}.md")
        i += 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    return {"ok": True, "converter": "markitdown", "out_path": out_path}
