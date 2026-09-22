"""Dedup: grupos exatos (SHA-256) e near-duplicates (dHash hamming).

Nunca remove todos os membros de um grupo; canônico eleito por regra explícita:
maior resolução; desempate por maior byte_size; desempate final por id (estável).
"""
from typing import Any

from sqlmodel import Session, select

from ..analyzers.dedup import DETECTOR_VERSION, hamming_hex
from ..config import get_settings
from ..jobs import update_progress
from ..models import DuplicateGroup, DuplicateMember, ImageItem, Job


def swap_canonical(session: Session, group_id: str, item_id: str) -> DuplicateGroup:
    """Swap the canonical member of a duplicate group."""
    g = session.get(DuplicateGroup, group_id)
    if g is None:
        raise ValueError("group not found")
    ms = session.exec(select(DuplicateMember).where(DuplicateMember.group_id == group_id)).all()
    if not any(m.image_id == item_id for m in ms):
        raise ValueError("item does not belong to group")
    for m in ms:
        m.is_canonical = m.image_id == item_id
        session.add(m)
    session.commit()
    session.refresh(g)
    return g.model_dump()


def derive_from_items(session: Session, name: str, source_id: str, item_ids: list[str],
                     note: str = "") -> dict:
    """Dataset derivado a partir de ids arbitrários (grupos de duplicatas, clusters, outliers)."""
    from .derive_service import _register_from_item
    items = session.exec(select(ImageItem).where(ImageItem.id.in_(item_ids))).all()  # noqa: E501
    ds = _derive_new_dataset(session, name, source_id, note)
    for it in items:
        if it.decision_status != "keep":
            continue
        _register_from_item(session, ds.id, it)
    session.commit()
    session.refresh(ds)
    return ds.model_dump()


def _derive_new_dataset(session: Session, name: str, source_id: str, note: str) -> Any:
    from ..models import Dataset
    from datetime import datetime, timezone
    ds = Dataset(name=name, source_type="derived", parent_id=source_id,
                 notes=f"{note} derived from {source_id}")
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _canonical(items: list[ImageItem]) -> ImageItem:
    return sorted(items, key=lambda i: (-i.width * i.height, -i.byte_size, i.id))[0]


def _replace_groups(session: Session, dataset_id: str, method: str) -> None:
    for g in session.exec(select(DuplicateGroup).where(
            DuplicateGroup.dataset_id == dataset_id,
            DuplicateGroup.method == method)).all():
        for m in session.exec(select(DuplicateMember).where(
                DuplicateMember.group_id == g.id)).all():
            session.delete(m)
        session.delete(g)
    session.commit()


def _make_group(session: Session, dataset_id: str, method: str,
               members: list[ImageItem], threshold: float,
               similarities: dict[str, float]) -> None:
    canon = _canonical(members)
    g = DuplicateGroup(dataset_id=dataset_id, method=method,
                      threshold=threshold, model_name="")
    session.add(g)
    session.flush()
    for it in members:
        session.add(DuplicateMember(
            group_id=g.id, image_id=it.id,
            similarity=similarities.get(it.id, 1.0),
            is_canonical=(it.id == canon.id),
            evidence_json={"phash" if method == "phash" else "sha256":
                          it.perceptual_hash if method == "phash" else it.content_hash_sha256},
        ))


def run_exact_dedup(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    _replace_groups(session, dataset_id, "sha256")
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()
    by_hash: dict[str, list[ImageItem]] = {}
    for it in items:
        if it.content_hash_sha256:
            by_hash.setdefault(it.content_hash_sha256, []).append(it)
    total = sum(1 for v in by_hash.values() if len(v) > 1)
    processed = 0
    from ..jobs import is_cancelled
    for group_items in by_hash.values():
        if is_cancelled(job.id):
            break
        if len(group_items) > 1:
            _make_group(session, dataset_id, "sha256", group_items, 0.0, {})
            processed += 1
            session.commit()  # libera lock antes do update_progress abrir outra sessão
            update_progress(job.id, processed, 0, max(total, 1))


def run_phash_dedup(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    s = get_settings()
    hamming_th = int(job.config_json.get("hamming_threshold", s.phash_threshold_hamming))
    _replace_groups(session, dataset_id, "phash")
    items = [it for it in session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all() if it.perceptual_hash]
    # ponytail: varredura O(n^2) por hamming; buckets por bits p/ >100k imagens
    used: set[str] = set()
    total = len(items)
    groups = 0
    from ..jobs import is_cancelled
    for i, a in enumerate(items):
        if is_cancelled(job.id):
            break
        if a.id in used:
            continue
        members = [a]
        sims = {a.id: 0.0}
        for b in items[i + 1:]:
            if b.id in used:
                continue
            d = hamming_hex(a.perceptual_hash, b.perceptual_hash)
            if d <= hamming_th:
                members.append(b)
                sims[b.id] = float(d)
        if len(members) > 1:
            used.update(m.id for m in members)
            _make_group(session, dataset_id, "phash", members, float(hamming_th), sims)
            groups += 1
            session.commit()  # libera lock antes do update_progress abrir outra sessão
        update_progress(job.id, i + 1, 0, max(total, 1))
    session.commit()
