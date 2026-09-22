"""Dedup: hash exato (SHA-256) e perceptual (dHash 8x8, hamming).

dHash mantém o formato binário legado; hamming usa XOR+popcount.
"""
import hashlib
import numpy as np
from PIL import Image

DETECTOR_VERSION = "2"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_int(h: str | int) -> int:
    if isinstance(h, int):
        return h
    h = h.strip()
    if h.startswith("0b"):
        return int(h, 2)
    if len(h) == 64 and set(h) <= {"0", "1"}:
        return int(h, 2)
    return int(h, 16)


def dhash(img: Image.Image, size: int = 8) -> str:
    """Difference perceptual hash — 64 bits como string binária legada."""
    gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.int16)
    diff = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    return "".join("1" if bit else "0" for bit in diff)


def hamming_hex(a: str | int, b: str | int) -> int:
    return (_as_int(a) ^ _as_int(b)).bit_count()
