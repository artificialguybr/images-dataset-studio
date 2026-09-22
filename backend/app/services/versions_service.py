"""Versões: snapshot imutável + manifest JSONL + checksum. Quarentena/decisões.

Regra: snapshot final nunca é alterado silenciosamente; restore cria nova versão
apontando para a parent, ou reativa a versão antiga como current.
"""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..config import get_settings
from ..models import (Dataset, DatasetVersion, ImageItem, Label,
                      ReviewDecision)


def _manifest_entry(it: ImageItem, labels: list[Label]) -> dict[str, Any]:
    return {
        "item_id": it.id,
        "source_uri": it.source_uri,
        "output_uri": it.storage_uri,
        "sha256": it.content_hash_sha256,
        "width": it.width,
        "height": it.height,
        "labels": [{"id": lb.id, "type": lb.label_type, "category": lb.category,
                    "source_type": lb.source_type, "status": lb.status}
                   for lb in labels],
        "tags": it.tags_json,
        "decision": it.decision_status,
    }


def create_version(session: Session, dataset_id: str, description: str = "") -> DatasetVersion:
    s = get_settings()
    ds = session.get(Dataset, dataset_id)
    assert ds is not None
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.decision_status.in_(("keep", "restore")))).all()
    entries = []
    for it in items:
        labels = session.exec(select(Label).where(
            Label.image_id == it.id, Label.status == "approved")).all()
        entries.append(_manifest_entry(it, labels))

    parent_id = ds.current_version_id
    v = DatasetVersion(dataset_id=dataset_id, parent_version_id=parent_id,
                       item_count=len(entries), description=description,
                       snapshot_json=entries)
    session.add(v)
    session.flush()

    manifest_dir = s.manifests_dir / dataset_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{v.id}.jsonl"
    payload = "\n".join(json.dumps(e) for e in entries)
    manifest_path.write_text(payload, encoding="utf-8")
    v.checksum = hashlib.sha256(payload.encode()).hexdigest()
    v.manifest_uri = str(manifest_path.relative_to(s.data_dir))
    ds.current_version_id = v.id
    ds.updated_at = datetime.now(UTC)
    session.add(ds)
    session.add(v)
    session.commit()
    session.refresh(v)
    return v


def diff_versions(session: Session, dataset_id: str, old_id: str, new_id: str) -> dict:
    def ids(vid):
        v = session.get(DatasetVersion, vid)
        if v is None:
            return set()
        return {e["item_id"] for e in v.snapshot_json}
    old, new = ids(old_id), ids(new_id)
    return {"added": sorted(new - old), "removed": sorted(old - new)}


def set_decision(session: Session, item_id: str, decision: str, reason: str = "",
                reviewer: str = "local") -> ImageItem:
    it = session.get(ImageItem, item_id)
    assert it is not None
    it.decision_status = decision
    it.quarantine_reason = reason if decision == "quarantine" else ""
    session.add(it)
    session.add(ReviewDecision(target_type="item", target_id=item_id,
                               reviewer_id=reviewer, decision=decision, reason=reason))
    # invalida cover do dataset (recalculada quando cache é mais velho que updated_at)
    ds = session.get(Dataset, it.dataset_id)
    if ds is not None:
        ds.updated_at = datetime.now(UTC)
        session.add(ds)
    session.commit()
    session.refresh(it)
    return it
