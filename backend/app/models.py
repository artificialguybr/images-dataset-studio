import json
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlmodel import JSON, Column, Field, SQLModel


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Dataset(SQLModel, table=True):
    __tablename__ = "datasets"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    owner: str = "local"
    source_type: str = "local"           # local | zip | imported | cloud
    source_uri: str = ""
    license: str = "unknown"
    license_evidence_uri: str = ""
    license_policy: str = "permissive"  # permissive | strict (bloqueia export com licença unknown)
    thresholds_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    current_version_id: Optional[str] = Field(default=None, foreign_key="dataset_versions.id")
    status: str = "active"              # active | archived
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ImageItem(SQLModel, table=True):
    __tablename__ = "image_items"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    source_uri: str                      # original path/origin, never rewritten
    storage_uri: str = ""                # where bytes live inside data/
    original_filename: str = Field(index=True)
    relative_path: str = ""
    mime_type: str = ""
    byte_size: int = 0
    content_hash_sha256: str = Field(default="", index=True)
    perceptual_hash: str = ""
    width: int = 0
    height: int = 0
    channels: int = 0
    mode: str = ""
    exif_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    tags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    license: str = "unknown"             # herdada do dataset; sobrescrevível por item
    license_evidence_uri: str = ""
    ingest_status: str = "pending"        # pending | done | error
    ingest_error: str = ""
    decision_status: str = "keep"        # keep | review | quarantine | reject | restore
    quarantine_reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ImageIssue(SQLModel, table=True):
    __tablename__ = "image_issues"
    id: str = Field(default_factory=new_id, primary_key=True)
    image_id: str = Field(foreign_key="image_items.id", index=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    issue_type: str = Field(index=True)
    score: float = 0.0
    threshold: float = 0.0
    detector_name: str = ""
    detector_version: str = ""
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "open"                  # open | acknowledged | dismissed
    created_at: datetime = Field(default_factory=utcnow)
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None


class DuplicateGroup(SQLModel, table=True):
    __tablename__ = "duplicate_groups"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    method: str = "sha256"                # sha256 | phash | embedding
    threshold: float = 0.0
    model_name: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class DuplicateMember(SQLModel, table=True):
    __tablename__ = "duplicate_members"
    id: str = Field(default_factory=new_id, primary_key=True)
    group_id: str = Field(foreign_key="duplicate_groups.id", index=True)
    image_id: str = Field(foreign_key="image_items.id", index=True)
    similarity: float = 1.0
    is_canonical: bool = False
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    decision: str = "pending"             # pending | keep_canonical | quarantine_member


class Label(SQLModel, table=True):
    __tablename__ = "labels"
    id: str = Field(default_factory=new_id, primary_key=True)
    image_id: str = Field(foreign_key="image_items.id", index=True)
    label_type: str = "classification"      # classification | bbox | polygon | mask | keypoint
    category: str = Field(index=True)
    geometry_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    value_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source_type: str = "human"             # human | model | imported | rule | unknown
    source_id: str = ""
    confidence: Optional[float] = None
    status: str = "approved"               # approved | pending | rejected
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = "local"
    superseded_at: Optional[datetime] = None
    supersedes_id: Optional[str] = None

class Caption(SQLModel, table=True):
    __tablename__ = "captions"
    id: str = Field(default_factory=new_id, primary_key=True)
    image_id: str = Field(foreign_key="image_items.id", index=True)
    text: str = ""
    prompt: str = ""
    prefix: str = ""
    suffix: str = ""
    template: str = "{caption}"
    source_type: str = "model"          # model | human | imported
    source_id: str = ""
    confidence: Optional[float] = None
    status: str = "pending"             # pending | approved | rejected
    superseded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class ReviewDecision(SQLModel, table=True):
    __tablename__ = "review_decisions"
    id: str = Field(default_factory=new_id, primary_key=True)
    target_type: str = "item"              # item | issue | label | duplicate_group
    target_id: str = Field(index=True)
    reviewer_id: str = "local"
    decision: str = "keep"                 # keep | review | quarantine | reject | restore | approve | dismiss
    reason: str = ""
    comment: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class DatasetVersion(SQLModel, table=True):
    __tablename__ = "dataset_versions"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    parent_version_id: Optional[str] = None
    manifest_uri: str = ""
    item_count: int = 0
    checksum: str = ""
    description: str = ""
    snapshot_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class ExportRecord(SQLModel, table=True):
    __tablename__ = "export_records"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    fmt: str = "imagefolder"
    version_id: str = ""
    path: str = ""
    item_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: str = Field(default_factory=new_id, primary_key=True)
    type: str = Field(index=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    status: str = "queued"                  # queued | running | completed | failed | cancelled
    progress: float = 0.0
    total: int = 0
    processed: int = 0
    failed: int = 0
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error_summary: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
