#!/usr/bin/env python3
"""Shared inference runtime for the official ids plugins.

Loads ONNX models via onnxruntime or TFLite models via ai-edge-litert,
reading weights from the model cache path provided in each request.
Self-contained: no pip installs required at runtime beyond what ships
inside the pluginpack.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# NOTE: vendored-wheel bootstrap lives in each plugin's run.py (with python-tag
# filtering); this module only provides inference helpers.


def onnx_session(model_path: str):
    import onnxruntime as ort
    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def tflite_interpreter(model_path: str):
    from ai_edge_litert.interpreter import Interpreter
    interp = Interpreter(model_path=str(model_path))
    interp.allocate_tensors()
    return interp


def preprocess_image(image_path: str, size: tuple[int, int], layout: str = "nchw",
                     normalize: bool = True) -> "list":
    """Decode an image and return a float32 tensor ready for inference."""
    import numpy as np
    from PIL import Image
    img = Image.open(image_path).convert("RGB").resize(size, Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32)
    if normalize:
        arr = arr / 255.0
        arr = (arr - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    if layout == "nchw":
        arr = arr.transpose(2, 0, 1)
    return arr[np.newaxis].astype(np.float32)


def jsonl_loop(handler) -> None:
    """Read ids-plugin.v1 requests on stdin; emit one result event per request."""
    import json
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        try:
            output = handler(request["capability"], request["payload"])
            event = {"type": "result", "output": output}
        except Exception as exc:  # noqa: BLE001 — surface diagnostics, never partial results
            event = {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(event) + "\n")
        sys.stdout.flush()
