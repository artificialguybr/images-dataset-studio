#!/usr/bin/env python3
"""privacy-local plugin: PP-OCRv5 mobile OCR (detection + recognition) and BlazeFace PII.

Real ONNX/TFLite inference over the model cache. Detection finds text boxes
(DBNet postprocess); recognition decodes each box (CTC greedy).
"""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(next(p for p in (Path(__file__).resolve().parent / "_shared",
                                        Path(__file__).resolve().parent.parent / "_shared") if p.is_dir())))

from inference import jsonl_loop, onnx_session, tflite_interpreter  # noqa: E402

_det_sess = None
_rec_sess = None
_pii_interp = None


def _db_postprocess(pred, threshold=0.3):
    """DBNet text boxes from a probability map (simple connected contours)."""
    import cv2
    import numpy as np
    pred = np.asarray(pred).squeeze()
    prob = (pred > threshold).astype(np.uint8) * 255
    # DBNet-style: close glyph gaps so letters merge into text lines
    kernel = np.ones((3, 25), np.uint8)
    prob = cv2.morphologyEx(prob, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(prob, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        rect = cv2.minAreaRect(contour)
        if rect[1][0] < 8 or rect[1][1] < 4:
            continue
        box = cv2.boxPoints(rect)
        boxes.append(np.intp(box))
    return boxes


def _expand_box(box, w, h, pad=0.15):
    import numpy as np
    center = box.mean(axis=0)
    size = box.max(axis=0) - box.min(axis=0)
    size = size * (1 + pad * 2)
    half = size / 2
    lo = np.maximum(0, center - half).astype(int)
    hi = np.minimum([w, h], center + half).astype(int)
    return lo, hi


def run_ocr(payload):
    global _det_sess, _rec_sess
    import numpy as np
    from PIL import Image
    if _det_sess is None:
        cache = Path(payload["model_path"]).parent
        det_file = next(cache.glob("*det*.onnx"), None)
        rec_file = next(cache.glob("*rec*.onnx"), None)
        if det_file is None or rec_file is None:
            raise ValueError("model cache must contain det and rec ONNX files")
        _det_sess = onnx_session(str(det_file))
        _rec_sess = onnx_session(str(rec_file))
    img = Image.open(payload["image_path"]).convert("RGB")
    w, h = img.size
    # PaddleOCR-style resize: keep aspect, limit side to 960, round to /32
    scale = min(960 / max(w, h), 1.0)
    rw, rh = int(round(w * scale / 32) * 32), int(round(h * scale / 32) * 32)
    rw, rh = max(32, rw), max(32, rh)
    det_in = np.asarray(img.resize((rw, rh), Image.BILINEAR), dtype=np.float32) / 255.0
    det_in = (det_in - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    det_in = det_in.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    det_out = _det_sess.run(None, {(_det_sess.get_inputs()[0].name): det_in})[0]
    det_out = np.asarray(det_out).squeeze()
    # boxes come from the resized det input; map back to original image size
    scale_x, scale_y = w / det_out.shape[-1], h / det_out.shape[-2]
    boxes = [box * [scale_x, scale_y] for box in _db_postprocess(det_out)]
    texts = []
    for box in boxes[:64]:
        lo, hi = _expand_box(box, w, h)
        if hi[0] <= lo[0] or hi[1] <= lo[1]:
            continue
        crop = img.crop((int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1]))).resize((320, 48))
        rec_in = np.asarray(crop, dtype=np.float32) / 255.0
        rec_in = (rec_in - [0.5, 0.5, 0.5]) / [0.5, 0.5, 0.5]
        rec_in = rec_in.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
        rec_out = _rec_sess.run(None, {(_rec_sess.get_inputs()[0].name): rec_in})[0]
        text, conf = _ctc_decode(rec_out)
        if text and conf >= 0.5:
            x, y = int(lo[0]), int(lo[1])
            texts.append({"text": text, "confidence": round(float(conf), 4),
                          "bbox": {"x": x, "y": y, "w": int(hi[0] - lo[0]), "h": int(hi[1] - lo[1])}})
    return {"texts": texts}


def _ctc_decode(logits):
    """Greedy CTC decode; PP-OCRv5 dict is embedded in the ONNX metadata sidecar."""
    import numpy as np
    logits = np.asarray(logits)
    if logits.ndim == 2:
        logits = logits[np.newaxis]
    if logits.min() >= 0.0 and logits.max() <= 1.0:
        probs = logits  # PP-OCRv5 rec ONNX emits probabilities directly
    else:
        e = np.exp(logits - logits.max(-1, keepdims=True))
        probs = e / e.sum(-1, keepdims=True)
    ids = probs[0].argmax(-1)
    confs = probs[0].max(-1)
    charset = _charset()
    out, conf, prev, n = [], 0.0, -1, 0
    for idx, c in zip(ids, confs):
        i = int(idx)
        if i != prev and i != 0:
            out.append(charset[i] if 0 < i < len(charset) else "")
            conf += float(c)
            n += 1
        prev = i
    return "".join(out), conf / max(1, n)


_CHARSET = None
def _charset():
    """PP-OCRv5 dictionary (charset.json beside this file, vendored into packs)."""
    global _CHARSET
    if _CHARSET is None:
        import json
        path = Path(__file__).resolve().parent / "charset.json"
        _CHARSET = json.loads(path.read_text(encoding="utf-8"))
    return _CHARSET


_CHARSET = None
def run_pii(payload):
    """BlazeFace short-range: face boxes become possible-PII evidence."""
    global _pii_interp
    import numpy as np
    from PIL import Image
    if _pii_interp is None:
        _pii_interp = tflite_interpreter(payload["model_path"])
    interp = _pii_interp
    inp = interp.get_input_details()[0]
    h, w = int(inp["shape"][1]), int(inp["shape"][2])
    img = Image.open(payload["image_path"]).convert("RGB")
    orig_w, orig_h = img.size
    arr = np.asarray(img.resize((w, h)), dtype=np.float32)[np.newaxis]
    if arr.max() > 1.5:
        arr = arr / 255.0
    interp.set_tensor(inp["index"], arr)
    interp.invoke()
    regressors = interp.get_tensor(interp.get_output_details()[0]["index"])[0]   # (896, 16)
    raw_scores = interp.get_tensor(interp.get_output_details()[1]["index"])[0]   # (896, 1)
    np.clip(raw_scores, -80, 80, out=raw_scores)
    probs = 1 / (1 + np.exp(-raw_scores[:, 0]))
    # decode follows fdlite (MIT) / mediapipe tflite_tensors_to_detections
    anchors = _ssd_anchors()
    points = regressors.reshape(-1, 8, 2) / h  # 8 xy points, normalized
    points[:, 0] += anchors                     # point 0 = box center (x, y)
    best = int(probs.argmax())
    boxes = []
    if probs[best] > 0.5:
        cx, cy = points[best, 0]
        bw, bh = points[best, 1]
        x, y = max(0, int((cx - bw / 2) * orig_w)), max(0, int((cy - bh / 2) * orig_h))
        boxes.append({"x": x, "y": y,
                      "w": min(int(bw * orig_w), orig_w - x),
                      "h": min(int(bh * orig_h), orig_h - y)})
    return {"pii": bool(boxes), "types": ["face"] * len(boxes),
            "boxes": boxes, "evidence": f"{len(boxes)} face(s) detected"}


def _ssd_anchors():
    """BlazeFace 896 anchors (mediapipe ssd_anchors_calculator): strides [8,16,16,16],
    each cell repeated twice; normalized (x, y) centers."""
    anchors = []
    for stride, repeats in ((8, 2), (16, 6)):
        fm = 128 // stride
        for y in range(fm):
            for x in range(fm):
                for _ in range(repeats):
                    anchors.append(((x + 0.5) / fm, (y + 0.5) / fm))
    return np.array(anchors, dtype=np.float32)



def main():
    jsonl_loop(lambda capability, payload: run_ocr(payload) if capability == "ocr" else run_pii(payload))


if __name__ == "__main__":
    main()
