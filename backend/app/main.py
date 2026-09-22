"""API completa: datasets, imports/jobs, items, thumbnails, issues, duplicates,
labels, decisions, versions, search semântica, clusters, export."""
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat
from sqlmodel import Session, func, or_, select

from . import jobs as jobrunner
from .services import versions_service
from .config import get_settings, public_provider_settings, update_provider_settings
from .analyzers import quality
from .db import engine, get_session, init_db
from .exporters.exporter import export
from .models import (Caption, Dataset, DatasetVersion, DuplicateGroup,
                      ExportRecord, ImageIssue, ImageItem, Job, Label, ReviewDecision)
from .services import (ai_service, dedup_service, embeddings_service, ingest,
                        quality_service, versions_service)
from .services.paths import item_path
from . import model_catalog, plugin_runtime
from . import providers  # noqa: F401 — registra os builtin plugins

app = FastAPI(title="Images Dataset Studio", version="0.1.0")

app.on_event("startup")(init_db)


@app.on_event("startup")
def _reconcile_stuck_jobs():
    """Jobs 'running' de um processo anterior morrem com o servidor; sem isso
    ficam presos para sempre na UI."""
    with Session(engine) as session:
        stmt = (select(Job)
                .where(Job.status.in_(("queued", "running"))))
        stuck = session.exec(stmt).all()
        for j in stuck:
            j.status = "failed"
            j.error_summary = "server restarted while job was in flight"
            j.finished_at = datetime.now(UTC)
            session.add(j)
        session.commit()


# ---------- helpers de segurança ----------

def _safe_path(p: Path, s) -> bool:
    """Thumbnail/raw: precisa ficar sob data_dir. source_uri: precisa existir e não ser
    path de sistema sensível. (source_uri aponta pra arquivo ORIGINAL do usuário —
    é feature, ler ele é permitido; bloqueamos só os óbvios de sistema.)"""
    rp = p.resolve()
    under_data = rp.is_relative_to(s.data_dir.resolve())
    if under_data:
        return True
    forbidden = ("/etc", "/System", "/private/etc", "/usr/bin", "/bin", "/sbin", "Library/Keychains")
    if rp.is_file() and not any(rp.is_relative_to(Path(f)) for f in forbidden):
        return True
    return rp.is_file() and rp.suffix.lower() in quality.IMAGE_EXTENSIONS


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- schemas ----------

class DatasetIn(BaseModel):
    name: str
    description: str = ""
    folder: Optional[str] = None
    license: str = "unknown"
    license_evidence_uri: str = ""


class ImportIn(BaseModel):
    paths: list[str] = []
    zips: list[str] = []


class LabelIn(BaseModel):
    label_type: str = "classification"
    category: str
    geometry: dict[str, Any] = {}
    value: dict[str, Any] = {}
    source_type: str = "human"
    confidence: Optional[float] = None
    supersedes_id: Optional[str] = None


class LabelPatch(BaseModel):
    category: Optional[str] = None

class DecisionIn(BaseModel):
    # 'pending' só é legítimo via undo/restore (voltar ao estado indeciso);
    # qualquer cliente curadorial manda os 4 valores do dicionário fixo.
    decision: Literal["keep", "review", "quarantine", "reject", "restore", "pending"]
    reason: str = ""
    reviewer: str = "local"


class VersionIn(BaseModel):
    description: str = ""


class TagIn(BaseModel):
    tags: list[str]


class ExportIn(BaseModel):
    fmt: Literal['imagefolder', 'coco', 'yolo', 'manifest', 'parquet'] = "imagefolder"
    version_id: Optional[str] = None


class IssueAckIn(BaseModel):
    status: Literal["acknowledged", "dismissed"] = "acknowledged"
    reviewer: str = "local"


# ---------- datasets ----------

@app.post("/api/datasets", status_code=201)
def create_dataset(body: DatasetIn, session: Session = Depends(get_session)):
    ds = Dataset(**{k: v for k, v in body.model_dump().items() if v is not None and k not in ("folder",)})
    if body.folder:
        from pathlib import Path
        p = Path(body.folder).resolve()
        p.mkdir(parents=True, exist_ok=True)
        ds.source_uri = str(p)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


