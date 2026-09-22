"""Análise de qualidade: roda detectores sobre todos os itens do dataset.

Idempotente: reexecução com mesma config gera mesmos scores; issues antigas
do mesmo detector são substituídas (delete+reinsert por image_id+detector).
"""
from pathlib import Path

from sqlmodel import Session, select

from ..analyzers import quality
from ..config import get_settings
from ..jobs import update_progress
from ..models import ImageIssue, ImageItem, Job
from .paths import item_path


# (issue_type, score_fn, needs_image, threshold_key, comparator)
# comparator: 'below' => issue se score < threshold; 'above' => issue se score > threshold
QUALITY_RULES = [
    ("blur", quality.blur_score, True, "blur_threshold", "below"),
    ("underexposed", lambda img, gray=None: quality.luminance_stats(img, gray)["mean"], True, "dark_threshold", "below"),
    ("overexposed", lambda img, gray=None: quality.luminance_stats(img, gray)["mean"], True, "bright_threshold", "above"),
    ("low_contrast", quality.contrast_score, True, "low_contrast_threshold", "below"),
    ("low_information", quality.entropy_score, True, "low_information_threshold", "below"),
    ("screenshot", lambda img, gray=None: quality.screenshot_score(img, gray)["score"], True, "screenshot_threshold", "above"),
]


def _thresholds(session: Session, dataset_id: str) -> dict:
    from ..models import Dataset
    ds = session.get(Dataset, dataset_id)
    overrides = ds.thresholds_json if ds and ds.thresholds_json else {}
    s = get_settings()
    return {k: overrides.get(k, getattr(s, k)) for k in (
        "blur_threshold", "dark_threshold", "bright_threshold",
        "low_contrast_threshold", "low_information_threshold", "screenshot_threshold",
        "min_resolution", "aspect_limit")}


def run_quality(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    th = _thresholds(session, dataset_id)
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()

    # limpa issues anteriores dos detectors desta rodada p/ idempotência
    detectors = {"quality-rules"}
    for issue in session.exec(select(ImageIssue).where(
            ImageIssue.dataset_id == dataset_id)).all():
        if issue.detector_name in detectors:
            session.delete(issue)
    session.commit()

    processed = failed = 0
    total = len(items)
    pending = 0
    from ..jobs import is_cancelled
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            path = item_path(it)
            img, _ = quality.decode_image(path)
            if img is None:
                failed += 1
                continue
            # decodifica 1x: downsample + gray compartilhado por todos os detectores
            img, gray = quality.prepare(img)
            issues = []
            for issue_type, fn, _needs, th_key, cmp in QUALITY_RULES:
                score = fn(img, gray)
                t = th[th_key]
                hit = score < t if cmp == "below" else score > t
                if hit:
                    issues.append((issue_type, score, t))
            # resolução / aspect — sem decodificação (dims reais do item)
            if it.width < th["min_resolution"] or it.height < th["min_resolution"]:
                issues.append(("small_resolution", float(min(it.width, it.height)), float(th["min_resolution"])))
            ratio = max(it.width, it.height) / max(1, min(it.width, it.height))
            if ratio > th["aspect_limit"]:
                issues.append(("odd_aspect_ratio", ratio, float(th["aspect_limit"])))
            if quality.is_grayscale(img):
                issues.append(("grayscale", 1.0, 0.0))
            for issue_type, score, t in issues:
                session.add(ImageIssue(
                    image_id=it.id, dataset_id=dataset_id, issue_type=issue_type,
                    score=score, threshold=t, detector_name="quality-rules",
                    detector_version=quality.DETECTOR_VERSION,
                    evidence_json={"rule": issue_type},
                ))
            processed += 1
        except Exception:  # noqa: BLE001 — item falha não derruba job
            failed += 1
        # commit em lote: 1 fsync WAL a cada 50 itens, não 2 por item
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))
