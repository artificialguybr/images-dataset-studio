"""Embeddings + busca semântica + clusters/outliers.

Provider OpenCLIP opcional: sem torch instalado, job falha com mensagem clara
(nunca resultado falso). Vetores ficam em .npy fora do banco relacional.
"""
import math
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..analyzers import embeddings
from ..config import get_settings
from ..jobs import update_progress
from ..models import ImageItem, Job
from .. import model_catalog, plugin_runtime

MODEL_NAME = "ViT-B-32"
PRETRAINED = "openai"


def _model_for_job(job: Job) -> tuple[str, str | None]:
    model_id = str(job.config_json.get("model_id", ""))
    if not model_id or model_id == "openclip-vit-b32":
        return MODEL_NAME, None
    spec = model_catalog.get_model(model_id)
    if spec.capability != "embedding" or not model_catalog.plugin_installed(spec.plugin_id):
        raise RuntimeError(f"embedding plugin for {model_id} is not installed")
    return model_id, spec.plugin_id


def _plugin_vector(plugin_id: str, model_id: str, payload: dict) -> object:
    import numpy as np
    out = plugin_runtime.invoke(plugin_id, "embedding", {**payload, "model_id": model_id,
                                                           "model_path": model_catalog.installed_path(model_id)})
    vec = np.asarray(out.get("embedding"), dtype="float32")
    if vec.ndim != 1 or not vec.size:
        raise ValueError("plugin returned an invalid embedding")
    return vec

def _item_path(it: ImageItem) -> Path:
    return Path(it.source_uri.split(":", 1)[1])


def run_embeddings(session: Session, job: Job) -> None:
    model_name, plugin_id = _model_for_job(job)
    if plugin_id is None and not embeddings.is_available():
        raise RuntimeError("open-clip-torch is not installed — run `uv sync --extra ml`")
    dataset_id = job.dataset_id
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()
    cached = embeddings.load_vectors([it.id for it in items], model_name)
    total = len(items)
    processed = failed = 0
    from ..jobs import is_cancelled
    for it in items:
        if is_cancelled(job.id):
            break
        if it.id in cached:
            processed += 1
            continue
        try:
            if plugin_id:
                import numpy as np
                out = plugin_runtime.invoke(plugin_id, "embedding", {
                    "image_path": str(_item_path(it)), "model_id": model_name,
                    "model_path": model_catalog.installed_path(model_name)})
                vec = np.asarray(out.get("embedding"), dtype="float32")
                if vec.ndim != 1 or not vec.size:
                    raise ValueError("plugin returned an invalid embedding")
                np.save(embeddings._vector_path(it.id, model_name), vec)
            else:
                vec = embeddings.embed_image(it.id, _item_path(it), MODEL_NAME, PRETRAINED,
                                            content_hash=it.content_hash_sha256 or "")
            processed += 1 if vec is not None else 0
            if vec is None:
                failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        update_progress(job.id, processed, failed, max(total, 1))
    _matrix_cache.clear()  # novos vetores: busca/cluster não podem usar cache velho

def _normalize(v):
    import numpy as np
    return v / (np.linalg.norm(v) + 1e-9)


_matrix_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}  # (ds, model) -> (timestamp, {id: vec})
_MATRIX_TTL = 300.0


def _vectors_for(session: Session, dataset_id: str, model_key: str,
              items: list) -> dict[str, Any]:
    """Matriz de vetores com cache TTL — busca/cluster não re-leem N .npy por request."""
    import time
    now = time.monotonic()
    hit = _matrix_cache.get((dataset_id, model_key))
    if hit and now - hit[0] < _MATRIX_TTL:
        return hit[1]
    vecs = embeddings.load_vectors([it.id for it in items], model_key)
    _matrix_cache.clear()  # 1 dataset ativo por vez: RAM de vetores é o gargalo
    _matrix_cache[(dataset_id, model_key)] = (now, vecs)
    return vecs


