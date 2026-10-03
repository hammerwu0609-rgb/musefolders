"""Consumer UI data and local actions; no secrets or local audio paths in the payload."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from .astrology import build_zodiac, ZODIAC_LABELS
from .playlist_draft import PlaylistDraft, apply_selection, reconcile, move_item, save_draft, load_draft
from .playlist_filters import safe_playlist_name
from .artist_regions import read_regions, region_for_artist, REGIONS


def parse_command(text: str) -> tuple[str, str, str]:
    """Split playlist commands from the search description sent to the model."""
    text = text.strip()
    if not text or len(text) > 500:
        raise ValueError("请输入 1–500 字的描述。")
    name_match = re.search(r'[「“\"]([^」”\"]{1,60})[」”\"]', text)
    name = name_match.group(1) if name_match else "新歌单"
    if re.search(r"(?:新建|创建|生成|建一个|建成|建为).{0,50}歌单|歌单.{0,20}(?:新建|创建|生成)", text):
        query = re.sub(r'[「“\"][^」”\"]+[」”\"]', "", text)
        descriptive = re.fullmatch(r"(?:帮我|给我)?(?:新建|创建|生成)(?:一[个张份])?(?:关于)?(.+?)(?:的)?歌单", query)
        query = re.sub(r"(?:，|,|。|；|;)?\s*(?:并|然后|帮我|给我|把这些歌|把搜索结果)?\s*(?:新建|创建|生成|建一个|建成|建为).*", "", query)
        query = re.sub(r"^(?:找|搜索|帮我找)", "", query).strip(" ，,。")
        if query in {"", "把这些歌", "把搜索结果", "这些歌", "搜索结果"}:
            query = ""
        if not query and descriptive:
            query = descriptive.group(1).removesuffix("的").strip()
        return "create", query, safe_playlist_name(name)
    if re.search(r"(?:加入|添加到|放进).{0,8}歌单", text):
        query = re.sub(r"^(?:把|将)", "", text)
        query = re.sub(r"(?:加入|添加到|放进).*", "", query).strip(" ，,。")
        return "add", "" if query in {"这些歌", "搜索结果"} else query, ""
    if re.search(r"(?:移除|移出|删除).{0,50}歌单|(?:从|在)歌单.{0,8}(?:移除|移出|删除)", text):
        query = re.sub(r"(?:从|在)歌单(?:中|里)?(?:移除|移出|删除)", "", text)
        query = re.sub(r"^(?:把|将|移除|移出|删除)", "", query)
        query = re.sub(r"(?:从|在)?歌单(?:中|里)?", "", query).strip(" ，,。")
        query = re.sub(r"(?:移除|移出|删除)$", "", query).strip()
        return "remove", query, ""
    return "search", text, ""


def archive_playlist(artifacts: Path, draft: PlaylistDraft) -> None:
    """Preserve the current playlist before creating or switching to another."""
    if not draft.items and not draft.name:
        return
    folder = artifacts / "saved_playlists"
    folder.mkdir(parents=True, exist_ok=True)
    # Re-saving a selected playlist updates its stable snapshot.
    # PlaylistDraft uses slots. The snapshot identity is tracked by content/name.
    import hashlib
    identity = hashlib.sha256((draft.source_root + "\0" + (draft.name or "我的歌单")).encode()).hexdigest()[:24]
    from dataclasses import asdict
    path = folder / f"{identity}.json"
    temporary = folder / f".{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(asdict(draft), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def saved_playlists(artifacts: Path, plan) -> list[dict]:
    result = []
    for path in sorted((artifacts / "saved_playlists").glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("source_root") == plan.source_root:
                result.append({"id": path.stem, "name": value.get("name") or "我的歌单", "count": len(value["items"])})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def switch_playlist(artifacts: Path, plan, draft: PlaylistDraft, identity: str) -> PlaylistDraft:
    if not re.fullmatch(r"[a-f0-9]{24}", identity):
        raise ValueError("请选择有效的本地歌单。")
    path = artifacts / "saved_playlists" / f"{identity}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_root") != plan.source_root:
        raise ValueError("这张歌单属于另一份曲库。")
    archive_playlist(artifacts, draft)
    # Reuse the strict existing draft loader rather than trust JSON item fields.
    from .playlist_draft import draft_path
    destination = draft_path(artifacts, plan.source_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".switch.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # Validate using a separate artifact root before touching the current draft.
    validation_root = artifacts / "playlist_validation"
    candidate = draft_path(validation_root, plan.source_root)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    try:
        candidate.write_text(temporary.read_text(encoding="utf-8"), encoding="utf-8")
        loaded = load_draft(validation_root, plan)
        save_draft(artifacts, loaded)
        return loaded
    finally:
        temporary.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)


def edit_playlist(draft, plan, action: dict) -> None:
    kind = action.get("kind")
    track_id = action.get("id")
    track = plan.track_by_id().get(track_id)
    if kind in {"add", "remove", "move"} and track is None:
        raise ValueError("这首歌已不在当前曲库中。")
    if kind == "add":
        apply_selection(draft, plan, [track_id], "add", "consumer")
    elif kind == "remove":
        draft.items = [item for item in draft.items if item.content_id != (track.source_sha256 or track_id)]
    elif kind == "move":
        offset = action.get("offset")
        if offset not in (-1, 1):
            raise ValueError("歌单移动方向无效。")
        move_item(draft, track.source_sha256 or track_id, offset)
    elif kind == "rename":
        draft.name = safe_playlist_name(str(action.get("name", "")))
    else:
        raise ValueError("未知的歌单操作。")


def payload(plan, profiles, draft, sound, artifacts: Path, *, results=None, message="", ai_ready=False, audio=None, share=None):
    zodiac = build_zodiac(sound, plan.tracks)
    points = {point.track_id: point for point in sound.points}
    # Optional verified country facts: never infer geography from a language code.
    regions = read_regions(artifacts)
    numeric_regions = {row[0]:row for row in REGIONS.values()}
    map_regions = {}
    tracks = []
    for track in plan.tracks:
        p = profiles[track.track_id]
        point = points.get(track.track_id)
        fact = region_for_artist(regions,p.artist)
        country = fact.get("country") if isinstance(fact, dict) and fact.get("source") else None
        country = str(country).zfill(3) if country and str(country).isdigit() else None
        if country:
            numeric = numeric_regions.get(country)
            map_regions[country] = {'id':country, 'name':fact.get('label') or (numeric[1] if numeric else country),
                                    'center':fact.get('center') or (numeric[2] if numeric else None)}
        tracks.append({"id": track.track_id, "title": p.title, "artist": p.artist or "未知歌手",
                       "playable": Path(track.source_path).is_file(),
                       "qqUrl": "https://y.qq.com/n/ryqq/songDetail/" + p.platform_mid if p.platform_mid else "",
                       "album": p.album, "year": p.year, "duration": round(track.acoustic.duration_s),
                       "x": point.x if point else None, "y": point.y if point else None,
                       "activity": p.activity, "themes": [tag.label for tag in p.tags if tag.dimension == "theme"],
                       "country": country, "region": map_regions[country]['name'] if country else "来源待补充",
                       "regionSource":fact.get('source','') if country else ""})
    selected, missing = reconcile(draft, plan)
    selected = [tid for tid in selected if (plan.track_by_id()[tid].source_sha256 or tid) not in draft.excluded]
    return {"tracks": tracks, "regions":list(map_regions.values()), "analysis": plan.analysis_id, "aiReady": ai_ready,
            "playlist": {"name": draft.name or "我的歌单", "ids": selected, "missing": len(missing)},
            "savedPlaylists": saved_playlists(artifacts, plan),
            "results": None if results is None else {"query": results[1], "hits": [{"id": h.track_id, "reasons": list(h.reasons)} for h in results[2]]},
            "star": {"name": ZODIAC_LABELS['zh'][zodiac.sign] if zodiac.sign else "等待星群成形",
                     "measured": len(sound.points),
                     "status": zodiac.status, "nodes": zodiac.overlay_nodes, "edges": zodiac.overlay_edges},
            "message": message, "audio": audio, "share": share}
