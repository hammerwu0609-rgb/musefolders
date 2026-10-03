"""Fixed-library web demo: immutable shared sources, isolated visitor workspace."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Lock
import time

from .intent_assistant import IntentAssistantError

FIXED_ARTIFACTS = ("user_annotations.json", "platform_catalog.json", "ai_lyrics_tags.json", "artist_regions.json")


def prepare_workspace(bundle: Path, destination: Path) -> Path:
    bundle = bundle.resolve()
    audio = (bundle / "audio").resolve()
    raw = json.loads((bundle / "collection_plan.json").read_text(encoding="utf-8"))
    if not raw.get("tracks"):
        raise ValueError("Demo library is empty")
    for track in raw["tracks"]:
        relative = Path(track["source_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid demo audio path")
        path = (bundle / relative).resolve()
        if not path.is_relative_to(audio) or not path.is_file():
            raise ValueError("Missing demo audio file")
        track["source_path"] = str(path)
    raw["source_root"] = str(audio)
    artifacts = destination / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "collection_plan.json").write_text(json.dumps(raw,ensure_ascii=False),encoding="utf-8")
    for name in FIXED_ARTIFACTS:
        if (bundle / name).is_file():
            shutil.copy2(bundle / name, artifacts / name)
    if (bundle / "platform_lyrics").is_dir():
        shutil.copytree(bundle / "platform_lyrics", artifacts / "platform_lyrics", dirs_exist_ok=True)
    return destination


@dataclass
class DemoBudget:
    requests: deque = field(default_factory=deque)
    lock: Lock = field(default_factory=Lock)

    def acquire(self, session_requests: list, *, now: float | None = None, hourly: int = 100, minute: int = 5):
        now = time.monotonic() if now is None else now
        with self.lock:
            while self.requests and self.requests[0] <= now-3600:
                self.requests.popleft()
            session_requests[:] = [stamp for stamp in session_requests if stamp > now-60]
            if len(session_requests) >= minute:
                raise IntentAssistantError("演示版每分钟最多进行 5 次 AI 检索，请稍等片刻；地图和试听仍可使用。")
            if len(self.requests) >= hourly:
                raise IntentAssistantError("演示版本小时的 AI 请求额度已用完，请稍后再试；地图和试听仍可使用。")
            self.requests.append(now)
            session_requests.append(now)


_BUDGET = DemoBudget()


def check_ai_budget():
    import streamlit as st
    if st.session_state.get("simple_demo_mode"):
        stamps = st.session_state.setdefault("demo_ai_requests", [])
        _BUDGET.acquire(stamps, hourly=max(1,int(os.getenv("MUSEFOLDERS_AI_HOURLY_LIMIT", "100"))))


def portable_playlist_bytes(tracks) -> bytes:
    lines = ["#EXTM3U"]
    for track in tracks:
        title = (track.metadata.title + " - " + track.metadata.artist).replace("\n", " ").replace("\r", " ")
        lines.extend([f"#EXTINF:{round(track.acoustic.duration_s)},{title}", Path(track.source_path).name])
    return ("\n".join(lines)+"\n").encode("utf-8-sig")


def render_demo(bundle: Path):
    import streamlit as st
    from .simple_ui import render_app
    st.session_state.simple_demo_mode = True
    st.session_state.simple_demo_bundle = str(bundle)
    if "demo_workspace" not in st.session_state:
        temporary = TemporaryDirectory(prefix="musefolders-visitor-")
        st.session_state.demo_workspace = temporary
        try:
            prepare_workspace(bundle, Path(temporary.name))
        except (OSError, ValueError, KeyError):
            st.error("演示曲库尚未准备完成，请稍后刷新。")
            st.stop()
    render_app(Path(st.session_state.demo_workspace.name))
