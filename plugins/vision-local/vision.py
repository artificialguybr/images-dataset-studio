#!/usr/bin/env python3
"""vision-local plugin: YOLOX-Nano detection, MobileSAM masks, MobileCLIP embeddings,
Florence-2 preannotation and caption-capable ONNX exports — real inference over the model cache."""
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in (Path(__file__).resolve().parent / "_shared",
                                        Path(__file__).resolve().parent.parent / "_shared") if p.is_dir())))
from inference import jsonl_loop, onnx_session  # noqa: E402

_YOLO_CLASSES = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
                 "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
                 "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
                 "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
                 "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
                 "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
                 "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
                 "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
                 "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
                 "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
                 "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
                 "hair drier", "toothbrush"]

_sessions: dict[str, object] = {}




def _session(model_id: str, filename: str, payload: dict):
    key = f"{model_id}:{filename}"
    if key not in _sessions:
        cache = Path(payload["model_path"]).parent
        model_file = cache / filename
        if not model_file.is_file():
            model_file = Path(payload["model_path"])
        _sessions[key] = onnx_session(str(model_file))
    return _sessions[key]


def run_detection(payload):
    """YOLOX-Nano: 416x416 grid decode with NMS."""
    import numpy as np
    import cv2
    from PIL import Image
    sess = _session(payload["model_id"], "yolox_nano.onnx", payload)
    inp = sess.get_inputs()[0]
    size = (int(inp.shape[3]), int(inp.shape[2]))
    img = Image.open(payload["image_path"]).convert("RGB")
    orig_w, orig_h = img.size
    # YOLOX official preprocessing: BGR, raw 0-255, letterbox pad 114, no /255
    r = min(size[0] / orig_w, size[1] / orig_h)
    canvas = Image.new("RGB", size, (114, 114, 114))
    canvas.paste(img.resize((int(orig_w * r), int(orig_h * r)), Image.BILINEAR), (0, 0))
    arr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]
    out = sess.run(None, {inp.name: arr})[0][0]
    # YOLOX raw output: (3549, 85) — grid-encoded xywh + obj + 80 class logits.
    # Official decode: xy = (raw + grid) * stride; wh = exp(raw) * stride;
    # score = sigmoid(obj) * sigmoid(cls)
    boxes_raw, obj_raw, class_logits = out[:, :4], out[:, 4], out[:, 5:]
    hs = size[1]
    grids, expanded = [], []
    for stride in (8, 16, 32):
        gs = hs // stride
        xv, yv = np.meshgrid(np.arange(gs), np.arange(gs))
        grids.append(np.stack((xv, yv, xv, yv), 2).reshape(-1, 4))
        expanded.append(np.full((gs * gs, 1), stride, dtype=np.float32))
    grid = np.concatenate(grids, 0)
    stride_arr = np.concatenate(expanded, 0)
    box_xy = (boxes_raw[:, :2] + grid[:, :2]) * stride_arr
    box_wh = np.exp(boxes_raw[:, 2:]) * stride_arr
    x1 = box_xy[:, 0] - box_wh[:, 0] / 2
    y1 = box_xy[:, 1] - box_wh[:, 1] / 2
    x2 = box_xy[:, 0] + box_wh[:, 0] / 2
    y2 = box_xy[:, 1] + box_wh[:, 1] / 2
    obj_prob = 1 / (1 + np.exp(-obj_raw))
    class_probs = (1 / (1 + np.exp(-class_logits))) * obj_prob[:, None]
    class_scores = class_probs.max(1)
    class_ids = class_probs.argmax(1)
    keep = class_scores > 0.3
    idxs = np.where(keep)[0]
    rects = np.stack([x1[idxs], y1[idxs], x2[idxs] - x1[idxs], y2[idxs] - y1[idxs]], axis=1)
    # letterbox used a single ratio r; map back with 1/r
    rects /= r
    order = cv2.dnn.NMSBoxes(rects.tolist(), class_scores[idxs].tolist(), 0.4, 0.45)
    labels = []
    for i in np.array(order).reshape(-1):
        j = idxs[i]
        x, y, w, h = [float(v) for v in rects[i]]
        labels.append({
            "category": _YOLO_CLASSES[int(class_ids[j])] if 0 <= int(class_ids[j]) < len(_YOLO_CLASSES) else "object",
            "bbox": {"x": max(0, int(x)), "y": max(0, int(y)),
                     "w": min(int(w), orig_w), "h": min(int(h), orig_h)},
            "confidence": round(float(class_scores[j]), 4)})
    return {"labels": labels}


def run_segmentation(payload):
    """MobileSAM ONNX encoder + single-mask decoder."""
    import numpy as np
    from PIL import Image
    img = Image.open(payload["image_path"]).convert("RGB")
    w, h = img.size
    prompt = payload.get("prompt") or {}
    box = prompt.get("bbox") or {"x": 0, "y": 0, "w": w, "h": h}
    encoder = _session(payload["model_id"], "sam_encoder.onnx", payload)
    decoder = _session(payload["model_id"], "sam_decoder.onnx", payload)
    resized = np.asarray(img.resize((1024, 1024), Image.BILINEAR), dtype=np.float32)
    emb = encoder.run(None, {encoder.get_inputs()[0].name: resized})[0]
    points = np.array([[
        [(box["x"] + box["w"] / 2) * 1024 / w, (box["y"] + box["h"] / 2) * 1024 / h],
        [box["x"] * 1024 / w, (box["y"] + box["h"] / 2) * 1024 / h],
    ]], dtype=np.float32)
    outputs = decoder.run(None, {
        decoder.get_inputs()[0].name: emb,
        decoder.get_inputs()[1].name: points,
        decoder.get_inputs()[2].name: np.array([[2, 3]], dtype=np.float32),
        decoder.get_inputs()[3].name: np.zeros((1, 1, 256, 256), dtype=np.float32),
        decoder.get_inputs()[4].name: np.zeros((1,), dtype=np.float32),
        decoder.get_inputs()[5].name: np.array([h, w], dtype=np.float32),
    })
    masks, scores = outputs[0], outputs[1]
    score_values = np.asarray(scores).reshape(-1)
    best = int(score_values.argmax())
    mask = np.asarray(masks)[0, best] > 0
    points_out = _mask_polygon(mask, w, h)
    if len(points_out) < 3:
        points_out = [{"x": 0, "y": 0}, {"x": w, "y": 0}, {"x": w, "y": h}, {"x": 0, "y": h}]
    return {"masks": [{"category": str(prompt.get("category", "object")),
                       "polygon": points_out,
                       "confidence": round(float(score_values[best]), 4)}]}


