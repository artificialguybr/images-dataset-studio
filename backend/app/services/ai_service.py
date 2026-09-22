"""Pré-anotação por IA e PII — via provider ativo do registro de plugins.

OpenAI Vision: manda a imagem (base64) pedindo boxes/classes em JSON estruturado.
Sugestões salvam como Label source_type=model, status=pending — humano aprova.
PII: mesmo modelo, pergunta sim/não + justificativa; vira ImageIssue.
"""
import base64
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from ..jobs import is_cancelled, update_progress
from ..models import Caption, ImageIssue, ImageItem, Job, Label, ReviewDecision
from .. import model_catalog, plugin_runtime
from ..providers.base import active
from ..providers.cloud import call_vision
PROMPT_PREANN = (
    'List visible objects in this image. Respond ONLY minified JSON: '
    '{"labels":[{"category":"name","bbox":{"x":0,"y":0,"w":0,"h":0}}]}. '
    "bbox in pixels, origin top-left. Empty list if none."
)
PROMPT_PII = (
    "Does this image contain personally identifiable information (faces, license plates, "
    "documents, screens with personal data, addresses, IDs)? "
    'Respond ONLY minified JSON: {"pii":bool,"types":[str],"evidence":str}.'
)


def _item_path(it: ImageItem) -> Path:
    # plugins run with cwd inside their own pack: always hand them absolute paths
    from .paths import item_path
    return item_path(it)



def _validated_bbox(raw: object, item: ImageItem) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("plugin returned a non-object bbox")
    try:
        x, y, w, h = (int(raw[key]) for key in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("plugin returned an invalid bbox") from exc
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > item.width or y + h > item.height:
        raise ValueError("plugin returned a bbox outside image bounds")
    return {"x": x, "y": y, "w": w, "h": h}
def _vision_call(image_path: Path, prompt: str, provider: str, capability: str) -> dict:
    if provider != "openai_vision":
        return call_vision(provider, str(image_path), prompt, capability)
    from ..config import get_settings, provider_model
    s = get_settings()
    req = urllib.request.Request(
        f"{s.openai_base_url.rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": provider_model("openai_vision", capability),
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode()}},
            ]}],
            "temperature": 0,
        }).encode(),
        headers={"content-type": "application/json",
                 "authorization": f"Bearer {s.openai_api_key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    text = out["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0)) if match else {"text": text, "caption": text}


def run_label_issues(session: Session, job: Job) -> None:
    """Cleanlab opcional: precisa de pred_probs externas em config_json['pred_probs']
    + labels existentes. Sem elas => issue 'unavailable' por item, nunca pass."""
    p = active("label_issues")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not ok:
        raise RuntimeError(f"label-issues provider unavailable — {msg}")
    import numpy as np
    from ..models import Label
    dataset_id = job.dataset_id
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()
    cfg = job.config_json
    probs = np.load(cfg["pred_probs_path"]) if cfg.get("pred_probs_path") else None
    labels = np.array([int(next(iter(
        [int(l.category) for l in session.exec(select(Label).where(
            Label.image_id == it.id, Label.status == "approved")).all()] or [-1])) )
        for it in items])
    if probs is None or probs.ndim != 2 or probs.shape[0] != len(items):
        raise RuntimeError("job config requires pred_probs_path (n_items x n_classes matrix)")
    from cleanlab.filter import find_label_issues
    ordered_types = cfg.get("classes", [])
    issues_idx = find_label_issues(labels=labels, pred_probs=probs,
                                    return_indices_ranked_by_score=True)
    for rank, idx in enumerate(issues_idx):
        it = items[int(idx)]
        session.add(ImageIssue(
            image_id=it.id, dataset_id=dataset_id, issue_type="possible_label_error",
            score=float(rank) / max(1, len(issues_idx)), threshold=0.0,
            detector_name=p.name, detector_version=p.version,
            evidence_json={"rank": int(rank)}))
    session.commit()
    update_progress(job.id, len(issues_idx), 0, max(len(items), 1))


