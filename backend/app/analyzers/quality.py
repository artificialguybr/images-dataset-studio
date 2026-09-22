"""Analyzers de qualidade — cada um registra método, versão e threshold.

Regra do plano: score não é decisão; humano decide (keep/review/quarantine).
"""
import io
import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

DETECTOR_VERSION = "1"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


def decode_image(path) -> tuple[Image.Image | None, dict[str, Any]]:
    """Decode real + verify. Retorna (pil_image, evidence); image None => corrupt."""
    evidence: dict[str, Any] = {}
    try:
        with open(path, "rb") as fh:
            fh.seek(0)
            data = fh.read()
        img = Image.open(io.BytesIO(data))
        img.verify()  # detecta truncamento/corrupção
        img = Image.open(io.BytesIO(data))  # reopen: verify() invalida o objeto
        img.load()
        evidence["format"] = img.format or ""
        return img, evidence
    except Exception as exc:  # noqa: BLE001
        evidence["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return None, evidence


def to_gray(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)


ANALYZE_MAX_SIDE = 1024  # downsample antes dos detectores; laplaciano/entropia são estáveis sob resize


def prepare(img: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """Retorna (img reduzida, gray 1x) — detectores compartilham a mesma gray."""
    w, h = img.size
    m = max(w, h)
    if m > ANALYZE_MAX_SIDE:
        scale = ANALYZE_MAX_SIDE / m
        img = img.convert("RGB").resize((max(1, round(w * scale)), max(1, round(h * scale))),
                                Image.Resampling.BILINEAR)
    gray = to_gray(img)
    return img, gray


def blur_score(img: Image.Image, gray: np.ndarray | None = None) -> float:
    """Variância do Laplacian (>=0); baixo => borrado. Threshold ~100 default."""
    gray = to_gray(img) if gray is None else gray
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def luminance_stats(img: Image.Image, gray: np.ndarray | None = None) -> dict[str, float]:
    g = (to_gray(img) if gray is None else gray).astype(np.float32)
    return {"mean": float(g.mean()), "std": float(g.std())}


def contrast_score(img: Image.Image, gray: np.ndarray | None = None) -> float:
    return luminance_stats(img, gray)["std"]


def entropy_score(img: Image.Image, gray: np.ndarray | None = None) -> float:
    g = to_gray(img) if gray is None else gray
    p = np.bincount(g.flatten(), minlength=256).astype(np.float64)
    p = p[p > 0] / g.size
    return float(-(p * np.log2(p)).sum())


def edge_density(img: Image.Image, gray: np.ndarray | None = None) -> float:
    g = to_gray(img) if gray is None else gray
    edges = cv2.Canny(g, 100, 200)
    return float(np.count_nonzero(edges)) / float(edges.size)


def is_grayscale(img: Image.Image) -> bool:
    """Requer RGB — chame com a imagem já reduzida por prepare()."""
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return bool(np.mean(np.abs(r - g) + np.abs(g - b) + np.abs(r - b)) < 3.0)


def brightness_histogram(img: Image.Image, gray: np.ndarray | None = None, bins: int = 32) -> list[int]:
    """Histograma de luminância (para revisão de brilho na UI — Fase 3.4.5)."""
    g = to_gray(img) if gray is None else gray
    hist, _ = np.histogram(g, bins=bins, range=(0, 256))
    return [int(x) for x in hist]

def color_histogram(img: Image.Image, bins: int = 32) -> dict[str, list[int]]:
    """Return independent RGB histograms for the inspector preview."""
    rgb = np.asarray(img.convert("RGB"))
    return {
        channel: [int(v) for v in np.histogram(rgb[..., index], bins=bins, range=(0, 256))[0]]
        for channel, index in (("red", 0), ("green", 1), ("blue", 2))
    }


SCREENSHOT_MARKERS = {
    "ui_chrome": ["file", "edit", "view", "favorites", "notifications", "settings",
                  "search", "share", "submit", "cancel", "loading", "sign in",
                  "home", "menu", "play", "next", "previous", "back"],
    "watermark_words": ["watermark", "shutterstock", "getty images", "istockphoto",
                        "alamy", "dreamstime", "123rf", "depositphotos"],
}


# ponytail: OCR de baixa confiança via tesseract quando disponível; fallback heurístico
def _ocr_text(img: Image.Image) -> str:
    try:
        import pytesseract
        return pytesseract.image_to_string(img).lower()
    except Exception:  # noqa: BLE001
        return ""


def screenshot_score(img: Image.Image, gray: np.ndarray | None = None) -> dict[str, Any]:
    """Heurística de screenshot/watermark (§4.3): UI chrome texto + bordas planas +
    watermark por OCR opcional. score 0-1; >0.5 => provável screenshot/watermark."""
    gray = to_gray(img) if gray is None else gray
    h, w = gray.shape
    ev: dict[str, Any] = {}
    # 1. bordas planas (barras de UI sólidas em cima/baixo)
    top = gray[: max(1, h // 20)]
    bot = gray[-max(1, h // 20):]
    flat_edges = 0.0
    for strip in (top, bot):
        if strip.size and float(strip.std()) < 4.0:
            flat_edges += 0.5
    # 2. razão de aspecto típica de tela
    ar = w / max(1, h)
    screen_ar = 0.2 if any(abs(ar - r) < 0.12 for r in (16/9, 16/10, 4/3, 3/2, 19.5/9)) else 0.0
    # 3. texto de UI/watermark via OCR
    text = _ocr_text(img)
    hits = [m for ms in SCREENSHOT_MARKERS.values() for m in ms if m in text]
    ui_text = 0.5 if hits else 0.0
    ev["ui_words"] = hits[:5]
    ev["flat_edges"] = flat_edges
    ev["screen_ar"] = round(ar, 3)
    score = min(1.0, flat_edges * 0.4 + screen_ar + ui_text)
    ev["score"] = round(score, 3)
    return ev