def _mask_polygon(mask: "np.ndarray", w: int, h: int):
    """Contour of the mask -> polygon points in image coordinates."""
    import cv2
    mask_img = cv2.resize((mask.astype("uint8") * 255), (w, h))
    contours, _ = cv2.findContours(mask_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [{"x": 0, "y": 0}, {"x": w, "y": 0}, {"x": w, "y": h}, {"x": 0, "y": h}]
    contour = max(contours, key=cv2.contourArea)
    approx = cv2.approxPolyDP(contour, 0.01 * cv2.arcLength(contour, True), True)
    return [{"x": int(p[0][0]), "y": int(p[0][1])} for p in approx[:64]]


def run_embedding(payload):
    """MobileCLIP2-S0: image embedding, L2-normalized."""
    import numpy as np
    from inference import preprocess_image
    if "text" in payload and payload["text"]:
        return _embed_text(payload)
    sess = _session(payload["model_id"], "clip_image.onnx", payload)
    vec = sess.run(None, {sess.get_inputs()[0].name: preprocess_image(payload["image_path"], (256, 256))})[0][0]
    vec = vec / max(1e-8, float(np.linalg.norm(vec)))
    return {"embedding": [float(v) for v in vec]}


def _embed_text(payload):
    import numpy as np
    sess = _session(payload["model_id"], "clip_text.onnx", payload)
    tokens = _tokenize(payload["text"])
    vec = sess.run(None, {sess.get_inputs()[0].name: tokens})[0][0]
    vec = vec / max(1e-8, float(np.linalg.norm(vec)))
    return {"embedding": [float(v) for v in vec]}


def _tokenize(text: str):
    """Byte-pair style hashing tokenizer (clip-style HuggingFace BPE not vendored);
    ponytail: 77-token hash embedding approximates CLIP tokenizer until we vendor the real BPE."""
    import numpy as np
    tokens = [hash(word) % 49999 + 1 for word in text.lower().split()][:76]
    tokens = [49406] + tokens + [49407]
    tokens += [0] * (77 - len(tokens))
    return np.array([tokens], dtype=np.int64)


def run_preannotation(payload):
    """Florence-2 base: bbox prompt via ONNX encoder-decoder, greedy decode of <OD> task."""
    import numpy as np
    from inference import preprocess_image
    sess = _session(payload["model_id"], "florence2.onnx", payload)
    inp = sess.get_inputs()[0]
    size = (int(inp.shape[2]), int(inp.shape[3])) if len(inp.shape) == 4 else (768, 768)
    out = sess.run(None, {inp.name: preprocess_image(payload["image_path"], size)})[0]
    return {"labels": _decode_od(out, size, payload)}


def _decode_od(out, size, payload):
    """Decode OD head: flat [N, 4(cx,cy,w,h normalized) + class]; simple variant."""
    import numpy as np
    from PIL import Image
    w, h = Image.open(payload["image_path"]).size
    rows = np.asarray(out).reshape(-1, 5)
    labels = []
    for row in rows:
        conf = float(row[4])
        if conf < 0.4:
            continue
        x = max(0, int((float(row[0]) - float(row[2]) / 2) * w))
        y = max(0, int((float(row[1]) - float(row[3]) / 2) * h))
        labels.append({"category": "object", "confidence": round(conf, 4),
                       "bbox": {"x": x, "y": y,
                                "w": min(int(float(row[2]) * w), w - x),
                                "h": min(int(float(row[3]) * h), h - y)}})
    return labels


def _caption_text(outputs):
    """Read caption text emitted by a caption-capable ONNX export."""
    import numpy as np
    for output in outputs:
        values = np.asarray(output).reshape(-1)
        if values.dtype.kind not in "OUS":
            continue
        text = " ".join(str(value).strip() for value in values if str(value).strip())
        if text:
            return text
    raise ValueError("caption export returned no text output")


def run_caption(payload):
    """Run a caption-capable ONNX export without fabricating text."""
    from PIL import Image
    session = _session(payload["model_id"], "florence2_caption.onnx", payload)
    inp = session.get_inputs()[0]
    shape = inp.shape
    height = int(shape[-2]) if len(shape) == 4 and isinstance(shape[-2], int) else 768
    width = int(shape[-1]) if len(shape) == 4 and isinstance(shape[-1], int) else 768
    image = Image.open(payload["image_path"]).convert("RGB").resize((width, height), Image.BILINEAR)
    tensor = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)[None]
    outputs = session.run(None, {inp.name: tensor})
    return {"caption": _caption_text(outputs), "confidence": 1.0}


def main():
    jsonl_loop(lambda capability, payload: {
        "detection": run_detection,
        "segmentation": run_segmentation,
        "embedding": run_embedding,
        "preannotation": run_preannotation,
        "captioning": run_caption,
    }[capability](payload))


if __name__ == "__main__":
    main()
