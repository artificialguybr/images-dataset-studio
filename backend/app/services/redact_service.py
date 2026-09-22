"""Redaction de PII (Fase 9.3.6): blur nas regiões apontadas por issues possible_pii,
gera novas imagens (as originais nunca são tocadas) e registra versão nova."""
from datetime import UTC, datetime
from pathlib import Path

from PIL import ImageFilter
from sqlmodel import Session, select

from ..analyzers import quality
from ..config import get_settings
from ..models import Dataset, DatasetVersion, ImageIssue, ImageItem, Job, Label
from .paths import item_path



def redact_pii(session: Session, job: Job, radius: int = 12) -> None:
    """Fase 9.3.6: blur das regiões possible_pii + versão nova. Runner no formato (session, job)."""
    ds_id = job.dataset_id
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise ValueError("dataset not found")
    issues = session.exec(select(ImageIssue).where(
        ImageIssue.dataset_id == ds_id,
        ImageIssue.issue_type == "possible_pii")).all()
    if not issues:
        return {"redacted": 0, "note": "nenhuma issue possible_pii neste dataset"}
    by_item: dict[str, list[ImageIssue]] = {}
    for iss in issues:
        by_item.setdefault(iss.image_id, []).append(iss)

    s = get_settings()
    red_dir = s.data_dir / "redacted" / ds_id[:8]
    red_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for iid, iss_list in by_item.items():
        it = session.get(ImageItem, iid)
        if it is None or it.decision_status not in ("keep", "restore"):
            continue
        src = item_path(it)
        img, _ev = quality.decode_image(src)
        if img is None:
            continue
        px = img.convert("RGB")
        for iss in iss_list:
            geo = (iss.evidence_json or {}).get("bbox") or (iss.evidence_json or {}).get("region")
            if not geo:
                continue
            x, y = int(geo["x"]), int(geo["y"])
            w, h = int(geo["w"]), int(geo["h"])
            pad = radius
            box = (max(0, x - pad), max(0, y - pad),
                   min(px.width, x + w + pad), min(px.height, y + h + pad))
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            region = px.crop(box).filter(ImageFilter.GaussianBlur(radius))
            px.paste(region, box)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out = red_dir / f"{it.id[:12]}-{stamp}.jpg"
        px.save(out, "JPEG", quality=90)
        # aponta o item para a cópia redigida; original preservado em source_uri antigo
        it.license_evidence_uri = it.license_evidence_uri or it.source_uri
        it.source_uri = f"file:{out}"
        it.relative_path = out.name
        session.add(it)
        # marca as issues como tratadas
        for iss in iss_list:
            iss.status = "resolved"
            session.add(iss)
        n += 1
    session.commit()
    # versão nova com o resultado (auditoria) — reusa o serviço existente
    from .versions_service import create_version
    v = create_version(session, ds_id, description=f"PII redaction de {n} itens; originais preservados")
    session.refresh(v)
    return {"redacted": n, "version_id": v.id}


def _dumps(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False, sort_keys=True)