"""Derivação de datasets: derive (por filtros), merge e split — sempre sem mover originais.

Derive cria ImageItems novos apontando para os MESMOS bytes (source_uri compartilhado,
novo id por dataset). Split com seed reproduzível.
"""
import hashlib
import random
from datetime import UTC, datetime

from sqlmodel import Session, select

from ..models import Dataset, ImageItem, Label


def derive(session: Session, source_ds: str, name: str, description: str,
          filters: dict) -> Dataset:
    """filters: qualquer combinação de {q, status, issue, tag, min_width, license}."""
    stmt = select(ImageItem).where(ImageItem.dataset_id == source_ds,
                                   ImageItem.ingest_status == "done")
    from .filters import apply_filters
    items = apply_filters(session, stmt, filters)
    ds = Dataset(name=name, description=description, source_type="derived",
                 source_uri=f"derived:{source_ds}")
    session.add(ds)
    session.commit()
    for it in items:
        ni = _register_from_item(session, ds.id, it)
        for lb in session.exec(select(Label).where(Label.image_id == it.id)).all():
            session.add(Label(image_id=ni.id, label_type=lb.label_type, category=lb.category,
                             geometry_json=lb.geometry_json, value_json=lb.value_json,
                             source_type=lb.source_type, status=lb.status))
    ds.updated_at = datetime.now(UTC)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds.model_dump()


def merge(session: Session, dataset_ids: list[str], name: str) -> Dataset:
    """Junta N datasets; IDs de item nunca colidem (UUID), origem preservada por item."""
    ds = Dataset(name=name, description=f"merge de {len(dataset_ids)} datasets",
                 source_type="merged", source_uri="merged:" + ",".join(dataset_ids))
    session.add(ds)
    session.commit()
    seen_hash: dict[str, str] = {}
    collisions = 0
    for src in dataset_ids:
        for it in session.exec(select(ImageItem).where(
                ImageItem.dataset_id == src, ImageItem.ingest_status == "done")).all():
            # Fase 10.9: mesmo conteúdo (sha256) já copiado de outro dataset = colisão pulada
            if it.content_hash_sha256 and it.content_hash_sha256 in seen_hash:
                collisions += 1
                continue
            if it.content_hash_sha256:
                seen_hash[it.content_hash_sha256] = it.id
            ni = _register_from_item(session, ds.id, it,)
            for lb in session.exec(select(Label).where(Label.image_id == it.id)).all():
                session.add(Label(image_id=ni.id, label_type=lb.label_type, category=lb.category,
                                 geometry_json=lb.geometry_json, value_json=lb.value_json,
                                 source_type=lb.source_type, status=lb.status))
    session.commit()
    ds.description += f" — {collisions} content collisions detected and skipped" if collisions else ""
    session.add(ds)
    session.commit()
    session.refresh(ds)
    out = ds.model_dump()
    out["content_collisions"] = collisions
    return out


def split(session: Session, source_ds: str, ratios: list[float], seed: int = 0) -> list[Dataset]:
    """Split por hash determinístico: str(item.id+seed) define partição — reproduzível."""
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == source_ds,
        ImageItem.decision_status.in_(("keep", "restore")),
        ImageItem.ingest_status == "done")).all()
    total_ratio = sum(ratios) or 1.0
    bounds = []
    acc = 0.0
    for r in ratios:
        acc += r / total_ratio
        bounds.append(acc)
    out = []
    for i, _r in enumerate(ratios):
        ds = Dataset(name=f"split-{i}-of-{source_ds[:8]}", source_type="split",
                     source_uri=f"split:{source_ds}")
        session.add(ds)
        session.commit()
        out.append(ds)
    for it in items:
        h = int(hashlib.sha256((it.id + str(seed)).encode()).hexdigest(), 16) / 2**256
        part = next(i for i, b in enumerate(bounds) if h <= b)
        _register_from_item(session, out[part].id, it,)
    session.commit()
    for ds in out:
        session.refresh(ds)
    return [ds.model_dump() for ds in out]


def _register_from_item(session: Session, dataset_id: str, it: ImageItem) -> ImageItem:
    """Cria item novo no dataset destino apontando pros mesmos bytes do original."""
    ni = ImageItem(dataset_id=dataset_id,
                   source_uri=it.source_uri, storage_uri=it.storage_uri,
                   original_filename=it.original_filename, relative_path=it.relative_path,
                   mime_type=it.mime_type, byte_size=it.byte_size,
                   content_hash_sha256=it.content_hash_sha256, perceptual_hash=it.perceptual_hash,
                   width=it.width, height=it.height, channels=it.channels, mode=it.mode,
                   exif_json=it.exif_json, tags_json=it.tags_json,
                   ingest_status=it.ingest_status, license=it.license,
                   license_evidence_uri=it.license_evidence_uri)
    session.add(ni)
    session.flush()
    return ni
