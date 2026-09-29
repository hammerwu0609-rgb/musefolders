"""One local, versioned candidate playlist shared by maps and catalog tools."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from .models import CollectionPlan, TrackEncoding


DRAFT_VERSION = 1
SelectionMode = Literal["add", "intersect", "replace"]


@dataclass(slots=True)
class DraftItem:
    track_id: str
    content_id: str
    title: str
    origin: str

    @classmethod
    def from_track(cls, track: TrackEncoding, origin: str) -> "DraftItem":
        return cls(track.track_id, track.source_sha256 or track.track_id,
                   track.metadata.title, origin)


@dataclass(slots=True)
class PlaylistDraft:
    source_root: str
    analysis_id: str
    name: str = ""
    items: list[DraftItem] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    version: int = DRAFT_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version, "source_root": self.source_root,
            "analysis_id": self.analysis_id, "name": self.name,
            "items": [asdict(item) for item in self.items],
            "excluded": list(self.excluded), "filters": dict(self.filters),
        }


def draft_path(artifacts: Path, source_root: str) -> Path:
    digest = hashlib.sha256(str(Path(source_root).resolve()).casefold().encode("utf-8")).hexdigest()[:20]
    return artifacts / "playlist_drafts" / f"{digest}.json"


def load_draft(artifacts: Path, plan: CollectionPlan) -> PlaylistDraft:
    path = draft_path(artifacts, plan.source_root)
    if not path.is_file():
        return PlaylistDraft(plan.source_root, plan.analysis_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != DRAFT_VERSION or data.get("source_root") != plan.source_root:
        raise ValueError("Unsupported playlist draft version or source")
    items = []
    for raw in data.get("items", []):
        if not isinstance(raw, dict) or not all(isinstance(raw.get(key), str)
                for key in ("track_id", "content_id", "title", "origin")):
            raise ValueError("Invalid playlist draft item")
        items.append(DraftItem(**{key: raw[key] for key in
                                ("track_id", "content_id", "title", "origin")}))
    if len(items) > 100000 or not isinstance(data.get("excluded", []), list):
        raise ValueError("Invalid playlist draft size")
    return PlaylistDraft(
        plan.source_root, str(data.get("analysis_id", "")),
        str(data.get("name", ""))[:80], items,
        [value for value in data.get("excluded", []) if isinstance(value, str)],
        data.get("filters", {}) if isinstance(data.get("filters", {}), dict) else {},
    )


def save_draft(artifacts: Path, draft: PlaylistDraft) -> None:
    path = draft_path(artifacts, draft.source_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(draft.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(draft: PlaylistDraft, plan: CollectionPlan) -> tuple[list[str], list[DraftItem]]:
    """Re-find audio by fingerprint; never substitute a different recording."""
    by_id = plan.track_by_id()
    by_content: dict[str, TrackEncoding] = {}
    for track in plan.tracks:
        by_content.setdefault(track.source_sha256 or track.track_id, track)
    found: list[str] = []
    missing: list[DraftItem] = []
    for item in draft.items:
        exact = by_id.get(item.track_id)
        if exact and (exact.source_sha256 or exact.track_id) == item.content_id:
            found.append(exact.track_id)
        elif item.content_id in by_content:
            found.append(by_content[item.content_id].track_id)
        else:
            missing.append(item)
    return found, missing


def apply_selection(draft: PlaylistDraft, plan: CollectionPlan, ids: list[str],
                    mode: SelectionMode, origin: str) -> PlaylistDraft:
    if mode not in {"add", "intersect", "replace"}:
        raise ValueError("Unknown selection mode")
    by_id = plan.track_by_id()
    incoming: list[DraftItem] = []
    seen: set[str] = set()
    for track_id in ids:
        track = by_id.get(track_id)
        if track is None:
            continue
        item = DraftItem.from_track(track, origin)
        if item.content_id not in seen:
            incoming.append(item)
            seen.add(item.content_id)
    if mode == "replace":
        draft.items = incoming
        draft.excluded = []
    elif mode == "intersect":
        draft.items = [item for item in draft.items if item.content_id in seen]
    else:
        known = {item.content_id for item in draft.items}
        draft.items.extend(item for item in incoming if item.content_id not in known)
        draft.excluded = [content for content in draft.excluded if content not in seen]
    draft.analysis_id = plan.analysis_id
    return draft


def move_item(draft: PlaylistDraft, content_id: str, offset: int) -> None:
    index = next((i for i, item in enumerate(draft.items) if item.content_id == content_id), None)
    if index is None:
        return
    target = max(0, min(len(draft.items) - 1, index + offset))
    draft.items.insert(target, draft.items.pop(index))