@app.get("/api/datasets")
def list_datasets(session: Session = Depends(get_session)):
    dss = session.exec(select(Dataset)).all()
    out = []
    for ds in dss:
        # GROUP BY no SQL: sem N+1 (antes carregava TODOS os itens de cada dataset)
        rows = session.exec(select(ImageItem.decision_status, func.count())
                            .where(ImageItem.dataset_id == ds.id)
                            .group_by(ImageItem.decision_status)).all()
        counts = {"total": 0, "keep": 0, "review": 0, "quarantine": 0, "reject": 0, "restore": 0}
        for status, n in rows:
            counts["total"] += n
            if status in counts:
                counts[status] = n
        issue_open = session.exec(select(func.count()).select_from(ImageIssue).where(
            ImageIssue.dataset_id == ds.id, ImageIssue.status == "open")).one()
        running_stmt = select(Job.id).where(
            Job.dataset_id == ds.id,
            Job.status.in_(("queued", "running")))
        running = [j.id for j in session.exec(running_stmt).all()]
        out.append({**ds.model_dump(), "item_counts": counts,
                   "open_issues": issue_open, "running_jobs": running})
    return out


@app.get("/api/datasets/{ds_id}")
def get_dataset(ds_id: str, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    # mesmas contagens de list_datasets — evita fetch de 1000 itens no frontend
    stmt = (select(ImageItem.decision_status, func.count())
             .where(ImageItem.dataset_id == ds.id)
             .group_by(ImageItem.decision_status))
    rows = session.exec(stmt).all()
    counts = {"total": 0, "keep": 0, "review": 0, "quarantine": 0, "reject": 0, "restore": 0}
    for status, n in rows:
        counts["total"] += n
        if status in counts:
            counts[status] = n
    stmt_i = (select(func.count()).select_from(ImageIssue)
              .where(ImageIssue.dataset_id == ds.id, ImageIssue.status == "open"))
    issue_open = session.exec(stmt_i).one()
    stmt_u = (select(func.count()).select_from(ImageItem)
              .where(ImageItem.dataset_id == ds.id, ImageItem.license == "unknown",
                      ImageItem.decision_status.in_(("keep", "restore"))))
    unknown_license = session.exec(stmt_u).one()
    return {**ds.model_dump(), "item_counts": counts, "open_issues": issue_open,
            "unknown_license": unknown_license}

@app.patch("/api/datasets/{ds_id}")
def patch_dataset(ds_id: str, body: dict, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    # null não pode descer ao DB (NOT NULL); chaves desconhecidas são ignoradas
    for k in ("name", "description", "license", "license_evidence_uri", "license_policy", "thresholds_json"):
        v = body.get(k)
        if k in body and v is not None:
            setattr(ds, k, v)
    if ds.license_policy not in ("permissive", "strict"):
        raise HTTPException(400, "license_policy must be permissive|strict")
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


# ---------- imports & jobs ----------

@app.post("/api/datasets/{ds_id}/imports", status_code=202)
def start_import(ds_id: str, body: ImportIn, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    for p in body.paths + body.zips:
        if not Path(p).exists():
            raise HTTPException(400, f"path not found: {p}")
    job = Job(type="ingest", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ingest.run_ingest, body.model_dump())
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/jobs/{job_type}", status_code=202)
def start_job(ds_id: str, job_type: str, body: dict | None = None, session: Session = Depends(get_session)):
    from .services import importers
    body = body or {}
    cfg = {k: (str(v) if k == "folder" else v) for k, v in body.items()
           if k in ("folder", "urls", "urls_file", "urls_json", "model_id", "automation",
                      "confidence", "preview", "prompt", "prefix", "suffix",
                      "separator", "template", "item_ids")}
    model_capabilities = {
        "embeddings": "embedding", "preannotate": "preannotation",
        "pii_scan": "pii", "ocr": "ocr", "detection": "detection",
        "segmentation": "segmentation", "caption": "captioning",
    }
    requested_model = body.get("model_id") or model_catalog.active_model(model_capabilities.get(job_type, ""))
    if requested_model:
        selected = next((m for m in model_catalog.list_catalog() if m["id"] == requested_model), None)
        if selected is None:
            raise HTTPException(404, "model not found")
        if not selected["installed"]:
            raise HTTPException(409, "selected model is not installed")
        cfg["model_id"] = requested_model
        cfg["model"] = {key: selected[key] for key in ("id", "name", "capability", "revision", "runtime", "license", "sha256") if key in selected}
    fn = {"quality": quality_service.run_quality,
          "dedup_exact": dedup_service.run_exact_dedup,
          "dedup_phash": dedup_service.run_phash_dedup,
          "embeddings": embeddings_service.run_embeddings,
          "preannotate": ai_service.run_preannotate,
          "pii_scan": ai_service.run_pii_scan,
          "ocr": ai_service.run_ocr,
          "detection": ai_service.run_detection,
          "segmentation": ai_service.run_segmentation,
          "caption": ai_service.run_caption,
          "label_issues": ai_service.run_label_issues,
          "import_imagefolder": importers.run_import_imagefolder,
          "import_yolo": importers.run_import_yolo,
          "import_coco": importers.run_import_coco,
          "import_voc": importers.run_import_voc,
          "import_imagenet": importers.run_import_imagenet,
          "import_urls": importers.run_import_urls,
          "retry_errors": importers.run_retry_errors}.get(job_type)
    if fn is None:
        raise HTTPException(400, f"unknown job type: {job_type}")
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    if job_type.startswith("import_") and job_type != "import_urls" and not cfg.get("folder"):
        raise HTTPException(400, "import_* jobs exigem 'folder'")
    if job_type == "import_urls" and not (body.get("urls") or body.get("urls_file") or body.get("urls_json")):
        raise HTTPException(400, "import_urls exige 'urls', 'urls_file' ou 'urls_json'")
    job = Job(type=job_type, dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, fn, cfg)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobrunner.cancel_job(job_id):
        raise HTTPException(409, "job not running")
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/automation/history")
def automation_history(limit: int = 50, session: Session = Depends(get_session)):
    rows = session.exec(select(ReviewDecision).where(
        ReviewDecision.reason.like("automation:%")).order_by(
            ReviewDecision.created_at.desc()).limit(min(limit, 200))).all()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = row.reason.split(":", 1)[1]
        entry = grouped.setdefault(job_id, {"job_id": job_id, "actions": 0, "created_at": row.created_at})
        entry["actions"] += 1
    return list(grouped.values())


@app.post("/api/automation/{job_id}/undo")
def undo_automation(job_id: str, session: Session = Depends(get_session)):
    decisions = session.exec(select(ReviewDecision).where(
        ReviewDecision.reason == f"automation:{job_id}")).all()
    if not decisions:
        raise HTTPException(404, "automation run not found")
    restored = 0
    for decision in decisions:
        if decision.target_type == "label":
            label = session.get(Label, decision.target_id)
            if label is not None and label.status == "approved":
                label.status = "pending"
                session.add(label)
                restored += 1
        elif decision.target_type == "item":
            item = session.get(ImageItem, decision.target_id)
            if item is not None:
                previous = decision.comment.removeprefix("previous_decision:")
                item.decision_status = previous or "keep"
                item.quarantine_reason = ""
                session.add(item)
                restored += 1
    session.add(ReviewDecision(
        target_type="job", target_id=job_id, decision="restore",
        reason=f"automation-undo:{job_id}", comment=f"restored:{restored}"))
    session.commit()
    return {"job_id": job_id, "restored": restored}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/datasets/{ds_id}/jobs")
def list_jobs(ds_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Job).where(Job.dataset_id == ds_id)).all()


# ---------- items ----------

@app.get("/api/datasets/{ds_id}/items")
def list_items(ds_id: str, q: str = "", status: str = "", issue: str = "",
               min_width: int = 0, tag: str = "", license: str = "",
               label: str = "", order: str = "", queue: str = "",
               limit: int = 1000, offset: int = 0,
               session: Session = Depends(get_session)):
    from .services.filters import count_items, page_items
    f = {"q": q, "status": status, "issue": issue, "min_width": min_width,
         "tag": tag, "license": license, "label": label, "order": order,
         "queue": queue}
    total = count_items(session, ds_id, f)
    items = page_items(session, ds_id, f, max(1, min(limit, 5000)), max(0, offset))
    return JSONResponse(content=jsonable_encoder(items),
                        headers={"X-Total-Count": str(total)})


@app.get("/api/items/{item_id}")
def get_item(item_id: str, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    issues = session.exec(select(ImageIssue).where(ImageIssue.image_id == item_id)).all()
    labels = session.exec(select(Label).where(Label.image_id == item_id)).all()
    caption = session.exec(select(Caption).where(
        Caption.image_id == item_id,
        Caption.superseded_at.is_(None))).first()
    return {"item": it, "issues": issues, "labels": labels, "caption": caption}


@app.get("/api/items/{item_id}/thumbnail")
def get_thumbnail(item_id: str, if_none_match: str | None = Header(None),
                 session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    s = get_settings()
    thumb = s.data_dir / it.storage_uri if it.storage_uri else s.raw_dir / it.dataset_id / f"{it.id}"
    if not thumb.exists():
        thumb = item_path(it)
    if not _safe_path(thumb, s):
        raise HTTPException(403, "path fora do dataset")
    etag = f'"{item_id}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(thumb, media_type="image/jpeg",
                        headers={"ETag": etag, "Cache-Control": "private, max-age=86400"})


@app.patch("/api/items/{item_id}/decision")
def set_decision(item_id: str, body: DecisionIn, session: Session = Depends(get_session)):
    it = versions_service.set_decision(session, item_id, body.decision, body.reason, body.reviewer)
    return it


@app.patch("/api/items/{item_id}/tags")
def set_tags(item_id: str, body: TagIn, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    it.tags_json = body.tags
    session.add(it)
    session.commit()
    session.refresh(it)
    return it.model_dump()

@app.get("/api/items/{item_id}/file")
def get_file(item_id: str, size: int = Query(ge=0, le=4096, default=0), if_none_match: str | None = Header(None),
           session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    p = item_path(it)
    if not _safe_path(p, get_settings()):
        raise HTTPException(403, "path inacessível")
    etag = f'"{item_id}:{it.content_hash_sha256}:{size}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    if 0 < size < min(it.width or size, it.height or size):
        from PIL import Image as PILImage
        cache = get_settings().derived_dir / it.dataset_id / f"preview-{it.id}-{size}.jpg"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            im = PILImage.open(p).convert("RGB")
            im.thumbnail((size, size))
            im.save(cache, "JPEG", quality=85)
        return FileResponse(cache, media_type="image/jpeg",
                            headers={"ETag": etag, "Cache-Control": "private, max-age=86400"})
    return FileResponse(p, media_type=it.mime_type or "application/octet-stream",
                        headers={"ETag": etag})


# ---------- issues ----------

@app.get("/api/datasets/{ds_id}/issues")
def list_issues(ds_id: str, issue_type: str = "", status: str = "open",
                order_by_score: bool = True, limit: int = 500,
                session: Session = Depends(get_session)):
    stmt = select(ImageIssue).where(ImageIssue.dataset_id == ds_id)
    if status:
        stmt = stmt.where(ImageIssue.status == status)
    if issue_type:
        stmt = stmt.where(ImageIssue.issue_type == issue_type)
    issues = session.exec(stmt.limit(limit)).all()
    if order_by_score:
        issues.sort(key=lambda i: -i.score)
    # dados do item inline — o frontend não precisa de um fetch de 1000 itens
    _ids = list({i.image_id for i in issues})
    _by = {}
    if _ids:
        for it in session.exec(select(ImageItem).where(ImageItem.id.in_(_ids))).all():
            _by[it.id] = it
    return [{**iss.model_dump(),
             "original_filename": _by[iss.image_id].original_filename if iss.image_id in _by else None,
             "relative_path": _by[iss.image_id].relative_path if iss.image_id in _by else None,
             "width": _by[iss.image_id].width if iss.image_id in _by else None,
             "height": _by[iss.image_id].height if iss.image_id in _by else None,
             "byte_size": _by[iss.image_id].byte_size if iss.image_id in _by else None,
             "mime_type": _by[iss.image_id].mime_type if iss.image_id in _by else None,
             "ingest_status": _by[iss.image_id].ingest_status if iss.image_id in _by else None}
            for iss in issues]


@app.patch("/api/issues/{issue_id}/ack")
def ack_issue(issue_id: str, body: IssueAckIn, session: Session = Depends(get_session)):
    iss = session.get(ImageIssue, issue_id)
    if iss is None:
        raise HTTPException(404, "issue not found")
    iss.status = body.status
    iss.reviewed_by = body.reviewer
    from datetime import UTC, datetime
    iss.reviewed_at = datetime.now(UTC)
    session.add(iss)
    session.commit()
    return iss


# ---------- duplicates ----------

@app.get("/api/datasets/{ds_id}/duplicates")
def list_duplicates(ds_id: str, method: str = "", session: Session = Depends(get_session)):
    stmt = select(DuplicateGroup).where(DuplicateGroup.dataset_id == ds_id)
    if method:
        stmt = stmt.where(DuplicateGroup.method == method)
    groups = session.exec(stmt).all()
    out = []
    for g in groups:
        from .models import DuplicateMember
        members = session.exec(select(DuplicateMember).where(DuplicateMember.group_id == g.id)).all()
        # dados do item inline por membro — evita fetch de 1000 itens no frontend
        _mids = [m.image_id for m in members]
        _mby = {it.id: it for it in session.exec(select(ImageItem).where(ImageItem.id.in_(_mids))).all()} if _mids else {}
        out.append({"group": g.model_dump(), "members": [
            {**m.model_dump(),
             "original_filename": _mby[m.image_id].original_filename if m.image_id in _mby else None,
             "relative_path": _mby[m.image_id].relative_path if m.image_id in _mby else None,
             "width": _mby[m.image_id].width if m.image_id in _mby else None,
             "height": _mby[m.image_id].height if m.image_id in _mby else None,
             "byte_size": _mby[m.image_id].byte_size if m.image_id in _mby else None,
             "mime_type": _mby[m.image_id].mime_type if m.image_id in _mby else None,
             "ingest_status": _mby[m.image_id].ingest_status if m.image_id in _mby else None}
            for m in members]})
    return out


# ---------- labels ----------

@app.post("/api/items/{item_id}/labels", status_code=201)
def add_label(item_id: str, body: LabelIn, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    lb = Label(image_id=item_id, label_type=body.label_type, category=body.category,
               geometry_json=body.geometry, value_json=body.value,
               source_type=body.source_type, confidence=body.confidence,
               supersedes_id=body.supersedes_id, status="approved" if body.source_type == "human" else "pending")
    if body.supersedes_id:
        old = session.get(Label, body.supersedes_id)
        if old:
            from datetime import UTC, datetime
            old.superseded_at = datetime.now(UTC)
            session.add(old)
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb

@app.patch("/api/labels/{label_id}")
def patch_label(label_id: str, body: LabelPatch, session: Session = Depends(get_session)):
    lb = session.get(Label, label_id)
    if lb is None:
        raise HTTPException(404, "label not found")
    if body.category is not None:
        category = body.category.strip()
        if not category:
            raise HTTPException(400, "category cannot be empty")
        lb.category = category
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


@app.patch("/api/labels/{label_id}/review")
def review_label(label_id: str, body: dict, session: Session = Depends(get_session)):
    lb = session.get(Label, label_id)
    if lb is None:
        raise HTTPException(404, "label not found")
    new_status = body.get("status")
    if new_status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be approved|rejected")
    lb.status = new_status
    session.add(lb)
    session.add(ReviewDecision(target_type="label", target_id=label_id,
                               reviewer_id=body.get("reviewer", "local"),
                               decision=new_status, comment=body.get("comment", "")))
    session.commit()
    return lb


# ---------- versions ----------

@app.post("/api/datasets/{ds_id}/versions", status_code=201)
def create_version(ds_id: str, body: VersionIn, session: Session = Depends(get_session)):
    return versions_service.create_version(session, ds_id, body.description)


@app.get("/api/datasets/{ds_id}/versions")
def list_versions(ds_id: str, session: Session = Depends(get_session)):
    return session.exec(select(DatasetVersion).where(
        DatasetVersion.dataset_id == ds_id)).all()


@app.get("/api/datasets/{ds_id}/versions/diff")
def version_diff(ds_id: str, old: str, new: str, session: Session = Depends(get_session)):
    return versions_service.diff_versions(session, ds_id, old, new)


@app.post("/api/datasets/{ds_id}/versions/{version_id}/restore")
def restore_version(ds_id: str, version_id: str, session: Session = Depends(get_session)):
    v = session.get(DatasetVersion, version_id)
    if v is None or v.dataset_id != ds_id:
        raise HTTPException(404, "version not found")
    keep_ids = {e["item_id"] for e in v.snapshot_json}
    for it in session.exec(select(ImageItem).where(ImageItem.dataset_id == ds_id)).all():
        want = "keep" if it.id in keep_ids else "quarantine"
        if it.decision_status in ("keep", "restore", "quarantine"):
            it.decision_status = want
            session.add(it)
    ds = session.get(Dataset, ds_id)
    assert ds is not None
    ds.current_version_id = version_id
    session.add(ds)
    from .models import ReviewDecision
    session.add(ReviewDecision(
        target_type="dataset", target_id=ds_id,
        reviewer_id="local-operator", decision="restore",
        reason=f"restore da versão {version_id[:8]} ({v.description[:40]})"))
    session.commit()
    return {"restored_version": version_id}


# ---------- semantic search & clusters ----------

@app.get("/api/datasets/{ds_id}/clusters")
def get_clusters(ds_id: str, k: int = 8, session: Session = Depends(get_session)):
    try:
        return embeddings_service.clusters(session, ds_id, k)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc


# ---------- derive / merge / split ----------

class DeriveIn(BaseModel):
    name: str
    description: str = ""
    filters: dict[str, Any] = {}


class MergeIn(BaseModel):
    dataset_ids: list[str]
    name: str


class SplitIn(BaseModel):
    ratios: list[PositiveFloat] = Field(min_length=1)
    seed: int = 0


@app.post("/api/datasets/{ds_id}/derive", status_code=201)
def derive_dataset(ds_id: str, body: DeriveIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.derive(session, ds_id, body.name, body.description, body.filters)


@app.post("/api/datasets/merge", status_code=201)
def merge_datasets(body: MergeIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.merge(session, body.dataset_ids, body.name)


@app.post("/api/datasets/{ds_id}/split", status_code=201)
def split_dataset(ds_id: str, body: SplitIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.split(session, ds_id, body.ratios, body.seed)


# ---------- license por item ----------

@app.patch("/api/items/{item_id}/license")
def set_item_license(item_id: str, body: dict, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    it.license = str(body.get("license", "unknown"))
    it.license_evidence_uri = str(body.get("license_evidence_uri", ""))
    session.add(it)
    session.commit()
    session.refresh(it)
    return it.model_dump()


# ---------- captions (per-image training caption) ----------

class CaptionIn(BaseModel):
    text: str
    status: str = "approved"  # approved | pending | rejected



@app.get("/api/items/{item_id}/caption")
def get_caption(item_id: str, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    cap = session.exec(select(Caption).where(
        Caption.image_id == item_id,
        Caption.superseded_at.is_(None))).first()
    return cap if cap else {}


@app.patch("/api/items/{item_id}/caption")
def set_caption(item_id: str, body: CaptionIn, session: Session = Depends(get_session)):
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    from datetime import UTC, datetime
    for old in session.exec(select(Caption).where(
            Caption.image_id == item_id,
            Caption.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)
    cap = Caption(image_id=item_id, text=body.text.strip(),
                   source_type="human", status=body.status)
    session.add(cap)
    session.commit()
    session.refresh(cap)
    return cap


@app.patch("/api/captions/{caption_id}/review")
def review_caption(caption_id: str, body: dict, session: Session = Depends(get_session)):
    cap = session.get(Caption, caption_id)
    if cap is None:
        raise HTTPException(404, "caption not found")
    status = str(body.get("status", ""))
    if status not in ("approved", "pending", "rejected"):
        raise HTTPException(400, "status must be approved | pending | rejected")
    cap.status = status
    session.add(cap)
    session.commit()
    session.refresh(cap)
    return cap



# ---------- providers (plugins): status real + execução via job ----------

@app.get("/api/providers")
def providers_status():
    """Estado real de cada provider registrado, por escopo — nunca finge disponibilidade."""
    from .providers.base import status
    return status()
@app.get("/api/provider-settings")
def provider_settings():
    """Safe provider configuration; API keys are never returned."""
    return public_provider_settings()


@app.patch("/api/provider-settings")
def patch_provider_settings(body: dict):
    return update_provider_settings(body)


# ---------- optional model/plugin catalog ----------

@app.get("/api/model-catalog")
def model_catalog_status():
    state = model_catalog.read_settings()
    return {"models": model_catalog.list_catalog(), "plugins": model_catalog.plugins(), "automation": state.get("automation", {})}


@app.post("/api/models/{model_id}/install", status_code=202)
def install_model(model_id: str, body: dict | None = None):
    body = body or {}
    try:
        return model_catalog.install_model(
            model_id, str(body.get("source", "")), str(body.get("sha256", "")),
            license_ack=bool(body.get("license_ack", False)))
    except KeyError as exc:
        raise HTTPException(404, "model not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/models/{model_id}/uninstall")
def uninstall_model(model_id: str):
    try:
        return model_catalog.uninstall_model(model_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/models/{model_id}/active")
def activate_model(model_id: str, body: dict):
    try:
        return model_catalog.set_active(str(body.get("capability", "")), model_id)
    except KeyError as exc:
        raise HTTPException(404, "model not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/model-automation/{capability}")
def update_model_automation(capability: str, body: dict):
    return model_catalog.set_automation(
        capability, bool(body.get("enabled", False)),
        float(body.get("confidence", 0.95)),
        bool(body.get("preview", True)),
        bool(body.get("auto_quarantine", False)))


@app.post("/api/plugins/install", status_code=201)
def install_plugin(body: dict):
    try:
        return model_catalog.install_plugin(str(body.get("path", "")))
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post("/api/plugins/{plugin_id}/uninstall")
def uninstall_plugin(plugin_id: str):
    try:
        return model_catalog.uninstall_plugin(plugin_id)
    except KeyError as exc:
        raise HTTPException(404, "plugin not found") from exc

@app.post("/api/plugins/{plugin_id}/invoke")
def invoke_plugin(plugin_id: str, body: dict):
    try:
        return plugin_runtime.invoke(plugin_id, str(body.get("capability", "")),
                                     body.get("payload", {}), int(body.get("timeout", 600)))
    except plugin_runtime.PluginError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/datasets/{ds_id}/preannotate", status_code=202)
def preannotate(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="preannotate", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_preannotate, body or {})
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/label-issues", status_code=202)
def label_issues(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="label_issues", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_label_issues, body or {})
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/pii-scan", status_code=202)
def pii_scan(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="pii_scan", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_pii_scan, body or {})
    return {"job_id": job_id, "status": "queued"}


# ---------- export ----------

@app.post("/api/datasets/{ds_id}/export")
def export_dataset(ds_id: str, body: ExportIn, session: Session = Depends(get_session)):
    try:
        return export(session, ds_id, body.fmt, body.version_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"export failed: {exc}") from exc


@app.get("/api/datasets/{ds_id}/exports")
def list_exports(ds_id: str, fmt: str = "", session: Session = Depends(get_session)):
    """Histórico de exportações do dataset (ledger em DB)."""
    stmt = (select(ExportRecord).where(ExportRecord.dataset_id == ds_id)
             .order_by(ExportRecord.created_at.desc()))
    if fmt:
        stmt = stmt.where(ExportRecord.fmt == fmt)
    recs = session.exec(stmt).all()
    return [{"id": r.id, "fmt": r.fmt, "version_id": r.version_id or "",
             "path": r.path, "item_count": r.item_count,
             "created_at": r.created_at.isoformat()} for r in recs]

# ---------- wave-3 endpoints ----------

@app.patch("/api/duplicates/groups/{group_id}/canonical/{item_id}")
def swap_canonical(group_id: str, item_id: str, session: Session = Depends(get_session)):
    """Fase 4.1.5: trocar o canônico de um grupo de duplicatas."""
    try:
        return dedup_service.swap_canonical(session, group_id, item_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class DeriveFromIn(BaseModel):
    name: str
    item_ids: list[str] = []
    group_id: str = ""                # grupo de duplicatas => dataset derivado
    cluster_index: int = -1          # cluster K => dataset derivado
    outliers: bool = False            # outliers => dataset derivado
    k: int = 8


@app.post("/api/datasets/{ds_id}/derive-from", status_code=201)
def derive_from(ds_id: str, body: DeriveFromIn, session: Session = Depends(get_session)):
    """Fase 5.4.5: derivar dataset de grupo de duplicatas, cluster ou outliers."""
    from .models import DuplicateMember
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    ids = body.item_ids
    label = ""
    if body.group_id:
        ids = [m.image_id for m in session.exec(select(DuplicateMember).where(
            DuplicateMember.group_id == body.group_id)).all()]
        label = f"dup-group {body.group_id[:8]}"
    elif body.outliers or body.cluster_index >= 0:
        cl = embeddings_service.clusters(session, ds_id, body.k)
        if body.outliers:
            ids = [o["image_id"] for o in cl.get("outliers", [])]
            label = "outliers"
        elif body.cluster_index < len(cl.get("clusters", [])):
            ids = [m for m in cl["clusters"][body.cluster_index]["members"]]
            label = f"cluster {body.cluster_index}"
    if not ids:
        raise HTTPException(400, "nenhum item para derivar (especifique item_ids, group_id, cluster_index ou outliers)")
    out = dedup_service.derive_from_items(session, body.name, ds_id, ids, label)
    out["note"] = label
    return out


@app.get("/api/datasets/{ds_id}/search")
def semantic_search2(ds_id: str, q: str = "", image_id: str = "",
                     limit: int = 50, status: str = "", license: str = "",
                     tag: str = "", issue: str = "",
                     session: Session = Depends(get_session)):
    """Fase 5.3.5: busca semântica combinada com filtros de metadata."""
    if not q and not image_id:
        raise HTTPException(400, "provide q (text) or image_id")
    filters = {k: v for k, v in {"status": status, "license": license,
                               "tag": tag, "issue": issue}.items() if v}
    try:
        return embeddings_service.semantic_search(session, ds_id, q,
                                               "text" if q else "image",
                                               image_id, limit, filters or None)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc


@app.get("/api/datasets/{ds_id}/items-by-label")
def items_by_label(ds_id: str, category: str = "", label_type: str = "",
                   session: Session = Depends(get_session)):
    """Fase 5.2: busca por label (categoria) — items com label aprovada."""
    from .models import Label
    stmt = select(Label.image_id, Label.category, Label.label_type, Label.status).where(
        Label.status == "approved")
    rows = session.exec(stmt).all()
    by_cat: dict[str, list[str]] = {}
    for iid, cat, ltype, _st in rows:
        item = session.get(ImageItem, iid)
        if item is None or item.dataset_id != ds_id:
            continue
        if category and cat != category:
            continue
        if label_type and ltype != label_type:
            continue
        by_cat.setdefault(cat, []).append(iid)
    return {"categories": {c: sorted(v) for c, v in by_cat.items()},
            "total": sum(len(v) for v in by_cat.values())}


@app.post("/api/datasets/{ds_id}/redact-pii", status_code=202)
def redact_pii(ds_id: str, session: Session = Depends(get_session)):
    """Fase 9.3.6: blur das regiões possible_pii + versão nova."""
    from .services import redact_service
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="redact_pii", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, redact_service.redact_pii, {"ds_id": ds_id})
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/items/{item_id}/histogram")
def get_histogram(item_id: str, if_none_match: str | None = Header(None),
                 session: Session = Depends(get_session)):
    """Return an RGB histogram preview for the selected image."""
    import io
    it = session.get(ImageItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    etag = f'"{item_id}:hist2"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    hist = (it.exif_json or {}).get("rgb_histogram")
    path = Path(it.source_uri.split(":", 1)[1])
    if hist is None:
        decoded, _ev = quality.decode_image(path)
        if decoded is None:
            raise HTTPException(501, "não foi possível decodificar a imagem")
        prepared, _gray = quality.prepare(decoded)
        hist = quality.color_histogram(prepared)
        it.exif_json = {**(it.exif_json or {}), "rgb_histogram": hist}
        session.add(it)
        session.commit()
    from PIL import Image as PILImage, ImageDraw
    W, H, PAD = 336, 120, 6
    canvas = PILImage.new("RGBA", (W, H), (24, 24, 28, 255))
    guide = ImageDraw.Draw(canvas)
    for fraction in (0.25, 0.5, 0.75):
        x = round(PAD + fraction * (W - PAD * 2))
        guide.line((x, 8, x, H - 8), fill=(255, 255, 255, 28), width=1)
    guide.line((PAD, H - 5, W - PAD, H - 5), fill=(255, 255, 255, 70), width=1)
    peak = max((max(values or [0]) for values in hist.values()), default=1) or 1
    colors = {"red": (224, 92, 88, 115), "green": (111, 190, 138, 115), "blue": (92, 135, 224, 115)}
    lines = {"red": (240, 112, 108, 220), "green": (134, 220, 165, 220), "blue": (112, 158, 240, 220)}
    for channel in ("red", "green", "blue"):
        values = hist.get(channel, [])
        if not values:
            continue
        points = [
            (round(PAD + index * (W - PAD * 2) / max(1, len(values) - 1)),
             round(H - 6 - value / peak * (H - 20)))
            for index, value in enumerate(values)
        ]
        overlay = ImageDraw.Draw(canvas, "RGBA")
        overlay.polygon([(PAD, H - 5), *points, (W - PAD, H - 5)], fill=colors[channel])
        overlay.line(points, fill=lines[channel], width=2)
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"ETag": etag, "Cache-Control": "private, max-age=86400"})


@app.get("/api/datasets/{ds_id}/cover")
def get_cover(ds_id: str, if_none_match: str | None = Header(None),
            session: Session = Depends(get_session)):
    """Capa cacheada; recalcula quando não existe OU ficou mais velha que o dataset
    (decisões/tags mudaram o conteúdo)."""
    import io
    from PIL import Image as PILImage
    import numpy as np
    s = get_settings()
    cache = s.derived_dir / ds_id / "cover.jpg"
    ds = session.get(Dataset, ds_id)
    stale = (ds is not None and cache.exists()
             and cache.stat().st_mtime < ds.updated_at.timestamp())
    if not cache.exists() or stale:
        items = session.exec(select(ImageItem).where(
            ImageItem.dataset_id == ds_id, ImageItem.ingest_status == "done")).all()
        best, best_std = None, -1.0
        for it in items[:60]:
            t = s.data_dir / it.storage_uri if it.storage_uri else s.raw_dir / ds_id / it.id
            if not t.exists():
                continue
            try:
                im = PILImage.open(t).convert("RGB").resize((480, 300))
                value = float(np.asarray(im).std())
                if value > best_std:
                    best, best_std = im, value
            except Exception:  # noqa: BLE001
                continue
        canvas = best if best is not None else PILImage.new("RGB", (480, 300), (22, 23, 27))
        cache.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(cache, "JPEG", quality=82)
    etag = f'"{ds_id}:cover:{cache.stat().st_mtime_ns}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(cache, media_type="image/jpeg",
                        headers={"ETag": etag, "Cache-Control": "private, max-age=3600"})


# ---------- single-process deployment: serve the built frontend ----------
from fastapi.staticfiles import StaticFiles  # noqa: E402

# frontend build ships with the repo; resolve relative to this package
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")