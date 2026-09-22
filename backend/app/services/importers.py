"""Imports de datasets existentes: ImageFolder, YOLO (labels txt), COCO (annotations json).

Não usa Datumaro (dependência pesada) — parsers diretos, testados contra os formatos
que o próprio app exporta. Regra: importar labels com source_type='imported'.
"""
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..analyzers import quality
from ..analyzers.dedup import dhash, sha256_file
from ..config import get_settings
from ..jobs import update_progress
from ..models import ImageItem, Job, Label
from .ingest import _register


def _find_image(folder: Path, stem: str) -> Path | None:
    for ext in quality.IMAGE_EXTENSIONS:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def run_import_voc(session: Session, job: Job) -> None:
    """Pascal VOC: Annotations/*.xml (um por imagem) + JPEGImages/ (ou raiz)."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id
    ann_dir = folder / "Annotations" if (folder / "Annotations").is_dir() else folder
    img_dir = folder / "JPEGImages" if (folder / "JPEGImages").is_dir() else folder
    import xml.etree.ElementTree as ET
    anns = sorted(ann_dir.glob("*.xml"))
    total = len(anns)
    processed = failed = 0
    for xf in anns:
        try:
            root = ET.parse(xf).getroot()
            fname = root.findtext("filename") or (xf.stem + ".jpg")
            f = img_dir / fname
            if not f.exists():
                f = _find_image(img_dir, xf.stem)
            if f is None:
                raise FileNotFoundError(fname)
            item = _register(session, dataset_id, f, fname, "imported")
            if item.ingest_status != "done":
                failed += 1
            else:
                w = int(root.findtext("size/width") or item.width)
                h = int(root.findtext("size/height") or item.height)
                for obj in root.findall("object"):
                    cat = obj.findtext("name") or "unknown"
                    bb = obj.find("bndbox")
                    if bb is None:
                        continue
                    x0 = float(bb.findtext("xmin")); y0 = float(bb.findtext("ymin"))
                    x1 = float(bb.findtext("xmax")); y1 = float(bb.findtext("ymax"))
                    session.add(Label(image_id=item.id, label_type="bbox", category=cat,
                                      geometry_json={"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
                                      value_json={"voc": [x0, y0, x1, y1]},
                                      source_type="imported", status="approved"))
                processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_imagenet(session: Session, job: Job) -> None:
    """ImageNet-style: pares img + txt com rótulos, ou lista de caminhos + arquivo de classes."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id
    # classes.txt opcional no formato: id nome (ou um nome por linha)
    classes: list[str] = []
    cfile = folder / "classes.txt"
    if cfile.exists():
        for line in cfile.read_text().splitlines():
            parts = line.split(None, 1)
            classes.append(parts[1].strip() if len(parts) > 1 else parts[0].strip())
    todo: list[tuple[Path, str]] = []
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() not in quality.IMAGE_EXTENSIONS:
            continue
        lf = f.with_suffix(".txt")
        if lf.exists():  # label lateral: categorias por linha (nome ou índice)
            cats = []
            for line in lf.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                cats.append(classes[int(line)] if line.isdigit() and int(line) < len(classes) else line)
            for c in cats or ["unknown"]:
                todo.append((f, c))
        else:
            todo.append((f, ""))
    total = len({f for f, _ in todo}) or len(todo)
    processed = failed = 0
    seen: set[str] = set()
    for f, cat in todo:
        try:
            if str(f) in seen and cat:
                # item já registrado: só adicionar a label extra
                it = session.exec(select(ImageItem).where(ImageItem.source_uri == f"file:{f}")).first()
                if it:
                    session.add(Label(image_id=it.id, label_type="classification", category=cat,
                                      source_type="imported", status="approved"))
                    session.commit()
                continue
            item = _register(session, dataset_id, f, str(f.relative_to(folder)), "imported")
            seen.add(str(f))
            if cat and item.ingest_status == "done":
                session.add(Label(image_id=item.id, label_type="classification", category=cat,
                                  source_type="imported", status="approved"))
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_urls(session: Session, job: Job) -> None:
    """Importar de URLs http(s) — baixa cada URL para raw/. Útil p/ cloud (S3/GS/azure presigned URLs)."""
    cfg = job.config_json
    urls: list[str] = cfg.get("urls") or []
    if not urls and cfg.get("urls_file"):
        urls = [u.strip() for u in Path(cfg["urls_file"]).read_text().splitlines() if u.strip()]
    if not urls and cfg.get("urls_json"):
        urls = json.loads(cfg["urls_json"])
    dataset_id = job.dataset_id
    total = len(urls)
    processed = failed = 0
    import urllib.request
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "images-studio/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r, tempfile.NamedTemporaryFile(suffix=Path(u).suffix or ".jpg", delete=False) as tmp:
                shutil.copyfileobj(r, tmp)
                tmp_path = Path(tmp.name)
            item = _register(session, dataset_id, tmp_path, u, "imported")
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_retry_errors(session: Session, job: Job) -> None:
    """Reprocessar apenas os itens com ingest_status=error deste dataset (Fase 1.16)."""
    cfg = job.config_json
    dataset_id = job.dataset_id
    items = session.exec(
        select(ImageItem).where(ImageItem.dataset_id == dataset_id, ImageItem.ingest_status == "error")  # noqa: E501
    ).all()
    total = len(items)
    processed = failed = 0
    for it in items:
        try:
            src = it.source_uri.split(":", 1)[1] if ":" in it.source_uri else it.source_uri
            _register(session, dataset_id, Path(src), it.relative_path, "retried")
            if session.get(ImageItem, it.id).ingest_status == "done":
                processed += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_imagefolder(session: Session, job: Job) -> None:
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id
    classes = sorted([d.name for d in folder.iterdir() if d.is_dir()]) if cfg.get("labeled") else []
    processed = failed = 0
    if classes:
        todo = [(f, c) for c in classes for f in sorted((folder / c).rglob("*")) if f.is_file()]
    else:
        todo = [(f, "") for f in sorted(folder.rglob("*")) if f.is_file()]
    total = len(todo)
    for f, cat in todo:
        if f.suffix.lower() not in quality.IMAGE_EXTENSIONS:
            continue
        try:
            item = _register(session, dataset_id, f, str(f.relative_to(folder)), "imported")
            if cat and item.ingest_status == "done":
                session.add(Label(image_id=item.id, label_type="classification",
                                  category=cat, source_type="imported", status="approved"))
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_yolo(session: Session, job: Job) -> None:
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    images_dir = folder / "images" if (folder / "images").is_dir() else folder
    labels_dir = folder / "labels" if (folder / "labels").is_dir() else folder
    classes_file = folder / "classes.txt"
    classes = [l.strip() for l in classes_file.read_text().splitlines() if l.strip()] if classes_file.exists() else []
    dataset_id = job.dataset_id
    imgs = [f for f in sorted(images_dir.rglob("*")) if f.suffix.lower() in quality.IMAGE_EXTENSIONS]
    total = len(imgs)
    processed = failed = 0
    for f in imgs:
        try:
            item = _register(session, dataset_id, f, str(f.relative_to(images_dir)), "imported")
            if item.ingest_status != "done":
                failed += 1
            else:
                lf = labels_dir / (f.stem + ".txt")
                if lf.exists():
                    for line in lf.read_text().splitlines():
                        parts = line.split()
                        if len(parts) != 5:
                            continue
                        cid, xc, yc, w, h = parts
                        cat = classes[int(cid)] if classes and int(cid) < len(classes) else f"class_{cid}"
                        session.add(Label(image_id=item.id, label_type="bbox", category=cat,
                                          geometry_json={"x": float(xc) * item.width, "y": float(yc) * item.height,
                                                         "w": float(w) * item.width, "h": float(h) * item.height},
                                          value_json={"normalized": [float(xc), float(yc), float(w), float(h)]},
                                          source_type="imported", status="approved"))
                processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_coco(session: Session, job: Job) -> None:
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    ann_path = folder / "coco_annotations.json" if (folder / "coco_annotations.json").exists() else folder / "annotations.json"
    coco: dict[str, Any] = json.loads(ann_path.read_text())
    dataset_id = job.dataset_id
    img_dir = folder if not (folder / "images").is_dir() else folder / "images"
    by_id = {im["id"]: im for im in coco.get("images", [])}
    cat_by_id = {c["id"]: c["name"] for c in coco.get("categories", [])}
    anns: dict[int, list[Any]] = {}
    for a in coco.get("annotations", []):
        anns.setdefault(a["image_id"], []).append(a)
    total = len(by_id)
    processed = failed = 0
    for cid, meta in by_id.items():
        f = _find_image(img_dir, str(meta.get("file_name", "").rsplit(".", 1)[0])) if "." in meta.get("file_name", "") else _find_image(img_dir, meta.get("file_name", ""))
        if f is None:
            failed += 1
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            continue
        try:
            item = _register(session, dataset_id, f, meta.get("file_name", f.name), "imported")
            if item.ingest_status == "done":
                for a in anns.get(cid, []):
                    x, y, w, h = a["bbox"]
                    session.add(Label(image_id=item.id, label_type="bbox",
                                      category=cat_by_id.get(a["category_id"], "unknown"),
                                      geometry_json={"x": x, "y": y, "w": w, "h": h},
                                      source_type="imported", status="approved"))
                processed += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