def _external_plugin(job: Job, capability: str, builtins: set[str], required: bool = False) -> tuple[str, str] | None:
    model_id = str(job.config_json.get("model_id") or model_catalog.active_model(capability) or "")
    if not model_id or model_id in builtins:
        if required:
            raise RuntimeError(f"no installed model is active for {capability}")
        return None
    spec = model_catalog.get_model(model_id)
    if spec.capability != capability:
        raise RuntimeError(f"model {model_id} does not provide {capability}")
    if not model_catalog.plugin_installed(spec.plugin_id):
        raise RuntimeError(f"plugin for {model_id} is not installed")
    return model_id, spec.plugin_id


def _job_items(session: Session, job: Job) -> list[ImageItem]:
    query = select(ImageItem).where(
        ImageItem.dataset_id == job.dataset_id,
        ImageItem.ingest_status == "done")
    raw_ids = job.config_json.get("item_ids")
    if isinstance(raw_ids, list):
        ids = {str(value) for value in raw_ids if str(value)}
        if not ids:
            return []
        query = query.where(ImageItem.id.in_(ids))
    return session.exec(query).all()


def _plugin_items(session: Session, job: Job, capability: str) -> tuple[str, str, list[ImageItem]]:
    model_id, plugin_id = _external_plugin(job, capability, set(), required=True) or ("", "")
    return model_id, plugin_id, _job_items(session, job)


def _plugin_payload(model_id: str, item: ImageItem, prompt: str = "") -> dict:
    return {"image_path": str(_item_path(item)), "model_id": model_id,
            "model_path": model_catalog.installed_path(model_id), "prompt": prompt}


def _validated_polygon(raw: object, item: ImageItem) -> list[dict[str, int]]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError("plugin returned an invalid polygon")
    points = []
    for point in raw:
        if not isinstance(point, dict):
            raise ValueError("plugin returned an invalid polygon point")
        try:
            x, y = int(point["x"]), int(point["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("plugin returned an invalid polygon point") from exc
        if x < 0 or y < 0 or x > item.width or y > item.height:
            raise ValueError("plugin returned a polygon outside image bounds")
        points.append({"x": x, "y": y})
    return points

def run_preannotate(session: Session, job: Job) -> None:
    external = _external_plugin(job, "preannotation", {"openai-vision"})
    model_id, plugin_id = external or (None, None)
    p = active("preannotation")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not external and not ok:
        raise RuntimeError(f"preannotation provider unavailable — {msg}")
    source_id = model_id or (p.name if p else "plugin")
    items = _job_items(session, job)
    total = len(items)
    processed = failed = pending = 0
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            out = plugin_runtime.invoke(plugin_id, "preannotation", _plugin_payload(model_id, it, PROMPT_PREANN)) if external else _vision_call(_item_path(it), PROMPT_PREANN, p.name, "preannotation")
            labels = []
            for lb in out.get("labels", []):
                labels.append(Label(
                    image_id=it.id, label_type="bbox",
                    category=str(lb.get("category", "object")).strip() or "object",
                    geometry_json=_validated_bbox(lb.get("bbox"), it),
                    source_type="model", source_id=source_id,
                    confidence=_confidence(lb.get("confidence")), status="pending"))
            _save_model_labels(session, job, it, "preannotation", source_id, labels,)
            processed += 1
        except Exception:  # noqa: BLE001 — API fora/pago/limite: item falha, job segue
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))

def run_pii_scan(session: Session, job: Job) -> None:
    external = _external_plugin(job, "pii", {"openai-vision-pii"})
    model_id, plugin_id = external or (None, None)
    p = active("pii")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not external and not ok:
        raise RuntimeError(f"PII provider unavailable — {msg}")
    source_id = model_id or (p.name if p else "plugin")
    dataset_id = job.dataset_id
    items = _job_items(session, job)
    # idempotente: issues possible_pii antigas (do mesmo source) são substituídas,
    # como faz run_quality com seus detectores — rescan não empilha duplicatas.
    _source_ids = {it.id for it in items}
    if _source_ids:
        for old in session.exec(select(ImageIssue).where(
                ImageIssue.dataset_id == dataset_id,
                ImageIssue.issue_type == "possible_pii",
                ImageIssue.image_id.in_(_source_ids))).all():
            if (old.detector_name or "") == source_id or old.status == "resolved":
                session.delete(old)
        session.commit()
    total = len(items)
    processed = failed = pending = 0
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            out = plugin_runtime.invoke(plugin_id, "pii", {"image_path": str(_item_path(it)), "model_id": model_id, "model_path": model_catalog.installed_path(model_id), "prompt": PROMPT_PII}) if external else _vision_call(_item_path(it), PROMPT_PII, p.name, "pii")
            if out.get("pii"):
                session.add(ImageIssue(
                    image_id=it.id, dataset_id=dataset_id, issue_type="possible_pii",
                    score=1.0, threshold=0.0, detector_name=source_id,
                    detector_version=p.version if p else "plugin",
                    evidence_json={"types": out.get("types", []),
                                   "evidence": str(out.get("evidence", ""))[:500]}))
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))


