"""Unit tests das funções puras (Fase 2.9): analyzers de qualidade, dedup, redact, importers.

Run: cd backend && uv run python -m pytest tests/ -q  (ou: uv run python tests/test_units.py)
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzers import quality  # noqa: E402
from app.analyzers.dedup import dhash, hamming_hex, sha256_file  # noqa: E402


def _img_bytes(color=(120, 120, 120), size=(64, 64), fmt="JPEG"):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def test_histogram_bins_sum_to_pixels():
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(_img_bytes()))
    hist = quality.brightness_histogram(img, bins=32)
    assert len(hist) == 32
    assert sum(hist) == 64 * 64, "histograma deve somar o total de pixels"
    peak = hist.index(max(hist))
    assert 14 <= peak <= 18, f"pico esperado no bin do cinza 120, got {peak}"


def test_screenshot_flat_edges_score():
    from PIL import Image
    import io
    import numpy as np
    # imagem com barras sólidas em cima/baixo => flat_edges alto
    arr = np.full((480, 640, 3), 60, dtype=np.uint8)
    arr[40:440] = 150
    img = Image.fromarray(arr)
    ev = quality.screenshot_score(img)
    assert ev["flat_edges"] >= 0.9, ev


def test_screenshot_uniform_low_score():
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(_img_bytes()))
    ev = quality.screenshot_score(img)
    # imagem uniforme pode ter bordas planas mas sem AR de tela/OCR => score moderado-baixo
    assert ev["score"] <= 0.5, ev


def test_grayscale_detect():
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(_img_bytes(color=(10, 200, 10))))
    assert quality.is_grayscale(img) is False
    img2 = Image.open(io.BytesIO(_img_bytes(color=(100, 100, 100))))
    assert quality.is_grayscale(img2) is True


def test_entropy_of_uniform_is_zero():
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(_img_bytes()))
    assert quality.entropy_score(img) < 0.01


def test_dhash_identical_images_equal_hash():
    from PIL import Image
    import io
    data = _img_bytes(color=(30, 144, 255), size=(80, 60))
    assert dhash(Image.open(io.BytesIO(data))) == dhash(Image.open(io.BytesIO(data)))
    assert dhash(Image.open(io.BytesIO(data))).startswith(("0", "1"))


def test_hamming_distance_changes_with_brightness():
    from PIL import Image
    import io
    import numpy as np
    arr1 = np.full((64, 64, 3), 30, dtype=np.uint8)
    arr1[:, 32:] = 200  # metade escura, metade clara => gradiente horizontal
    arr2 = np.full((64, 64, 3), 30, dtype=np.uint8)
    arr2[:32, :] = 200  # metade superior clara => gradiente vertical
    a = dhash(Image.fromarray(arr1))
    b = dhash(Image.fromarray(arr2))
    assert hamming_hex(a, b) > 0, (a, b)


def test_voc_parser(tmp_path=None):
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "Annotations").mkdir(); (d / "JPEGImages").mkdir()
    from PIL import Image
    Image.new("RGB", (100, 90), (50, 50, 50)).save(d / "JPEGImages" / "a.jpg")
    (d / "Annotations" / "a.xml").write_text(
        '<annotation><filename>a.jpg</filename>'
        '<size><width>100</width><height>90</height></size>'
        '<object><name>dog</name><bndbox>'
        '<xmin>10</xmin><ymin>20</ymin><xmax>60</xmax><ymax>70</ymax>'
        '</bndbox></object></annotation>')
    from sqlmodel import SQLModel, Session, create_engine, select
    from app.models import Dataset, Job, ImageItem, Label
    from app.services.importers import run_import_voc
    import app.jobs as jobsmod

    class FakeJob:
        id = "job-voc-test"; dataset_id = "ds-test-voc"; config_json = {"folder": str(d)}

    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    orig = jobsmod.engine
    jobsmod.engine = eng
    try:
        with Session(eng) as s:
            s.add(Dataset(id="ds-test-voc", name="voc-test"))
            s.add(Job(id="job-voc-test", type="import_voc", dataset_id="ds-test-voc"))
            s.commit()
            run_import_voc(s, FakeJob())
            items = s.exec(select(ImageItem)).all()
            assert len(items) == 1, items
            labels = s.exec(select(Label)).all()
            assert len(labels) == 1 and labels[0].category == "dog", labels
            assert labels[0].geometry_json == {"x": 10.0, "y": 20.0, "w": 50.0, "h": 50.0}
    finally:
        jobsmod.engine = orig


if __name__ == "__main__":
    import inspect
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        try:
            sig = inspect.signature(fn)
            if len(sig.parameters) == 0:
                fn()
            else:
                fn(None)
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}"); sys.exit(1)
    print(f"ALL {len(fns)} UNIT TESTS PASS")
