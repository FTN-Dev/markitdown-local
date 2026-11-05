import asyncio
import io
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR, JOB_TTL_MIN, CONVERT_TIMEOUT_S, WORKERS


@dataclass
class Item:
    id: str
    name: str
    ext: str
    status: str = "queued"  # queued|running|done|failed
    error: str | None = None
    converter: str | None = None
    seconds: float | None = None
    out_path: str | None = None
    in_path: str | None = None


@dataclass
class Job:
    id: str
    created: float
    items: list[Item] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.items:
            return "done"
        statuses = {i.status for i in self.items}
        if "running" in statuses or "queued" in statuses:
            if "done" in statuses or "failed" in statuses:
                return "running"
            return "queued" if statuses == {"queued"} else "running"
        if statuses == {"done"}:
            return "done"
        if statuses == {"failed"}:
            return "failed"
        return "done"


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.executor = ProcessPoolExecutor(max_workers=WORKERS)
        self._janitor_started = False

    def start_janitor(self, loop):
        if self._janitor_started:
            return
        self._janitor_started = True
        loop.create_task(self._janitor_loop())

    async def _janitor_loop(self):
        while True:
            await asyncio.sleep(60)
            self.cleanup_old()

    def cleanup_old(self):
        cutoff = time.time() - JOB_TTL_MIN * 60
        with self.lock:
            to_del = [jid for jid, j in self.jobs.items() if j.created < cutoff]
        for jid in to_del:
            self.delete_job(jid)
        # remove orphaned job dirs not tracked in memory
        jobs_root = DATA_DIR / "jobs"
        if jobs_root.exists():
            with self.lock:
                tracked = set(self.jobs.keys())
            for entry in jobs_root.iterdir():
                if entry.is_dir() and entry.name not in tracked:
                    # only remove if old enough
                    try:
                        if time.time() - entry.stat().st_mtime > JOB_TTL_MIN * 60:
                            shutil.rmtree(entry, ignore_errors=True)
                    except Exception:
                        pass
        # best-effort: clear stale temp files in /tmp (files older than TTL)
        try:
            tmp_root = Path("/tmp")
            if tmp_root.exists():
                for entry in tmp_root.iterdir():
                    try:
                        if time.time() - entry.stat().st_mtime > JOB_TTL_MIN * 60:
                            if entry.is_dir():
                                shutil.rmtree(entry, ignore_errors=True)
                            else:
                                entry.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def new_job(self) -> Job:
        jid = uuid.uuid4().hex
        job = Job(id=jid, created=time.time())
        jobdir = DATA_DIR / "jobs" / jid
        (jobdir / "in").mkdir(parents=True, exist_ok=True)
        (jobdir / "out").mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.jobs[jid] = job
        return job

    def get(self, jid: str) -> Job | None:
        with self.lock:
            return self.jobs.get(jid)

    def delete_job(self, jid: str):
        with self.lock:
            self.jobs.pop(jid, None)
        jdir = DATA_DIR / "jobs" / jid
        if jdir.exists():
            shutil.rmtree(jdir, ignore_errors=True)

    def add_item(self, job: Job, item: Item):
        job.items.append(item)

    async def run_item(self, job: Job, item: Item):
        if item.status != "queued":
            return
        item.status = "running"
        t0 = time.time()
        loop = asyncio.get_event_loop()
        try:
            res = await loop.run_in_executor(
                self.executor,
                _convert_one,
                item.in_path,
                item.ext,
                str(DATA_DIR / "jobs" / job.id / "out"),
                item.name,
                CONVERT_TIMEOUT_S,
            )
            item.seconds = round(time.time() - t0, 2)
            if res.get("ok"):
                item.status = "done"
                item.converter = res.get("converter")
                item.out_path = res.get("out_path")
            else:
                item.status = "failed"
                item.error = res.get("error", "konversi gagal")
        except Exception as e:
            item.status = "failed"
            item.error = str(e)[:500]
            item.seconds = round(time.time() - t0, 2)

    def build_zip(self, job: Job) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for it in job.items:
                if it.status == "done" and it.out_path and os.path.exists(it.out_path):
                    arc = os.path.basename(it.out_path)
                    z.write(it.out_path, arc)
                # include assets dir if exists
            outdir = DATA_DIR / "jobs" / job.id / "out"
            assets = outdir / "assets"
            if assets.exists():
                for p in assets.rglob("*"):
                    if p.is_file():
                        z.write(p, str(p.relative_to(outdir)))
        return buf.getvalue()


def _convert_one(in_path, ext, out_dir, original_name, timeout):
    """Runs in worker process."""
    import signal

    def _handler(signum, frame):
        raise TimeoutError("timeout")

    # best-effort timeout via signal (unix)
    try:
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
    except Exception:
        pass

    try:
        try:
            from .router import convert_file
        except Exception:
            from app.router import convert_file
        return convert_file(in_path, ext, out_dir, original_name)
    except TimeoutError:
        return {"ok": False, "error": f"timeout {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass
