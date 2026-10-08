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


DRAFT_VERSION = 2
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
class DraftEntry:
    entry_id: str
    kind: str
    label: str
    source: dict
    members: list[DraftItem]


@dataclass(slots=True)
class PlaylistDraft:
    source_root: str
    analysis_id: str
    name: str = ""
    items: list[DraftItem] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    version: int = DRAFT_VERSION
    entries: list[DraftEntry] = field(default_factory=list)
    order: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.entries and self.items:
            unique = {}
            for item in self.items:
                unique.setdefault(item.content_id, item)
            self.entries = [_single_entry(item) for item in unique.values()]
        rebuild_items(self)

    def to_dict(self) -> dict:
        rebuild_items(self)
        return {
            "version": self.version, "source_root": self.source_root,
            "analysis_id": self.analysis_id, "name": self.name,
            "items": [asdict(item) for item in self.items],
            "entries": [asdict(entry) for entry in self.entries],
            "excluded": list(self.excluded), "filters": dict(self.filters),
            "order": list(self.order),
        }


def _single_entry(item: DraftItem) -> DraftEntry:
    identity = hashlib.sha256(item.content_id.encode()).hexdigest()[:24]
    return DraftEntry("single-" + identity, "single", item.title,
                      {"kind": "single", "label": "单曲加入"}, [item])


def rebuild_items(draft: PlaylistDraft) -> None:
    """Entries are sources of truth; the legacy item list is a deduplicated view."""
    seen = set()
    items = []
    for entry in draft.entries:
        for item in entry.members:
            if item.content_id not in seen:
                items.append(item)
                seen.add(item.content_id)
    ranks = {content: i for i, content in enumerate(draft.order)}
    items.sort(key=lambda item: ranks.get(item.content_id, len(ranks)))
    draft.items = items
    draft.order = [item.content_id for item in items]
    draft.version = DRAFT_VERSION


def set_single(draft: PlaylistDraft, plan: CollectionPlan, track_id: str, selected: bool) -> bool:
    track = plan.track_by_id().get(track_id)
    if track is None or not isinstance(selected, bool):
        raise ValueError("请选择当前曲库中的有效歌曲。")
    item = DraftItem.from_track(track, "consumer_single")
    existing = [e for e in draft.entries if e.kind == "single" and
                e.members[0].content_id == item.content_id]
    was_excluded = item.content_id in draft.excluded
    if selected and not existing:
        draft.entries.append(_single_entry(item))
    elif not selected:
        draft.entries = [e for e in draft.entries if e not in existing]
    if selected:
        draft.excluded = [c for c in draft.excluded if c != item.content_id]
    draft.analysis_id = plan.analysis_id
    rebuild_items(draft)
    return selected and (not existing or was_excluded)


