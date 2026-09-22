"""Ingestão: varre pastas/ZIPs, cria ImageItems, hashes, thumbnails, quality issues.

Idempotente: importação reexecutada pula arquivos já inventariados (por source_uri).
Falha por item não derruba o job; item fica ingest_status=error com mensagem.
"""
import shutil
import zipfile
from pathlib import Path

from PIL import ExifTags, Image
from sqlmodel import Session, select

from ..analyzers import quality
from ..analyzers.dedup import dhash, sha256_file
from ..config import get_settings
from ..jobs import is_cancelled, update_progress
from ..models import Dataset, ImageIssue, ImageItem, Job


def _register(session: Session, dataset_id: str, src: Path, relative: str, source_kind: str) -> ImageItem:
    s = get_settings()
    ds = session.get(Dataset, dataset_id)
    item = ImageItem(
        dataset_id=dataset_id,
        source_uri=f"{source_kind}:{src.resolve()}",
        original_filename=src.name,
        relative_path=relative,
        byte_size=src.stat().st_size,
        license=ds.license if ds else "unknown",
        license_evidence_uri=ds.license_evidence_uri if ds else "",
    )
    img, ev = quality.decode_image(src)
    # EXIF real preservado (nunca no original)
    try:
        exif = img.getexif()
        item.exif_json = {str(ExifTags.TAGS.get(k, k)): str(v)[:200] for k, v in exif.items()} if exif else {}
    except Exception:  # noqa: BLE001
        item.exif_json = {}
    if img is None:
        item.ingest_status = "error"
        item.ingest_error = ev.get("error", "unknown")
        item.exif_json = {"decode_error": item.ingest_error}
        session.add(item)
        session.add(ImageIssue(
            image_id=item.id, dataset_id=dataset_id, issue_type="corrupt_file",
            score=1.0, threshold=0.0, detector_name="pillow-verify",
            detector_version=quality.DETECTOR_VERSION, evidence_json=ev,
        ))
        return item

    item.mime_type = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif",
                      "BMP": "image/bmp", "WEBP": "image/webp", "TIFF": "image/tiff"}.get(img.format, "")
    item.width, item.height = img.size
    item.mode = img.mode
    item.channels = len(img.getbands())
    item.content_hash_sha256 = sha256_file(src)
    item.perceptual_hash = dhash(img)

    # thumbnail (nunca toca o original)
    thumb_dir = s.thumbnails_dir / dataset_id
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{item.id}.jpg"
    rgb = img.convert("RGB")
    rgb.thumbnail((s.thumbnail_size, s.thumbnail_size))
    rgb.save(thumb_path, "JPEG", quality=80)
    item.storage_uri = str(thumb_path.relative_to(s.data_dir))

    # copy bytes into raw/ for durability
    dest_dir = s.raw_dir / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{item.id}{src.suffix.lower()}"
    if not dest.exists():
        shutil.copy2(src, dest)
    item.ingest_status = "done"
    session.add(item)
    return item


def run_ingest(session: Session, job: Job) -> None:
    cfg = job.config_json
    dataset_id = job.dataset_id
    s = get_settings()
    processed = failed = pending = 0

    paths: list[Path] = [Path(p) for p in cfg.get("paths", [])]
    zips: list[Path] = [Path(p) for p in cfg.get("zips", [])]
    extract_roots: list[Path] = []
    for zp in zips:
        # limite anti zip-bomb (1 GiB somado) + rejeita membros com path traversal
        # stable dir per (dataset, zip) — job-scoped dirs would re-import everything on resume
        dest = s.derived_dir / dataset_id / f"zip-{zp.stem}"
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp) as zf:
            limit = 1 << 30  # 1 GiB total
            total = 0
            for info in zf.infolist():
                total += info.file_size
                if total > limit:
                    raise ValueError(f"zip {zp.name} exceeds the {limit}-byte limit")
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"malicious zip member: {info.filename}")
                target = dest / member
                if not target.exists():
                    zf.extract(info, dest)
        extract_roots.append(dest)

    all_files: list[tuple[Path, str, str]] = []  # (path, relative, source_kind)
    for root in paths + extract_roots:
        root = root.resolve()
        if root.is_file() and root.suffix.lower() in quality.IMAGE_EXTENSIONS:
            all_files.append((root, root.name, "local"))
        else:
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.suffix.lower() in quality.IMAGE_EXTENSIONS:
                    all_files.append((f, str(f.relative_to(root)), str(root)))

    existing = {it.source_uri for it in session.exec(
        select(ImageItem).where(ImageItem.dataset_id == dataset_id)).all()}
    todo = [t for t in all_files if f"{t[2]}:{t[0]}" not in existing]
    total = len(todo)
    for src, rel, kind in todo:
        if is_cancelled(job.id):
            job_status_note = "cancelled"
            break
        try:
            _register(session, dataset_id, src, rel, kind)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            it = ImageItem(dataset_id=dataset_id, source_uri=f"{kind}:{src}",
                          original_filename=src.name, relative_path=rel,
                          ingest_status="error", ingest_error=f"{type(exc).__name__}: {exc}"[:500])
            session.add(it)
        # commit em lote: 1 fsync WAL a cada 50 itens, não 2 por item
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed + failed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed + failed, failed, max(total, 1))

    # Zip-extract cleanup: os dirs extraídos são scratch — a durabilidade está em
    # raw/<ds>/<id><ext>. Só removemos um dir quando TODO membro registrado
    # tem cópia raw com bytes idênticos; se qualquer arquivo ficou de fora
    # (erro, cancelamento, raw ausente), o dir permanece — provenância nunca
    # é sacrificada por espaço em disco.
    for root in extract_roots:
        members = [f for f in sorted(root.rglob("*")) if f.is_file()]
        raw_ok = bool(members)
        by_src = {i.source_uri: i for i in session.exec(select(ImageItem).where(
            ImageItem.dataset_id == dataset_id)).all()}
        for f in members:
            it = by_src.get(f"imported:{f}")
            if it is None or it.ingest_status != "done":
                raw_ok = False
                break
            raw_copy = s.raw_dir / dataset_id / f"{it.id}{f.suffix.lower()}"
            if not raw_copy.is_file() or raw_copy.stat().st_size != f.stat().st_size:
                raw_ok = False
                break
        if raw_ok:
            shutil.rmtree(root, ignore_errors=True)
