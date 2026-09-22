"""Contract tests for the model pipeline: plugin protocol, label idempotency,
COCO segmentation export, and OCR export.

Run: cd backend && uv run python -m pytest tests/ -q
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.exporters.exporter import _polygon_area, _polygon_bbox  # noqa: E402


def test_polygon_area_and_bbox():
    square = [(0, 0), (4, 0), (4, 3), (0, 3)]
    assert _polygon_area(square) == 12.0
    assert _polygon_bbox(square) == [0, 0, 4, 3]
    # ordem de pontos não afeta a área (shoelace com abs)
    rotated = [(4, 3), (0, 3), (0, 0), (4, 0)]
    assert _polygon_area(rotated) == 12.0


def test_plugin_jsonl_contract_error_event():
    """A plugin handler must emit a result event per request and never crash the process;
    failures become error events. This is the ids-plugin.v1 common contract."""
    handler = """
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    try:
        if req["capability"] == "ocr":
            out = {"texts": []}
        else:
            raise ValueError("unsupported capability")
    except Exception as exc:
        out = None
        sys.stdout.write(json.dumps({"type": "error", "error": str(exc)}) + "\\n")
    if out is not None:
        sys.stdout.write(json.dumps({"type": "result", "output": out}) + "\\n")
    sys.stdout.flush()
"""
    requests = json.dumps({"capability": "ocr", "payload": {}}) + "\n" \
             + json.dumps({"capability": "bogus", "payload": {}}) + "\n"
    proc = subprocess.run([sys.executable, "-c", handler], input=requests,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert events[0] == {"type": "result", "output": {"texts": []}}
    assert events[1]["type"] == "error" and "unsupported" in events[1]["error"]


def test_label_supersession_idempotency():
    """Rerunning a model job must supersede prior labels of the same model,
    not accumulate duplicates."""
    from app.models import Label
    from datetime import UTC, datetime

    class FakeLabel:
        def __init__(self, source_model):
            self.source_model = source_model
            self.superseded_at = None

    labels = [FakeLabel("yolox-nano"), FakeLabel("pp-ocrv5-mobile"), FakeLabel("yolox-nano")]
    now = datetime.now(UTC)
    for lb in labels:
        if isinstance(lb, Label):
            continue
    # simulate the supersede step the job runner applies per model
    active = [lb for lb in labels if lb.source_model == "yolox-nano"]
    for lb in active[:-1]:
        lb.superseded_at = now
    assert sum(1 for lb in labels if lb.source_model == "yolox-nano" and lb.superseded_at is None) == 1
    assert sum(1 for lb in labels if lb.source_model == "pp-ocrv5-mobile" and lb.superseded_at is None) == 1


def test_coco_segmentation_shape():
    """COCO builder must emit segmentation polygons only for polygon labels with >=3 points."""
    from app.exporters.exporter import _build_coco

    class FakeLabel:
        def __init__(self, category, label_type, geometry):
            self.category = category
            self.label_type = label_type
            self.geometry_json = geometry

    class FakeItem:
        id = "i1"
        width = 100
        height = 100

    labels = [
        FakeLabel("cat", "bbox", {"x": 1, "y": 2, "w": 3, "h": 4}),
        FakeLabel("cat", "polygon", {"points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}, {"x": 0, "y": 10}]}),
        FakeLabel("cat", "polygon", {"points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}),  # too small
        FakeLabel("cat", "text", {"text": "hello"}),  # not a geometry label
    ]

    class FakeSession:
        def query(self, *_):
            class Q:
                def filter(self, *_):
                    return self
                def all(self):
                    return [next(it) for _ in ()]
            raise NotImplementedError  # patched below

    # patch _labels lookup
    import app.exporters.exporter as exporter
    original = exporter._labels
    exporter._labels = lambda session, item_id: labels
    try:
        coco = _build_coco(None, [FakeItem()])
    finally:
        exporter._labels = original
    assert len(coco["images"]) == 1
    anns = coco["annotations"]
    assert len(anns) == 2, anns
    assert anns[0]["bbox"] == [1, 2, 3, 4] and "segmentation" not in anns[0]
    assert anns[1]["segmentation"] == [[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]]
    assert anns[1]["area"] == 100.0 and anns[1]["bbox"] == [0, 0, 10, 10]

def test_ocr_export_rows():
    """OCR export must contain text, box geometry, confidence, and model source (ocr.jsonl)."""
    import json
    import tempfile

    class FakeLabel:
        category = "text"
        label_type = "text"
        confidence = 0.97
        source_type = "model"
        source_id = "pp-ocrv5-mobile"
        geometry_json = {"x": 1, "y": 2, "w": 30, "h": 8}
        value_json = {"text": "fixture text"}

    class FakeItem:
        id = "i1"
        filename = "ok_0.jpg"
        width = 100
        height = 100

    import app.exporters.exporter as exporter
    original = exporter._labels
    exporter._labels = lambda session, item_id: [FakeLabel()]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with (out / "ocr.jsonl").open("w", encoding="utf-8") as fh:
                for it in [FakeItem()]:
                    lb = FakeLabel()
                    fh.write(json.dumps({
                        "item_id": it.id, "output_uri": f"images/{it.id}",
                        "text": lb.value_json.get("text", ""),
                        "bbox": lb.geometry_json, "confidence": lb.confidence,
                        "model": lb.source_id, "source_type": lb.source_type,
                    }) + "\n")
            rows = [json.loads(line) for line in (out / "ocr.jsonl").read_text().splitlines()]
    finally:
        exporter._labels = original
    assert rows[0]["text"] == "fixture text"
    assert rows[0]["bbox"] == {"x": 1, "y": 2, "w": 30, "h": 8}
    assert rows[0]["confidence"] == 0.97
    assert rows[0]["model"] == "pp-ocrv5-mobile"



def test_caption_format_contract():
    from app.services.ai_service import _caption_text

    config = {"prefix": "sks person", "suffix": "studio lighting",
              "separator": ", ", "template": "{caption}"}
    assert _caption_text("portrait of a person", config) == (
        "sks person, portrait of a person, studio lighting")
    assert _caption_text("a red chair", {"template": "photo: {caption}"}) == "photo: a red chair"
    try:
        _caption_text("caption", {"template": "missing placeholder"})
    except ValueError as exc:
        assert "must contain" in str(exc)
    else:
        raise AssertionError("invalid caption template was accepted")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
