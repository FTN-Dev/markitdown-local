import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import (
    DATA_DIR, MAX_FILE_MB, MAX_FILES, MAX_TOTAL_MB, VERSION,
    DOCLING_URL, SUPPORTED_EXT,
)
from .validate import validate_file, validate_batch, safe_name
from .jobs import JobManager, Item

app = FastAPI(title="markitdown-local", version=VERSION)
manager = JobManager()


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)


@app.on_event("startup")
async def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "jobs").mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    manager.start_janitor(loop)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": VERSION}


@app.get("/api/formats")
async def formats():
    return {
        "extensions": sorted(SUPPORTED_EXT),
        "ocr_active": bool(DOCLING_URL),
        "docling_url": DOCLING_URL or None,
        "max_file_mb": MAX_FILE_MB,
        "max_files": MAX_FILES,
    }


@app.post("/api/convert")
async def convert(files: list[UploadFile] = File(...), extract_images: bool = Form(False)):
    file_infos = []
    for f in files:
        data = await f.read()
        file_infos.append({"data": data, "name": f.filename or "file", "size": len(data)})

    ok, err = validate_batch([{"size": fi["size"]} for fi in file_infos])
    if not ok:
        raise HTTPException(400, err)

    job = manager.new_job()
    jdir = DATA_DIR / "jobs" / job.id
    (jdir / "in").mkdir(parents=True, exist_ok=True)
    (jdir / "out").mkdir(parents=True, exist_ok=True)

    items_meta = []
    for fi in file_infos:
        name = fi["name"]
        size = fi["size"]
        data = fi["data"]
        head = data[:16]
        okf, ext, errf = validate_file(name, size, head)
        item_id = os.urandom(8).hex()
        if not okf:
            item = Item(id=item_id, name=name, ext=ext, status="failed", error=errf)
            manager.add_item(job, item)
            items_meta.append({"id": item_id, "name": name, "status": "failed", "error": errf})
            continue
        safe = safe_name(name)
        in_name = f"{item_id}{ext}"
        in_path = jdir / "in" / in_name
        with open(in_path, "wb") as fh:
            fh.write(data)
        item = Item(id=item_id, name=name, ext=ext, in_path=str(in_path))
        manager.add_item(job, item)
        items_meta.append({"id": item_id, "name": name, "status": "queued"})

    return JSONResponse({"job_id": job.id, "items": items_meta}, status_code=202)


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    items = []
    for it in job.items:
        items.append({
            "id": it.id,
            "name": it.name,
            "status": it.status,
            "error": it.error,
            "converter": it.converter,
            "seconds": it.seconds,
        })
    return {"id": job.id, "status": job.status, "items": items}


@app.post("/api/jobs/{job_id}/process")
async def process_all(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")

    async def runner():
        for it in list(job.items):
            if it.status == "queued":
                await manager.run_item(job, it)

    asyncio.create_task(runner())
    return {"started": True}


@app.post("/api/jobs/{job_id}/items/{item_id}/process")
async def process_one(job_id: str, item_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    target = None
    for it in job.items:
        if it.id == item_id:
            target = it
            break
    if not target:
        raise HTTPException(404, "item tidak ditemukan")
    if target.status != "queued":
        return {"started": False, "status": target.status}

    async def runner():
        await manager.run_item(job, target)

    asyncio.create_task(runner())
    return {"started": True}


@app.delete("/api/jobs/{job_id}/items/{item_id}")
async def cancel_item(job_id: str, item_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    target = None
    for it in job.items:
        if it.id == item_id:
            target = it
            break
    if not target:
        raise HTTPException(404, "item tidak ditemukan")
    if target.status not in ("queued", "failed"):
        raise HTTPException(400, "item tidak bisa dibatalkan")
    job.items = [it for it in job.items if it.id != item_id]
    if target.in_path and os.path.exists(target.in_path):
        try:
            os.remove(target.in_path)
        except Exception:
            pass
    if target.out_path and os.path.exists(target.out_path):
        try:
            os.remove(target.out_path)
        except Exception:
            pass
    return {"deleted": item_id}


@app.get("/api/jobs/{job_id}/files/{item_id}")
async def job_file(job_id: str, item_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    for it in job.items:
        if it.id == item_id:
            if it.status != "done" or not it.out_path or not os.path.exists(it.out_path):
                raise HTTPException(404, "file belum siap")
            return FileResponse(it.out_path, media_type="text/markdown", filename=os.path.basename(it.out_path))
    raise HTTPException(404, "item tidak ditemukan")


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    data = manager.build_zip(job)
    return Response(content=data, media_type="application/zip",
                   headers={"Content-Disposition": f'attachment; filename="markitdown-{job_id}.zip"'})


@app.delete("/api/jobs/{job_id}")
async def job_delete(job_id: str):
    manager.delete_job(job_id)
    return {"deleted": job_id}


@app.post("/api/convert/sync")
async def convert_sync(file: UploadFile = File(...)):
    data = await file.read()
    name = file.filename or "file"
    head = data[:16]
    okf, ext, errf = validate_file(name, len(data), head)
    if not okf:
        raise HTTPException(400, errf)
    tmpdir = Path(tempfile.mkdtemp(dir=str(DATA_DIR)))
    in_path = tmpdir / ("in" + ext)
    out_dir = tmpdir / "out"
    out_dir.mkdir()
    with open(in_path, "wb") as fh:
        fh.write(data)
    from .router import convert_file
    res = convert_file(str(in_path), ext, str(out_dir), name)
    if not res.get("ok"):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(400, res.get("error", "gagal"))
    with open(res["out_path"], "r", encoding="utf-8") as fh:
        text = fh.read()
    shutil.rmtree(tmpdir, ignore_errors=True)
    return Response(content=text, media_type="text/markdown")


STATIC = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