def _confidence(raw: object) -> float | None:
    if raw is None:
        return None
    value = float(raw)
    if not 0 <= value <= 1:
        raise ValueError("plugin returned an invalid confidence")
    return value


def _supersede_model_labels(session: Session, item_id: str, model_id: str) -> None:
    for old in session.exec(select(Label).where(
            Label.image_id == item_id, Label.source_type == "model",
            Label.source_id == model_id, Label.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)


def _automation_state(capability: str) -> tuple[bool, float, bool, bool]:
    config = model_catalog.read_settings().get("automation", {}).get(capability, {})
    return (
        bool(config.get("enabled", False)),
        max(0.0, min(1.0, float(config.get("confidence", 0.95)))),
        bool(config.get("preview", True)),
        bool(config.get("auto_quarantine", False)),
    )


def _save_model_labels(session: Session, job: Job, item: ImageItem, capability: str, model_id: str, labels: list[Label]) -> None:
    _supersede_model_labels(session, item.id, model_id)
    enabled, threshold, preview, auto_quarantine = _automation_state(capability)
    apply = enabled and not preview
    confident = [label for label in labels if label.confidence is not None and label.confidence >= threshold]
    for label in labels:
        if apply and label in confident:
            label.status = "approved"
        session.add(label)
        if apply and label in confident:
            session.add(ReviewDecision(
                target_type="label", target_id=label.id,
                decision="approve", reason=f"automation:{job.id}",
                comment=f"{capability} confidence {label.confidence:.2f}"))
    if apply and auto_quarantine and confident:
        previous = item.decision_status
        item.decision_status = "quarantine"
        item.quarantine_reason = f"automation:{capability} ({model_id})"
        session.add(item)
        session.add(ReviewDecision(
            target_type="item", target_id=item.id,
            decision="quarantine", reason=f"automation:{job.id}",
            comment=f"previous_decision:{previous}"))


def _run_plugin_labels(session: Session, job: Job, capability: str, output_key: str, parser) -> None:
    model_id, plugin_id, items = _plugin_items(session, job, capability)
    total = len(items)
    processed = failed = pending = 0
    errors: list[str] = []
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            output = plugin_runtime.invoke(plugin_id, capability, _plugin_payload(model_id, item))
            records = output.get(output_key)
            if not isinstance(records, list):
                raise ValueError(f"plugin output must contain a {output_key} list")
            _save_model_labels(session, job, item, capability, model_id, parser(records, item, model_id))
            processed += 1
        except Exception as exc:  # noqa: BLE001 — one bad image must not lose the job
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()


def _parse_ocr(records: list, item: ImageItem, model_id: str) -> list[Label]:
    labels = []
    for record in records:
        if not isinstance(record, dict) or not str(record.get("text", "")).strip():
            raise ValueError("plugin returned invalid OCR text")
        labels.append(Label(
            image_id=item.id, label_type="text", category="text",
            geometry_json=_validated_bbox(record.get("bbox"), item),
            value_json={"text": str(record["text"]).strip()},
            source_type="model", source_id=model_id,
            confidence=_confidence(record.get("confidence")), status="pending"))
    return labels


def _parse_detection(records: list, item: ImageItem, model_id: str) -> list[Label]:
    labels = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("plugin returned invalid detection")
        labels.append(Label(
            image_id=item.id, label_type="bbox",
            category=str(record.get("category", "object")).strip() or "object",
            geometry_json=_validated_bbox(record.get("bbox"), item),
            source_type="model", source_id=model_id,
            confidence=_confidence(record.get("confidence")), status="pending"))
    return labels


def _parse_segmentation(records: list, item: ImageItem, model_id: str) -> list[Label]:
    labels = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("plugin returned invalid mask")
        labels.append(Label(
            image_id=item.id, label_type="polygon",
            category=str(record.get("category", "object")).strip() or "object",
            geometry_json={"points": _validated_polygon(record.get("polygon"), item)},
            source_type="model", source_id=model_id,
            confidence=_confidence(record.get("confidence")), status="pending"))
    return labels


def run_ocr(session: Session, job: Job) -> None:
    _run_plugin_labels(session, job, "ocr", "texts", _parse_ocr)


def run_detection(session: Session, job: Job) -> None:
    _run_plugin_labels(session, job, "detection", "labels", _parse_detection)


def run_segmentation(session: Session, job: Job) -> None:
    _run_plugin_labels(session, job, "segmentation", "masks", _parse_segmentation)


def _caption_text(raw: object, config: dict) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("caption plugin returned empty text")
    separator = str(config.get("separator", ", ")) or ", "
    prefix = str(config.get("prefix", "")).strip()
    suffix = str(config.get("suffix", "")).strip()
    if prefix:
        text = f"{prefix}{separator}{text}"
    if suffix:
        text = f"{text}{separator}{suffix}"
    template = str(config.get("template", "{caption}"))
    if "{caption}" not in template:
        raise ValueError("caption template must contain {caption}")
    return template.replace("{caption}", text).strip()


def _save_caption(session: Session, job: Job, item: ImageItem, model_id: str, text: str,
                  confidence: float | None, config: dict) -> None:
    for old in session.exec(select(Caption).where(
            Caption.image_id == item.id, Caption.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)
    enabled, threshold, preview, _ = _automation_state("captioning")
    caption = Caption(image_id=item.id, text=text, prompt=str(config.get("prompt", "")),
                      prefix=str(config.get("prefix", "")), suffix=str(config.get("suffix", "")),
                      template=str(config.get("template", "{caption}")),
                      source_type="model", source_id=model_id, confidence=confidence,
                      status="approved" if enabled and not preview and (confidence or 0) >= threshold else "pending")
    session.add(caption)
    if caption.status == "approved":
        session.add(ReviewDecision(target_type="caption", target_id=caption.id,
                                   decision="approve", reason=f"automation:{job.id}",
                                   comment=f"caption confidence {confidence or 0:.2f}"))
def _run_cloud_caption(session: Session, job: Job, provider: str) -> None:
    config = job.config_json
    items = _job_items(session, job)
    total = len(items)
    processed = failed = 0
    errors: list[str] = []
    prompt = str(config.get("prompt", "Describe the main subject, setting, and visual style."))
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            output = _vision_call(_item_path(item), prompt, provider, "captioning")
            text = _caption_text(output.get("caption") or output.get("text"), config)
            _save_caption(session, job, item, provider, text, _confidence(output.get("confidence")), config)
            processed += 1
        except Exception as exc:  # noqa: BLE001 — one bad image must not lose the job
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()


def run_caption(session: Session, job: Job) -> None:
    if _external_plugin(job, "captioning", set()):
        _run_plugin_caption(session, job)
        return
    provider = active("captioning")
    if provider and provider.name in {"openai_vision", "replicate", "falai"}:
        ok, msg = provider.available()
        if not ok:
            raise RuntimeError(f"captioning provider unavailable — {msg}")
        _run_cloud_caption(session, job, provider.name)
        return
    _run_plugin_caption(session, job)


def _run_plugin_caption(session: Session, job: Job) -> None:
    model_id, plugin_id, items = _plugin_items(session, job, "captioning")
    config = job.config_json
    total = len(items)
    processed = failed = 0
    errors: list[str] = []
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            payload = _plugin_payload(model_id, item, str(config.get("prompt", "")))
            payload.update({key: config.get(key, default) for key, default in (
                ("prefix", ""), ("suffix", ""), ("separator", ", "), ("template", "{caption}"))})
            output = plugin_runtime.invoke(plugin_id, "captioning", payload)
            text = _caption_text(output.get("caption"), config)
            _save_caption(session, job, item, model_id, text, _confidence(output.get("confidence")), config)
            processed += 1
        except Exception as exc:  # noqa: BLE001 — one bad image must not lose the job
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()
