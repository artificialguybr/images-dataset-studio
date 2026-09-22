"""Export: pasta organizada + manifest JSONL + CSV + labels + relatório.

Formatos: imagefolder (com classes por label de classificação aprovada).
COCO/YOLO ficam como adaptadores de saída simples bbox-only.
"""
import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..config import get_settings
from ..models import Caption, Dataset, DatasetVersion, ExportRecord, ImageItem, ImageIssue, Label
from ..services.paths import item_path

def _active_items(session: Session, dataset_id: str) -> list[ImageItem]:
    return session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id,
        ImageItem.decision_status.in_(("keep", "restore")))).all()


def _labels(session: Session, image_id: str) -> list[Label]:
    return session.exec(select(Label).where(
        Label.image_id == image_id, Label.status == "approved")).all()


def _caption(session: Session, image_id: str) -> Caption | None:
    return session.exec(select(Caption).where(
        Caption.image_id == image_id, Caption.superseded_at.is_(None),
        Caption.status == "approved"
    ).order_by(Caption.created_at.desc())).first()


def export(session: Session, dataset_id: str, fmt: str = "imagefolder",
          version_id: str | None = None) -> dict[str, Any]:
    s = get_settings()
    ds = session.get(Dataset, dataset_id)
    assert ds is not None
    version = session.get(DatasetVersion, version_id) if version_id else None
    # sem version_id: exporta o estado VIVO (keep|restore atuais);
    # version_id explícito: pacote reflete o snapshot do checkpoint.

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = s.exports_dir / dataset_id[:8] / f"{fmt}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fase 9.2.6/§10: policy exige licença válida => bloqueia itens com licença 'unknown'
    policy = (ds.license_policy or "permissive").lower()
    items = _active_items(session, dataset_id)
    if policy == "strict":
        bad = [it for it in items if (it.license or "unknown") == "unknown"]
        if bad:
            raise RuntimeError(
                f"strict license policy blocks export: {len(bad)} items have no defined license. "
                f"Set licenses or PATCH dataset.license_policy='permissive'.")

    # Export versionado (§12): quando um checkpoint explícito é pedido, o pacote
    # reflete o snapshot do checkpoint — itens, labels e decisions da época —
    # não o estado vivo atual. Metadados vivos (mime/nome/licença) são lidos
    # por id; bytes vêm do mesmo item_path de sempre.
    snap_labels: dict[str, list[dict[str, Any]]] = {}
    snap_decision: dict[str, str] = {}
    if version_id and version and version.snapshot_json:
        wanted = [e["item_id"] for e in version.snapshot_json]
        by_id = {it.id: it for it in items}
        items = [by_id[i] for i in wanted if i in by_id]  # snapshot pode referenciar itens removidos
        for e in version.snapshot_json:
            snap_labels[e["item_id"]] = e.get("labels", [])
            snap_decision[e["item_id"]] = e.get("decision", "")
    counts = {"keep": 0, "quarantine": 0, "reject": 0, "review": 0}
    all_items = session.exec(select(ImageItem).where(
        ImageItem.dataset_id == dataset_id)).all()
    for it in all_items:
        if it.decision_status in counts:
            counts[it.decision_status] += 1

    def _item_labels(it: ImageItem) -> list[Label]:
        if it.id in snap_labels:
            # labels do snapshot são dicts plain; os consumidores do manifest
            # esperam o mesmo shape dos labels vivos — reconstruímos o mínimo.
            return [Label(  # type: ignore[call-arg]
                id=lb["id"], label_type=lb["type"], category=lb["category"],
                source_type=lb["source_type"], status=lb["status"])
                for lb in snap_labels[it.id]]
        return _labels(session, it.id)

    def _item_decision(it: ImageItem) -> str:
        return snap_decision.get(it.id) or it.decision_status

    manifest_rows: list[dict[str, Any]] = []
    class_dirs: set[str] = set()
    for it in items:
        src = item_path(it)
        labels = _item_labels(it)
        cats = [lb.category for lb in labels if lb.label_type == "classification"] or ["unlabeled"]
        rel = Path("images") / f"{it.id}{src.suffix.lower()}"
        if fmt == "imagefolder":
            cat = cats[0].replace("/", "_") or "unlabeled"
            class_dirs.add(cat)
            rel = Path(cat) / f"{it.id}{src.suffix.lower()}"
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)
        caption = _caption(session, it.id)
        manifest_rows.append({
            "item_id": it.id, "source_uri": it.source_uri,
            "output_uri": str(rel), "sha256": it.content_hash_sha256,
            "width": it.width, "height": it.height,
            "caption": caption.text if caption else "",
            "caption_model": caption.source_id if caption else "",
            "labels": [{"type": lb.label_type, "category": lb.category,
                        "geometry": lb.geometry_json,
                        "value": lb.value_json or None,
                        "source_type": lb.source_type, "model": lb.source_id,
                        "confidence": lb.confidence}
                       for lb in labels],
            "tags": it.tags_json, "decision": _item_decision(it),
            "dataset_version": version.id if version else "",
        })

    for r in manifest_rows:
        r["exported_by"] = "local-operator"  # sem auth: operador fixo; roadmap: user logado
        r["pipeline_version"] = "0.1.0"
    manifest_path = out_dir / "manifest.jsonl"
    manifest_path.write_text("\n".join(json.dumps(r) for r in manifest_rows), encoding="utf-8")
    # manifest.csv (Fase 12)
    if manifest_rows:
        with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
            w.writeheader()
            w.writerows(manifest_rows)

    # labels em CSV separado
    with (out_dir / "labels.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "label_type", "category", "source_type", "model", "confidence", "status"])
        for it in items:
            for lb in _item_labels(it):
                w.writerow([it.id, lb.label_type, lb.category, lb.source_type,
                            lb.source_id, lb.confidence or "", lb.status])

    # OCR estruturado: texto + geometria por item
    ocr_rows = [(it, lb) for it in items for lb in _item_labels(it)
                if lb.label_type == "text"]
    with (out_dir / "ocr.jsonl").open("w", encoding="utf-8") as fh:
        for it, lb in ocr_rows:
            fh.write(json.dumps({
                "item_id": it.id, "output_uri": f"images/{it.id}",
                "text": lb.value_json.get("text", ""),
                "bbox": lb.geometry_json, "confidence": lb.confidence,
                "model": lb.source_id, "source_type": lb.source_type,
            }) + "\n")

    # Training captions: approved text plus provenance, with sidecars beside each image.
    caption_rows = []
    for it in items:
        caption = _caption(session, it.id)
        if not caption:
            continue
        row = {"item_id": it.id, "output_uri": str(Path("captions") / f"{it.id}.txt"),
               "text": caption.text, "model": caption.source_id,
               "confidence": caption.confidence, "source_type": caption.source_type}
        caption_rows.append(row)
        (out_dir / "captions").mkdir(exist_ok=True)
        (out_dir / "captions" / f"{it.id}.txt").write_text(caption.text + "\n", encoding="utf-8")
        if fmt == "imagefolder":
            image_path = next((p for p in out_dir.rglob(f"{it.id}.*") if p.suffix != ".txt"), None)
            if image_path:
                image_path.with_suffix(".txt").write_text(caption.text + "\n", encoding="utf-8")
    (out_dir / "captions.jsonl").write_text(
        "\n".join(json.dumps(row) for row in caption_rows) + ("\n" if caption_rows else ""),
        encoding="utf-8")

    # COCO (bboxes)
    if fmt in ("coco", "imagefolder"):
        coco = _build_coco(session, items, label_of=_item_labels)
        (out_dir / "coco_annotations.json").write_text(json.dumps(coco), encoding="utf-8")
    # YOLO (bboxes normalizados)
    if fmt in ("yolo", "imagefolder"):
        _write_yolo(session, out_dir, items, label_of=_item_labels)
    # Parquet (Fase 12): pyarrow é dependência core — export sempre funcional.
    # pyarrow não serializa dicts heterogêneos como struct; campos compostos
    # viram JSON string (colunas planas + JSON é o formato canônico do parquet).
    if fmt in ("parquet", "imagefolder"):
        import pyarrow as pa
        import pyarrow.parquet as pq
        if manifest_rows:
            scalar = ("item_id", "source_uri", "output_uri", "sha256",
                      "caption", "caption_model", "decision",
                      "dataset_version", "exported_by", "pipeline_version")
            cols = {
                k: [json.dumps(r.get(k)) if k not in scalar else r.get(k)
                     for r in manifest_rows]
                for k in manifest_rows[0].keys()}
            table = pa.table(cols)
            pq.write_table(table, out_dir / "manifest.parquet")

    # relatório de limpeza
    issues = session.exec(select(ImageIssue).where(
        ImageIssue.dataset_id == dataset_id)).all()
    by_type: dict[str, int] = {}
    for iss in issues:
        by_type[iss.issue_type] = by_type.get(iss.issue_type, 0) + 1
    report = {
        "dataset": {"id": dataset_id, "name": ds.name, "version": version.id if version else None},
        "exported_items": len(manifest_rows),
        "decisions": counts,
        "issues_by_type": by_type,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    # pacote único para download/handoff
    zip_path = shutil.make_archive(str(out_dir), "zip", out_dir)

    # ledger de export em DB + retenção: 5 mais recentes por dataset+fmt.
    # Economia de disco: o export MAIS recente fica com dir aberto + zip;
    # os demais kept viram somente .zip (dir extraído é redundante —
    # basta descompactar); registros além dos 5 saem junto com dir e zip.
    rec = ExportRecord(dataset_id=dataset_id, fmt=fmt,
                     version_id=version.id if version else "",
                     path=str(out_dir), item_count=len(manifest_rows))
    session.add(rec)
    session.commit()
    old_recs = session.exec(select(ExportRecord).where(
        ExportRecord.dataset_id == dataset_id, ExportRecord.fmt == fmt)
        .order_by(ExportRecord.created_at.desc())).all()  # type: ignore[attr-defined]
    keep_list: list[str] = []
    for r in old_recs:
        if len(keep_list) < 5 and (Path(r.path).is_dir()
                                or Path(str(r.path) + '.zip').exists()):
            keep_list.append(r.id)
        elif r.id != rec.id:
            shutil.rmtree(r.path, ignore_errors=True)
            Path(str(r.path) + ".zip").unlink(missing_ok=True)
            session.delete(r)
    session.commit()
    keep_paths: set[str] = set()
    for i, rid in enumerate(keep_list):
        r = session.get(ExportRecord, rid)
        zp = str(r.path) + ".zip"
        if Path(zp).exists():
            keep_paths.add(zp)
        if i == 0:
            keep_paths.add(r.path)  # dir aberto apenas no mais recente
        else:
            shutil.rmtree(r.path, ignore_errors=True)  # zip basta para os antigos
    for p in (s.exports_dir / dataset_id[:8]).glob(f"{fmt}-*"):
        if str(p) not in keep_paths:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    return {"path": str(out_dir), "zip_path": zip_path, "items": len(manifest_rows),
            "report": report, "export_id": rec.id}


def _polygon_area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_bbox(points: list[tuple[float, float]]) -> list[float]:
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    x, y = min(xs), min(ys)
    return [x, y, max(xs) - x, max(ys) - y]


def _build_coco(session: Session, items: list[ImageItem], label_of=None) -> dict[str, Any]:
    images, annotations = [], []
    cat_ids: dict[str, int] = {}
    ann_id = 1
    for idx, it in enumerate(items, start=1):
        images.append({"id": idx, "file_name": f"{it.id}", "width": it.width, "height": it.height})
        for lb in (label_of(it) if label_of else _labels(session, it.id)):
            if lb.label_type not in ("bbox", "polygon"):
                continue
            cat_ids.setdefault(lb.category, len(cat_ids) + 1)
            g = lb.geometry_json
            if lb.label_type == "bbox":
                x, y, w, h = g.get("x", 0), g.get("y", 0), g.get("w", 0), g.get("h", 0)
                annotations.append({"id": ann_id, "image_id": idx,
                                  "category_id": cat_ids[lb.category],
                                  "bbox": [x, y, w, h], "area": w * h,
                                  "iscrowd": 0})
            else:
                points = [(p["x"], p["y"]) for p in g.get("points", []) if "x" in p and "y" in p]
                if len(points) < 3:
                    continue
                flat = [round(v, 2) for xy in points for v in xy]
                annotations.append({"id": ann_id, "image_id": idx,
                                  "category_id": cat_ids[lb.category],
                                  "segmentation": [flat], "bbox": _polygon_bbox(points),
                                  "area": _polygon_area(points), "iscrowd": 0})
            ann_id += 1
    return {"images": images, "annotations": annotations,
            "categories": [{"id": i, "name": n} for n, i in cat_ids.items()]}


def _write_yolo(session: Session, out_dir: Path, items: list[ImageItem], label_of=None) -> None:
    labels_dir = out_dir / "labels"
    labels_dir.mkdir(exist_ok=True)
    cats: dict[str, int] = {}
    for it in items:
        lines = []
        for lb in (label_of(it) if label_of else _labels(session, it.id)):
            if lb.label_type != "bbox":
                continue
            cats.setdefault(lb.category, len(cats))
            g = lb.geometry_json
            xc = (g.get("x", 0) + g.get("w", 0) / 2) / max(1, it.width)
            yc = (g.get("y", 0) + g.get("h", 0) / 2) / max(1, it.height)
            w = g.get("w", 0) / max(1, it.width)
            h = g.get("h", 0) / max(1, it.height)
            lines.append(f"{cats[lb.category]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
        (labels_dir / f"{it.id}.txt").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "classes.txt").write_text("\n".join(cats.keys()), encoding="utf-8")