def add_group(draft: PlaylistDraft, plan: CollectionPlan, ids: list[str], source: dict) -> bool:
    if not isinstance(source, dict) or source.get("kind") not in {
            "country", "energy", "themes", "star", "search", "selection", "library"}:
        raise ValueError("板块来源无效，请重新选择。")
    label = source.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > 100:
        raise ValueError("板块名称无效。")
    encoded = json.dumps(source, ensure_ascii=False, allow_nan=False)
    if len(encoded) > 10000 or not isinstance(source.get("description", ""), str):
        raise ValueError("板块特征无效。")
    by_id = plan.track_by_id()
    members, seen = [], set()
    for tid in ids:
        if tid not in by_id:
            raise ValueError("板块包含已失效的歌曲，请重新选择。")
        item = DraftItem.from_track(by_id[tid], "consumer_group")
        if item.content_id not in seen:
            members.append(item)
            seen.add(item.content_id)
    if not members:
        raise ValueError("这个板块没有歌曲可加入。")
    signature = {"kind": source["kind"], "key": source.get("key", label),
                 "criteria": source.get("criteria", {}), "members": sorted(seen)}
    identity = "group-" + hashlib.sha256(json.dumps(signature, sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:24]
    if any(e.entry_id == identity for e in draft.entries):
        restored = any(c in draft.excluded for c in seen)
        draft.excluded = [c for c in draft.excluded if c not in seen]
        draft.analysis_id = plan.analysis_id
        rebuild_items(draft)
        return restored
    draft.entries.append(DraftEntry(identity, "group", label.strip(), json.loads(encoded), members))
    draft.excluded = [c for c in draft.excluded if c not in seen]
    draft.analysis_id = plan.analysis_id
    rebuild_items(draft)
    return True


def remove_entry(draft: PlaylistDraft, identity: str) -> None:
    if not any(e.entry_id == identity for e in draft.entries):
        raise ValueError("该预备歌单条目已不存在。")
    draft.entries = [e for e in draft.entries if e.entry_id != identity]
    rebuild_items(draft)


def move_entry(draft: PlaylistDraft, identity: str, offset: int) -> None:
    if offset not in (-1, 1):
        raise ValueError("歌单移动方向无效。")
    index = next((i for i, e in enumerate(draft.entries) if e.entry_id == identity), None)
    if index is None:
        raise ValueError("该预备歌单条目已不存在。")
    target = max(0, min(len(draft.entries) - 1, index + offset))
    draft.entries.insert(target, draft.entries.pop(index))
    draft.order = []
    rebuild_items(draft)


def delete_song(draft: PlaylistDraft, content_id: str) -> None:
    """Remove a recording from every active source, retaining provenance for undo."""
    if not any(item.content_id == content_id for item in draft.items) or content_id in draft.excluded:
        raise ValueError("这首歌曲已不在预备歌单中。")
    draft.excluded.append(content_id)


def move_song(draft: PlaylistDraft, content_id: str, offset: int) -> None:
    if type(offset) is not int or offset not in (-1, 1):
        raise ValueError("歌曲移动方向无效。")
    rebuild_items(draft)
    active = [c for c in draft.order if c not in draft.excluded]
    if content_id not in active:
        raise ValueError("这首歌曲已不在预备歌单中。")
    index = active.index(content_id)
    target = max(0, min(len(active) - 1, index + offset))
    if target != index:
        other = active[target]
        a, b = draft.order.index(content_id), draft.order.index(other)
        draft.order[a], draft.order[b] = draft.order[b], draft.order[a]
    rebuild_items(draft)


def draft_path(artifacts: Path, source_root: str) -> Path:
    digest = hashlib.sha256(str(Path(source_root).resolve()).casefold().encode("utf-8")).hexdigest()[:20]
    return artifacts / "playlist_drafts" / f"{digest}.json"


def load_draft(artifacts: Path, plan: CollectionPlan) -> PlaylistDraft:
    path = draft_path(artifacts, plan.source_root)
    if not path.is_file():
        return PlaylistDraft(plan.source_root, plan.analysis_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") not in {1, DRAFT_VERSION} or data.get("source_root") != plan.source_root:
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
    entries = []
    if data.get("version") == DRAFT_VERSION:
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list) or len(raw_entries) > 100000:
            raise ValueError("Invalid playlist entries")
        identities = set()
        total = 0
        for raw in raw_entries:
            if (not isinstance(raw, dict) or not isinstance(raw.get("entry_id"), str) or
                    raw["entry_id"] in identities or raw.get("kind") not in {"single", "group"} or
                    not isinstance(raw.get("label"), str) or not isinstance(raw.get("source"), dict) or
                    not isinstance(raw.get("members"), list) or not raw["members"]):
                raise ValueError("Invalid playlist entry")
            members = []
            for member in raw["members"]:
                if not isinstance(member, dict) or not all(isinstance(member.get(k), str)
                        for k in ("track_id", "content_id", "title", "origin")):
                    raise ValueError("Invalid playlist member")
                members.append(DraftItem(**{k: member[k] for k in
                    ("track_id", "content_id", "title", "origin")}))
            total += len(members)
            if total > 100000 or (raw["kind"] == "single" and len(members) != 1):
                raise ValueError("Invalid playlist member count")
            entries.append(DraftEntry(raw["entry_id"], raw["kind"], raw["label"], raw["source"], members))
            identities.add(raw["entry_id"])
        items = []  # Never reconstruct v2 sources from its derived compatibility list.
    return PlaylistDraft(
        plan.source_root, str(data.get("analysis_id", "")),
        str(data.get("name", ""))[:80], items,
        [value for value in data.get("excluded", []) if isinstance(value, str)],
        data.get("filters", {}) if isinstance(data.get("filters", {}), dict) else {},
        entries=entries,
        order=[c for c in data.get("order", []) if isinstance(c, str)]
            if isinstance(data.get("order", []), list) else [],
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
    rebuild_items(draft)
    return reconcile_members(draft.items, plan)


def reconcile_members(items: list[DraftItem], plan: CollectionPlan) -> tuple[list[str], list[DraftItem]]:
    by_id = plan.track_by_id()
    by_content: dict[str, TrackEncoding] = {}
    for track in plan.tracks:
        by_content.setdefault(track.source_sha256 or track.track_id, track)
    found: list[str] = []
    missing: list[DraftItem] = []
    for item in items:
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
        draft.entries = [_single_entry(item) for item in incoming]
        draft.excluded = []
        draft.order = []
    elif mode == "intersect":
        draft.entries = [_single_entry(item) for item in draft.items if item.content_id in seen]
    else:
        known = {e.members[0].content_id for e in draft.entries if e.kind == "single"}
        draft.entries.extend(_single_entry(item) for item in incoming if item.content_id not in known)
        draft.excluded = [content for content in draft.excluded if content not in seen]
    draft.analysis_id = plan.analysis_id
    rebuild_items(draft)
    return draft


def move_item(draft: PlaylistDraft, content_id: str, offset: int) -> None:
    for entry in draft.entries:
        if entry.kind == "single" and entry.members[0].content_id == content_id:
            move_entry(draft, entry.entry_id, offset)
            return
    for entry in draft.entries:
        index = next((i for i, item in enumerate(entry.members) if item.content_id == content_id), None)
        if index is not None:
            target = max(0, min(len(entry.members) - 1, index + offset))
            entry.members.insert(target, entry.members.pop(index))
            draft.order = []
            rebuild_items(draft)
            return