def semantic_search(session: Session, dataset_id: str, query: str,
                  kind: str = "text", image_id: str | None = None,
                  limit: int = 50, filters: dict | None = None):
    """Busca com o modelo de embedding ativo e índice isolado por model_id."""
    model_name = model_catalog.active_model("embedding") or "openclip-vit-b32"
    plugin_id: str | None = None
    if model_name == "openclip-vit-b32":
        if not embeddings.is_available():
            raise RuntimeError("open-clip-torch is not installed — run `uv sync --extra ml`")
        model_key = MODEL_NAME
    else:
        spec = model_catalog.get_model(model_name)
        if spec.capability != "embedding" or not model_catalog.plugin_installed(spec.plugin_id):
            raise RuntimeError(f"embedding plugin for {model_name} is not installed")
        plugin_id = spec.plugin_id
        model_key = model_name
    import numpy as np
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()
    if filters:
        from .filters import apply_filters
        stmt = select(ImageItem).where(
            ImageItem.dataset_id == dataset_id,
            ImageItem.ingest_status == "done")
        items = apply_filters(session, stmt, filters)
    if kind == "text":
        qv = (_plugin_vector(plugin_id, model_key, {"text": query}) if plugin_id
              else embeddings.embed_text(query, MODEL_NAME, PRETRAINED))
    else:
        src = session.get(ImageItem, image_id)
        if src is None:
            return []
        qv = (_plugin_vector(plugin_id, model_key, {"image_path": str(_item_path(src))}) if plugin_id
              else embeddings.embed_image(src.id, _item_path(src), MODEL_NAME, PRETRAINED,
                                         content_hash=src.content_hash_sha256 or ""))
    if qv is None:
        return []
    qv = _normalize(qv)
    vectors = _vectors_for(session, dataset_id, model_key, items)
    scored = []
    for it in items:
        v = vectors.get(it.id)
        if v is not None:
            scored.append((float(np.dot(_normalize(v), qv)), it.id))
    scored.sort(reverse=True)
    return [{"image_id": iid, "score": sc} for sc, iid in scored[:limit]]


def clusters(session: Session, dataset_id: str, k: int = 8, limit_items: int = 2000):
    """KMeans simples sobre embeddings normalizados; outliers = mais distantes do centro.

    ponytail: kMeans numpy puro, KMeans++ init; MiniBatch/sklearn se escalar.
    """
    if model_name == "openclip-vit-b32" and not embeddings.is_available():
        raise RuntimeError("open-clip-torch is not installed — run `uv sync --extra ml`")
    import numpy as np
    items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.ingest_status == "done")).all()
    model_key = MODEL_NAME if model_name == "openclip-vit-b32" else model_name
    vectors = _vectors_for(session, dataset_id, model_key, items)
    ids = [it.id for it in items if it.id in vectors]
    if not ids:
        return {"clusters": [], "outliers": []}
    X = np.stack([_normalize(vectors[i]) for i in ids])
    k = min(k, len(ids))
    rng = np.random.default_rng(0)
    centers = X[rng.choice(len(X), k, replace=False)]
    assign = np.zeros(len(X), dtype=int)
    for _ in range(25):
        dists = 1 - X @ centers.T                     # (n, k) cosine dist
        new_assign = dists.argmin(axis=1)
        if (new_assign == assign).all():
            break
        assign = new_assign
        for j in range(k):
            mask = assign == j
            if mask.any():
                centers[j] = X[mask].mean(axis=0)
    dists = 1 - X @ centers.T
    best = dists.min(axis=1)
    outlier_idx = np.argsort(best)[-max(10, len(ids) // 50):]
    clusters_out = []
    for j in range(k):
        members = [ids[i] for i in range(len(ids)) if assign[i] == j]
        rep = members[int(np.argmin([dists[i, j] for i in range(len(ids)) if assign[i] == j]))] if members else None
        clusters_out.append({"cluster": j, "count": len(members),
                             "representative": rep, "members": members[:200]})
    outliers = [{"image_id": ids[i], "distance": float(best[i])} for i in outlier_idx]
    outliers.sort(key=lambda o: -o["distance"])
    return {"clusters": clusters_out, "outliers": outliers}
