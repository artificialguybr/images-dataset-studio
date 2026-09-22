# Job runner: jobs rodam em threads fora do request HTTP; idempotentes e retomáveis.
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from .db import engine
from .models import Job

_lock = threading.Lock()
# ponytail: two workers keep local inference responsive; make configurable when throughput demands it.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ids-job")
_threads: dict[str, Future] = {}
_cancelled: set[str] = set()


def cancel_job(job_id: str) -> bool:
    """Marca job como cancelado; o worker checa via is_cancelled()."""
    with _lock:
        future = _threads.get(job_id)
        if future is None or future.done():
            return False
        _cancelled.add(job_id)
        future.cancel()
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is not None:
            job.status = "cancelled"
            job.error_summary = "cancelled by user"
            job.finished_at = datetime.now(UTC)
            session.add(job)
            session.commit()
    return True


def is_cancelled(job_id: str) -> bool:
    with _lock:
        return job_id in _cancelled


def _run_job(job_id: str, fn: Callable[[Session, Job], None]) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.add(job)
        session.commit()
    try:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            assert job is not None
            fn(session, job)
            # don't overwrite a cancel that landed while the worker was finishing
            if is_cancelled(job_id):
                return
            job.status = "completed"
            job.finished_at = datetime.now(UTC)
            session.add(job)
            session.commit()
    except Exception as exc:  # noqa: BLE001 — erro vira estado visível do job
        with Session(engine) as session:
            job = session.get(Job, job_id)
            assert job is not None
            if not is_cancelled(job_id):
                job.status = "failed"
            job.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
            job.finished_at = datetime.now(UTC)
            session.add(job)
            session.commit()
    finally:
        with _lock:
            _threads.pop(job_id, None)
            _cancelled.discard(job_id)
def spawn_job(job: Job, fn: Callable[[Session, Job], None], config: dict[str, Any]) -> str:
    """Persiste job e agenda execução no scheduler local."""
    job.config_json = config
    with Session(engine) as session:
        job.status = "queued"
        session.add(job)
        session.commit()
        job_id = job.id
    future = _executor.submit(_run_job, job_id, fn)
    with _lock:
        _threads[job_id] = future
    return job_id


def update_progress(job_id: str, processed: int, failed: int, total: int) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.processed = processed
        job.failed = failed
        job.total = total
        job.progress = (processed / total * 100.0) if total else 100.0
        session.add(job)
        session.commit()


def job_is_alive(job_id: str) -> bool:
    with _lock:
        future = _threads.get(job_id)
    return bool(future and not future.done())
