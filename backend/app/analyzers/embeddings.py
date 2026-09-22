"""Embeddings: OpenCLIP plugável; cache por (sha256, model, version).

Regra: nunca assumir que embeddings de modelos diferentes são comparáveis.
Se torch/open_clip não estiverem instalados, provider fica 'unavailable'
e a busca semântica responde 501 — sem resultado falso.
"""
import json
from pathlib import Path
from typing import Any, Optional

from ..config import get_settings

DETECTOR_VERSION = "openclip-1"

try:
    import open_clip
    import torch
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_model_cache: dict[tuple, Any] = {}       # (model, pretrained, device) -> (model, preprocess, tokenizer)
_model_last_used: dict[tuple, float] = {}
_vector_cache: dict[tuple, Any] = {}       # (sha256, model, pretrained, ver) -> vec — com teto
_VECTOR_CACHE_MAX = 20000                   # ~512-dim float32: ~40 MB; além disso, disco
_UNLOAD_AFTER_S = 600                     # 10 min idle -> unload + empty_cache


def _get_np():
    import numpy as np
    return np


def is_available() -> bool:
    return _AVAILABLE


def _device() -> str:
    from ..config import get_settings
    d = get_settings().openclip_device
    if d:
        return d
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model(model_name: str, pretrained: str):
    import time
    key = (model_name, pretrained, _device())
    now = time.monotonic()
    _model_last_used[key] = now
    if key not in _model_cache:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=key[2])
        tokenizer = open_clip.get_tokenizer(model_name)
        model.eval()
        _model_cache[key] = (model, preprocess, tokenizer)
    _unload_idle(now)
    return _model_cache[key]


def _unload_idle(now: float) -> None:
    """Despeja modelos parados há mais de _UNLOAD_AFTER_S — RAM/VRAM voltam pro sistema."""
    stale = [k for k, t in _model_last_used.items()
             if now - t > _UNLOAD_AFTER_S and k in _model_cache]
    for k in stale:
        _model_cache.pop(k, None)
        _model_last_used.pop(k, None)
    if stale and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _vector_path(image_id: str, model_name: str) -> Path:
    s = get_settings()
    d = s.embeddings_dir / model_name.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{image_id}.npy"


def embed_image(image_id: str, image_path: Path, model_name: str = "ViT-B-32",
               pretrained: str = "openai",
               content_hash: str = "") -> Optional[Any]:
    """Embed de imagem. Cache por (hash de conteúdo, modelo); o hash vem da coluna
    content_hash_sha256 do banco quando o chamador passa — sem re-ler o arquivo."""
    np = _get_np()
    if not _AVAILABLE:
        return None
    model, preprocess, _ = _load_model(model_name, pretrained)
    cache_key = (content_hash or sha256_file(image_path), model_name, pretrained, DETECTOR_VERSION)
    if cache_key not in _vector_cache:
        if len(_vector_cache) >= _VECTOR_CACHE_MAX:
            _vector_cache.pop(next(iter(_vector_cache)))
        from PIL import Image
        img = preprocess(Image.open(image_path)).unsqueeze(0).to(_device())
        with torch.no_grad():
            vec = model.encode_image(img).squeeze(0).cpu().numpy().astype("float32")
        _vector_cache[cache_key] = vec
        np.save(_vector_path(image_id, model_name), vec)
    return _vector_cache[cache_key]


def embed_text(text: str, model_name: str = "ViT-B-32", pretrained: str = "openai"):
    if not _AVAILABLE:
        return None
    model, _, tokenizer = _load_model(model_name, pretrained)
    toks = tokenizer([text]).to(_device())
    with torch.no_grad():
        return model.encode_text(toks).squeeze(0).cpu().numpy().astype("float32")


def load_vectors(image_ids: list[str], model_name: str = "ViT-B-32") -> dict[str, Any]:
    """Carrega vetores persistidos; retorna {image_id: vector}."""
    np = _get_np()
    out: dict[str, Any] = {}
    for iid in image_ids:
        p = _vector_path(iid, model_name)
        if p.exists():
            out[iid] = np.load(p)
    return out
