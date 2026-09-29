"""Local, optional lyric embeddings and a separate two-dimensional lyric map.

No lyric text is persisted: the cache contains only a hash and an embedding.
This module does not download a model unless the caller explicitly opts in.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import numpy as np

from .models import TrackEncoding


LYRICS_ENGINE_VERSION = "lyrics-v3-evidence-aware"
GTE_MODEL_ID = "Alibaba-NLP/gte-multilingual-base"
# Pin remote code to a reviewed, immutable repository revision rather than main.
GTE_REVISION = "f48be033386d222715f74de68ba1d31b51f19f3a"
SUPPORTED_LYRIC_SUFFIXES = frozenset({".lrc", ".txt"})
MIN_CONTENT_CHARS = 40
MAX_LYRIC_CHUNK_CHARS = 360
MAX_LYRIC_CHUNKS = 24
TITLE_WEIGHT = 0.2
LYRICS_WEIGHT = 0.8
PARTIAL_TITLE_WEIGHT = 0.6
PARTIAL_LYRICS_WEIGHT = 0.4
_EMBEDDED_SUFFIXES = frozenset({".mp3", ".flac", ".ogg", ".oga", ".opus"})
_EMBEDDED_COMMENT_KEYS = frozenset({"lyrics", "unsyncedlyrics", "unsynchronisedlyrics", "unsynchronizedlyrics", "syncedlyrics"})

# These are theme comparison anchors, not calibrated probabilities or factual labels.
THEME_PROMPTS: dict[str, str] = {
    "love": "关于恋爱、爱人、亲密关系和浪漫的歌曲。 Songs about romantic love, lovers, intimacy, and romance.",
    "family": "关于父母、孩子、家人、亲情和家庭陪伴的歌曲。 Songs about parents, children, family bonds, and home life.",
    "friendship": "关于朋友、友谊、知己和相互支持的歌曲。 Songs about friends, friendship, and mutual support.",
    "memory": "关于回忆、怀旧、往事和时间流逝的歌曲。 Songs about memories, nostalgia, and the passage of time.",
    "solitude": "关于孤独、寂寞、独处和失落的歌曲。 Songs about loneliness, solitude, and loss.",
    "hope": "关于希望、成长、重新开始和克服困难的歌曲。 Songs about hope, growth, and new beginnings.",
    "journey": "关于旅途、旅行、探索和远方的歌曲。 Songs about travel, journeys, exploration, and distant places.",
    "celebration": "关于欢聚、派对、快乐和庆祝的歌曲。 Songs about gathering, parties, joy, and celebration.",
    "nature": "关于森林、海洋、山川、天空和自然景象的歌曲。 Songs about forests, oceans, mountains, sky, and nature.",
}

# A title can suggest a theme but is never treated as lyric evidence. The cues
# deliberately favor precision over coverage: evocative but ambiguous titles
# (for example "Home" or "雨") stay unassigned until lyrics or a person help.
_TITLE_CUES: dict[str, tuple[str, ...]] = {
    "love": ("爱情", "恋人", "恋爱", "暗恋", "爱你", "情人", "心动", "恋愛", "愛して", "love", "lover", "loving", "romance", "beloved"),
    "family": ("亲情", "家人", "亲人", "母亲", "妈妈", "父亲", "爸爸", "父と母", "家族", "mother", "father", "family", "mama"),
    "friendship": ("友情", "友谊", "朋友", "知己", "友達", "友だち", "friend", "friends", "friendship", "friendships"),
    "memory": ("回忆", "往事", "怀念", "童年", "记忆", "想い出", "思い出", "記憶", "memory", "memories", "remember", "nostalgia", "yesterday"),
    "solitude": ("孤独", "寂寞", "孤单", "独自", "lonely", "alone", "solitude"),
    "hope": ("希望", "成长", "重生", "明天", "未来", "hope", "tomorrow", "rebirth"),
    "journey": ("旅途", "路途", "旅行", "远方", "出发", "旅程", "journey", "travel", "voyage"),
    "celebration": ("庆祝", "舞会", "欢聚", "派对", "celebrate", "party", "festival"),
    "nature": ("森林", "海洋", "山川", "星空", "自然", "forest", "ocean", "mountain", "nature"),
}
_GENERIC_TITLES = frozenset({
    "", "song", "track", "music", "untitled", "unknown", "instrumental",
    "audio", "test", "missing", "short", "home", "rain", "雨", "歌", "歌曲", "无题", "纯音乐",
})

_LRC_TIMESTAMP = re.compile(r"\[(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
_KARAOKE_TIMESTAMP = re.compile(r"<(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?>")
_LRC_HEADER = re.compile(r"^\[(?:ar|al|ti|by|offset|length|re|ve|au|la|作词|作曲)\s*:[^\]]*\]$", re.IGNORECASE)
_SECTION_HEADER = re.compile(r"^\[(?:verse|chorus|bridge|intro|outro|hook|interlude|pre-chorus)(?:\s+\d+)?\]$", re.IGNORECASE)


class LyricsModelUnavailable(RuntimeError):
    """The optional local text model or its weights are not installed."""


class LyricsLanguageModelUnavailable(RuntimeError):
    """The optional local language model or its runtime is not installed."""


class LyricEmbedder(Protocol):
    model_version: str

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class LyricLanguageDetector(Protocol):
    model_version: str

    def predict(self, text: str) -> tuple[str, float]: ...


class FastTextLanguageDetector:
    """Opt-in, local fastText language detection; never downloads model weights."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self.model_version = f"fasttext-lid:{self.model_path.name}"
        self._model = None

    def predict(self, text: str) -> tuple[str, float]:
        if self._model is None:
            if not self.model_path.is_file():
                raise LyricsLanguageModelUnavailable("本地语言识别模型文件不存在。")
            try:
                import fasttext
            except ImportError as exc:
                raise LyricsLanguageModelUnavailable("语言识别需要可选依赖 fasttext。") from exc
            try:
                self._model = fasttext.load_model(str(self.model_path))
            except (OSError, ValueError) as exc:
                raise LyricsLanguageModelUnavailable("无法读取本地语言识别模型。") from exc
        labels, probabilities = self._model.predict(re.sub(r"\s+", " ", text).strip(), k=1)
        if not labels:
            return "unknown", 0.0
        return str(labels[0]).removeprefix("__label__"), float(probabilities[0])


@dataclass(slots=True, frozen=True)
class LyricsResolution:
    status: str
    text: str = ""
    source: str = ""
    source_path: str = ""
    candidates: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class LanguageDetection:
    code: str
    status: str
    confidence: float = 0.0


class LocalLyricsEmbedder:
    """Lazy GTE sentence-transformers wrapper. Cached weights only by default.

    GTE requires ``trust_remote_code=True``. Its repository revision is pinned;
    callers must still opt in before fetching and executing these model files.
    """

    model_version = f"{GTE_MODEL_ID}@{GTE_REVISION}"

    def __init__(self, *, allow_download: bool = False) -> None:
        self.allow_download = allow_download
        self._model = None

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise LyricsModelUnavailable(
                    "歌词地图需要可选依赖 sentence-transformers；请先安装歌词模型支持。"
                ) from exc
            try:
                self._model = SentenceTransformer(
                    GTE_MODEL_ID,
                    revision=GTE_REVISION,
                    trust_remote_code=True,
                    local_files_only=not self.allow_download,
                )
            except (OSError, ValueError) as exc:
                raise LyricsModelUnavailable(
                    "本机尚无 GTE 多语模型。明确同意下载后再启用歌词主题地图；"
                    "未授权前不会下载模型或上传歌词。"
                ) from exc
        return self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)


@dataclass(slots=True)
class LyricsMapResult:
    statuses: dict[str, str] = field(default_factory=dict)
    points: dict[str, tuple[float, float]] = field(default_factory=dict)
    embeddings: dict[str, list[float]] = field(default_factory=dict)
    theme_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    primary_themes: dict[str, str] = field(default_factory=dict)
    secondary_themes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    evidence_sources: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    ambiguous_candidates: dict[str, list[str]] = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)
    language_statuses: dict[str, str] = field(default_factory=dict)
    language_confidences: dict[str, float] = field(default_factory=dict)
    cache_hits: int = 0
    projection_method: str = "none"
    model_version: str = ""


def clean_lyrics(raw: str) -> str:
    """Remove timing/metadata, retaining only readable lyric lines."""
    lines: list[str] = []
    for raw_line in raw.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line or _LRC_HEADER.fullmatch(line) or _SECTION_HEADER.fullmatch(line):
            continue
        line = _LRC_TIMESTAMP.sub("", line)
        line = _KARAOKE_TIMESTAMP.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and not _LRC_HEADER.fullmatch(line) and not _SECTION_HEADER.fullmatch(line):
            lines.append(line)
    return "\n".join(lines)


def lyrics_are_usable(text: str, *, min_content_chars: int = MIN_CONTENT_CHARS) -> bool:
    """Unicode-aware gate; Chinese/Japanese text needs no whitespace tokenization."""
    content = [char for char in text if unicodedata.category(char)[:1] in {"L", "N"}]
    return len(content) >= min_content_chars and len(set(content)) >= 8


def _read_lyrics(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("lyric file exceeds 1 MiB")
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            return clean_lyrics(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise UnicodeError("unsupported lyric text encoding")


def _matching_files(directory: Path, stem: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (entry for entry in directory.iterdir() if entry.is_file()
         and entry.suffix.casefold() in SUPPORTED_LYRIC_SUFFIXES
         and entry.stem.casefold() == stem.casefold()),
        key=lambda entry: str(entry).casefold(),
    )


def _external_lyrics_index(directory: Path | None) -> dict[str, list[Path]]:
    if directory is None or not directory.is_dir():
        return {}
    index: dict[str, list[Path]] = {}
    for entry in directory.rglob("*"):
        if entry.is_file() and entry.suffix.casefold() in SUPPORTED_LYRIC_SUFFIXES:
            index.setdefault(entry.stem.casefold(), []).append(entry)
    for matches in index.values():
        matches.sort(key=lambda entry: str(entry).casefold())
    return index


def _file_lyrics(path: Path, source: str) -> LyricsResolution:
    if path.suffix.casefold() not in SUPPORTED_LYRIC_SUFFIXES or not path.is_file():
        return LyricsResolution("read_error", source=source, source_path=str(path))
    try:
        text = _read_lyrics(path)
    except (OSError, UnicodeError, ValueError):
        return LyricsResolution("read_error", source=source, source_path=str(path))
    if not lyrics_are_usable(text):
        return LyricsResolution("short", text=text, source=source, source_path=str(path))
    return LyricsResolution("valid", text=text, source=source, source_path=str(path))


def _embedded_lyrics(path: Path) -> LyricsResolution:
    """Read ID3 or Vorbis comments without modifying the audio file."""
    if path.suffix.casefold() not in _EMBEDDED_SUFFIXES:
        return LyricsResolution("missing")
    try:
        import mutagen
        from mutagen.id3 import ID3, ID3NoHeaderError
    except ImportError:
        return LyricsResolution("read_error", source="embedded", source_path=str(path))
    texts: list[str] = []
    try:
        if path.suffix.casefold() == ".mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                return LyricsResolution("missing")
            for frame in tags.getall("USLT"):
                if isinstance(frame.text, str):
                    texts.append(frame.text)
            for frame in tags.getall("SYLT"):
                if isinstance(frame.text, str):
                    texts.append(frame.text)
                else:
                    texts.append("\n".join(str(part[0]) for part in frame.text if part))
        else:
            audio = mutagen.File(path, easy=False)
            if audio is None or audio.tags is None:
                return LyricsResolution("missing")
            for key, values in audio.tags.items():
                normalized_key = re.sub(r"[^a-z]", "", str(key).casefold())
                if normalized_key not in _EMBEDDED_COMMENT_KEYS:
                    continue
                candidates = values if isinstance(values, (list, tuple)) else [values]
                texts.extend(str(value) for value in candidates if isinstance(value, str))
    except (OSError, ValueError, mutagen.MutagenError):
        return LyricsResolution("read_error", source="embedded", source_path=str(path))
    unique = {clean_lyrics(text) for text in texts if text.strip()}
    unique.discard("")
    if not unique:
        return LyricsResolution("missing")
    if len(unique) > 1:
        return LyricsResolution("ambiguous", source="embedded", source_path=str(path))
    text = unique.pop()
    if not lyrics_are_usable(text):
        return LyricsResolution("short", text=text, source="embedded", source_path=str(path))
    return LyricsResolution("valid", text=text, source="embedded", source_path=str(path))


def _resolve_track_lyrics(
    track: TrackEncoding,
    *,
    lyrics_root: Path | None,
    selected_path: Path | None,
    external_index: Mapping[str, list[Path]],
    stem_counts: Mapping[str, int],
) -> LyricsResolution:
    source = Path(track.source_path)
    if selected_path is not None:
        return _file_lyrics(Path(selected_path), "manual")
    adjacent = _matching_files(source.parent, source.stem)
    if len(adjacent) > 1:
        return LyricsResolution(
            "ambiguous", source="adjacent",
            candidates=tuple(str(path) for path in adjacent),
        )
    if adjacent:
        return _file_lyrics(adjacent[0], "adjacent")
    embedded = _embedded_lyrics(source)
    if embedded.status != "missing":
        return embedded
    if lyrics_root is None:
        return LyricsResolution("missing")
    external = external_index.get(source.stem.casefold(), [])
    if not external:
        return LyricsResolution("missing")
    if len(external) != 1 or stem_counts.get(source.stem.casefold(), 0) != 1:
        return LyricsResolution(
            "ambiguous", source="external",
            candidates=tuple(str(path) for path in external),
        )
    return _file_lyrics(external[0], "external")


def resolve_track_lyrics(
    track: TrackEncoding,
    *,
    lyrics_root: Path | None = None,
    all_tracks: Sequence[TrackEncoding] = (),
    selected_path: Path | None = None,
) -> LyricsResolution:
    """Resolve one track read-only; lyric text exists only in the returned object.

    Supply the full library in ``all_tracks`` when an external lyric folder is
    used, so duplicate audio stems can never silently match the wrong lyrics.
    """
    if lyrics_root is not None and not all_tracks:
        raise ValueError("all_tracks is required when lyrics_root is set")
    tracks = all_tracks or (track,)
    stem_counts: dict[str, int] = {}
    for member in tracks:
        stem = Path(member.source_path).stem.casefold()
        stem_counts[stem] = stem_counts.get(stem, 0) + 1
    return _resolve_track_lyrics(
        track, lyrics_root=lyrics_root, selected_path=selected_path,
        external_index=_external_lyrics_index(lyrics_root), stem_counts=stem_counts,
    )


def _lyric_chunks(text: str) -> list[str]:
    """Keep short sections intact, then sample across very long lyric files."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        for fragment_start in range(0, len(line), MAX_LYRIC_CHUNK_CHARS):
            fragment = line[fragment_start:fragment_start + MAX_LYRIC_CHUNK_CHARS]
            if current and len(current) + len(fragment) + 1 > MAX_LYRIC_CHUNK_CHARS:
                chunks.append(current)
                current = ""
            current = f"{current}\n{fragment}".strip() if current else fragment
    if current:
        chunks.append(current)
    if len(chunks) > MAX_LYRIC_CHUNKS:
        indexes = np.linspace(0, len(chunks) - 1, MAX_LYRIC_CHUNKS).round().astype(int)
        chunks = [chunks[index] for index in indexes]
    return chunks


def _usable_partial_lyrics(text: str) -> bool:
    """A short fragment can add context, but repetitions like 'la la la' cannot."""
    content = [char for char in text if unicodedata.category(char)[:1] in {"L", "N"}]
    return len(content) >= 16 and len(set(content)) >= 6


def _title_is_informative(title: str) -> bool:
    compact = re.sub(r"\s+", " ", title.casefold()).strip()
    content = [char for char in compact if unicodedata.category(char)[:1] in {"L", "N"}]
    canonical = "".join(content)
    if canonical in _GENERIC_TITLES or re.fullmatch(r"(?:track|song|music|audio|untitled)\d*", canonical):
        return False
    return len(content) >= 2 and not all(char.isdigit() for char in content)


def _title_theme_cues(title: str) -> tuple[str, ...]:
    lowered = title.casefold()
    found: list[str] = []
    for theme, cues in _TITLE_CUES.items():
        for cue in cues:
            matched = (bool(re.search(rf"(?<![a-z]){re.escape(cue)}(?![a-z])", lowered))
                       if cue.isascii() else cue in lowered)
            if matched:
                found.append(theme)
                break
    return tuple(found)


def detect_lyric_language(
    text: str,
    detector: LyricLanguageDetector | None = None,
) -> LanguageDetection:
    """Detect only from lyric lines, never from song title or artist."""
    if detector is None:
        return LanguageDetection("unknown", "unavailable")
    segments: list[str] = []
    for line in text.splitlines():
        for start in range(0, len(line), 180):
            segment = line[start:start + 180].strip()
            if sum(unicodedata.category(char)[:1] == "L" for char in segment) >= 8:
                segments.append(segment)
    if not segments:
        return LanguageDetection("unknown", "unknown")
    votes: dict[str, float] = {}
    total = 0.0
    for segment in segments:
        code, confidence = detector.predict(segment)
        if not re.fullmatch(r"[a-z]{2,3}", code) or not np.isfinite(confidence) or confidence < 0.55:
            continue
        weight = min(len(segment), 180) * min(float(confidence), 1.0)
        votes[code] = votes.get(code, 0.0) + weight
        total += weight
    if not votes or total <= 0:
        return LanguageDetection("unknown", "unknown")
    ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    top_code, top_weight = ranked[0]
    top_share = top_weight / total
    if len(ranked) > 1 and ranked[1][1] / total >= 0.25:
        return LanguageDetection("mixed", "mixed", round(ranked[1][1] / total, 3))
    if top_share < 0.65:
        return LanguageDetection("unknown", "unknown", round(top_share, 3))
    return LanguageDetection(top_code, "known", round(top_share, 3))


def _unit_vector(vector: Sequence[float]) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float64)
    if arr.ndim != 1 or not arr.size or not np.isfinite(arr).all():
        raise ValueError("lyric model returned an invalid embedding")
    norm = float(np.linalg.norm(arr))
    if norm <= 0:
        raise ValueError("lyric model returned an empty embedding")
    return arr / norm


def _cache_path(artifacts: Path, text_hash: str, model_version: str) -> Path:
    digest = hashlib.sha256(f"{LYRICS_ENGINE_VERSION}|{model_version}|{text_hash}".encode("utf-8")).hexdigest()
    return artifacts / "lyrics_cache" / "embeddings" / f"{digest}.json"


def _cached_vector(path: Path, text_hash: str, model_version: str) -> np.ndarray | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("text_sha256") != text_hash or record.get("model_version") != model_version:
            return None
        return _unit_vector(record["embedding"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_vector(path: Path, vector: np.ndarray, text_hash: str, model_version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "text_sha256": text_hash,
        "model_version": model_version,
        "embedding": vector.tolist(),
    }
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    pending.replace(path)


def _theme_vectors(artifacts: Path, embedder: LyricEmbedder, model_version: str) -> list[np.ndarray]:
    names = list(THEME_PROMPTS)
    prompt_hash = hashlib.sha256(
        json.dumps(THEME_PROMPTS, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    cache_name = hashlib.sha256(f"{model_version}|{prompt_hash}".encode("utf-8")).hexdigest()
    path = artifacts / "lyrics_cache" / "themes" / f"{cache_name}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("model_version") == model_version and record.get("prompt_hash") == prompt_hash:
            vectors = [_unit_vector(record["embeddings"][name]) for name in names]
            if len({len(vector) for vector in vectors}) == 1:
                return vectors
    except (OSError, ValueError, KeyError, TypeError):
        pass
    encoded = embedder.encode(list(THEME_PROMPTS.values()))
    if len(encoded) != len(names):
        raise ValueError("lyric model returned an unexpected number of theme embeddings")
    vectors = [_unit_vector(vector) for vector in encoded]
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("theme embeddings have different dimensions")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "model_version": model_version,
        "prompt_hash": prompt_hash,
        "embeddings": {name: vector.tolist() for name, vector in zip(names, vectors)},
    }
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    pending.replace(path)
    return vectors


def _project(embeddings: dict[str, list[float]]) -> tuple[dict[str, tuple[float, float]], str]:
    ids = sorted(embeddings)
    if not ids:
        return {}, "none"
    if len(ids) == 1:
        return {ids[0]: (0.0, 0.0)}, "single-point"
    matrix = np.asarray([embeddings[track_id] for track_id in ids], dtype=np.float64)
    if len(ids) >= 15:
        try:
            from umap import UMAP
            coords = UMAP(n_components=2, n_neighbors=min(15, len(ids) - 1), random_state=42).fit_transform(matrix)
            return {track_id: (float(x), float(y)) for track_id, (x, y) in zip(ids, coords)}, "umap"
        except ImportError:
            pass
    # Stable sign orientation for this corpus; no stochastic PCA initialization.
    centered = matrix - matrix.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    axes = vh[: min(2, len(vh))].copy()
    for axis in axes:
        largest = int(np.argmax(np.abs(axis)))
        if axis[largest] < 0:
            axis *= -1
    coords = centered @ axes.T
    if coords.shape[1] == 1:
        coords = np.column_stack([coords[:, 0], np.zeros(len(ids))])
    return {track_id: (float(x), float(y)) for track_id, (x, y) in zip(ids, coords)}, "pca"


def _scan_lyrics(
    tracks: Sequence[TrackEncoding],
    *,
    lyrics_root: Path | None,
    selected_sources: Mapping[str, Path] | None,
    manual_instrumental_ids: Sequence[str],
    language_detector: LyricLanguageDetector | None,
) -> tuple[LyricsMapResult, dict[str, tuple[str, str, str]]]:
    """Resolve lyric text in memory and return its public coverage metadata."""
    result = LyricsMapResult()
    instrumental = set(manual_instrumental_ids)
    stem_counts: dict[str, int] = {}
    for track in tracks:
        stem = Path(track.source_path).stem.casefold()
        stem_counts[stem] = stem_counts.get(stem, 0) + 1
    external_index = _external_lyrics_index(lyrics_root)

    selected_sources = selected_sources or {}
    pending: dict[str, tuple[str, str, str]] = {}
    language_runtime_available = True
    for track in tracks:
        track_id = track.track_id
        result.primary_themes[track_id] = "unknown"
        result.secondary_themes[track_id] = ()
        result.evidence_sources[track_id] = "unknown"
        metadata = getattr(track, "metadata", None)
        title = str(getattr(metadata, "title", "") or Path(track.source_path).stem).strip()
        if track_id in instrumental:
            result.statuses[track_id] = "instrumental"
            result.languages[track_id] = "instrumental"
            result.language_statuses[track_id] = "instrumental"
            if _title_is_informative(title):
                pending[track_id] = (title, "", "title_only")
                result.evidence_sources[track_id] = "title_only"
            continue
        resolution = _resolve_track_lyrics(
            track, lyrics_root=lyrics_root,
            selected_path=selected_sources.get(track_id),
            external_index=external_index, stem_counts=stem_counts,
        )
        result.statuses[track_id] = resolution.status
        if resolution.candidates:
            result.ambiguous_candidates[track_id] = list(resolution.candidates)
        if resolution.status != "valid":
            result.languages[track_id] = "unknown"
            result.language_statuses[track_id] = "unknown"
            if resolution.status == "short" and _usable_partial_lyrics(resolution.text):
                pending[track_id] = (title, resolution.text, "partial_lyrics")
                result.evidence_sources[track_id] = "partial_lyrics"
                result.sources[track_id] = resolution.source
            elif _title_is_informative(title):
                pending[track_id] = (title, "", "title_only")
                result.evidence_sources[track_id] = "title_only"
            continue
        result.sources[track_id] = resolution.source
        pending[track_id] = (title, resolution.text, "lyrics")
        result.evidence_sources[track_id] = "lyrics"
        if language_detector is None or not language_runtime_available:
            language = LanguageDetection("unknown", "unavailable")
        else:
            try:
                language = detect_lyric_language(resolution.text, language_detector)
            except (LyricsLanguageModelUnavailable, OSError, RuntimeError):
                language_runtime_available = False
                language = LanguageDetection("unknown", "unavailable")
        result.languages[track_id] = language.code
        result.language_statuses[track_id] = language.status
        result.language_confidences[track_id] = language.confidence
    return result, pending


def scan_lyric_languages(
    tracks: Sequence[TrackEncoding],
    *,
    lyrics_root: Path | None = None,
    selected_sources: Mapping[str, Path] | None = None,
    manual_instrumental_ids: Sequence[str] = (),
    language_detector: LyricLanguageDetector | None = None,
) -> LyricsMapResult:
    """Read local lyric provenance and languages without loading a theme model.

    The returned object has no lyric text or embeddings. No artifacts or caches
    are created; missing or unavailable language models yield explicit status.
    """
    result, _ = _scan_lyrics(
        tracks, lyrics_root=lyrics_root, selected_sources=selected_sources,
        manual_instrumental_ids=manual_instrumental_ids,
        language_detector=language_detector,
    )
    return result


def build_lyrics_map(
    tracks: Sequence[TrackEncoding],
    artifacts: Path,
    *,
    lyrics_root: Path | None = None,
    selected_sources: Mapping[str, Path] | None = None,
    manual_instrumental_ids: Sequence[str] = (),
    embedder: LyricEmbedder | None = None,
    language_detector: LyricLanguageDetector | None = None,
    model_version: str | None = None,
    manual_themes: Mapping[str, str] | None = None,
) -> LyricsMapResult:
    """Build local title/lyric theme evidence without changing audio files.

    Manual lyric files take precedence over adjacent files, embedded tags, and
    unique external matches. Only hashes and embeddings are written to cache;
    language detection remains lyric-only. Explicit manual themes win last.
    """
    if embedder is None:
        embedder = LocalLyricsEmbedder()
    version = model_version or embedder.model_version
    if version != embedder.model_version:
        raise ValueError("model_version must match the active lyric embedder")
    result, pending = _scan_lyrics(
        tracks, lyrics_root=lyrics_root, selected_sources=selected_sources,
        manual_instrumental_ids=manual_instrumental_ids,
        language_detector=language_detector,
    )
    result.model_version = version

    uncached: dict[str, tuple[str, str, str, str, Path]] = {}
    for track_id, (title, lyric_text, evidence) in pending.items():
        payload = json.dumps(
            {"title": title, "lyrics": lyric_text, "evidence": evidence},
            ensure_ascii=False, sort_keys=True,
        )
        text_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        cache_file = _cache_path(artifacts, text_hash, version)
        cached = _cached_vector(cache_file, text_hash, version)
        if cached is not None:
            result.embeddings[track_id] = cached.tolist()
            result.cache_hits += 1
        else:
            uncached[track_id] = (title, lyric_text, evidence, text_hash, cache_file)

    if uncached:
        requests: list[str] = []
        layouts: dict[str, tuple[int, list[int], list[int], str]] = {}
        for track_id, (title, lyric_text, evidence, _, _) in uncached.items():
            title_index = len(requests)
            requests.append(title)
            chunk_indexes: list[int] = []
            chunk_lengths: list[int] = []
            for chunk in _lyric_chunks(lyric_text):
                chunk_indexes.append(len(requests))
                chunk_lengths.append(len(chunk))
                requests.append(chunk)
            layouts[track_id] = (title_index, chunk_indexes, chunk_lengths, evidence)
        vectors = embedder.encode(requests)
        if len(vectors) != len(requests):
            raise ValueError("lyric model returned an unexpected number of embeddings")
        normalized_vectors = [_unit_vector(vector) for vector in vectors]
        for track_id, (title_index, chunk_indexes, chunk_lengths, evidence) in layouts.items():
            title_vector = normalized_vectors[title_index]
            if evidence == "title_only":
                fused = title_vector
            else:
                if not chunk_indexes:
                    raise ValueError("usable lyrics yielded no embedding chunks")
                lyric_vectors = [normalized_vectors[index] for index in chunk_indexes]
                if any(len(vector) != len(title_vector) for vector in lyric_vectors):
                    raise ValueError("title and lyric embeddings have different dimensions")
                lyric_vector = _unit_vector(np.average(lyric_vectors, axis=0, weights=chunk_lengths))
                title_weight, lyric_weight = (
                    (TITLE_WEIGHT, LYRICS_WEIGHT) if evidence == "lyrics"
                    else (PARTIAL_TITLE_WEIGHT, PARTIAL_LYRICS_WEIGHT)
                ) if _title_is_informative(uncached[track_id][0]) else (0.0, 1.0)
                fused = _unit_vector(title_weight * title_vector + lyric_weight * lyric_vector)
            result.embeddings[track_id] = fused.tolist()
            _, _, _, text_hash, cache_file = uncached[track_id]
            _save_vector(cache_file, fused, text_hash, version)

    if result.embeddings:
        normalized_prompts = _theme_vectors(artifacts, embedder, version)
        dimension = len(next(iter(result.embeddings.values())))
        if any(len(vector) != dimension for vector in normalized_prompts):
            raise ValueError("lyric and theme embeddings have different dimensions")
        for track_id, values in result.embeddings.items():
            vector = np.asarray(values)
            scores = {
                theme: float(np.dot(vector, prompt))
                for theme, prompt in zip(THEME_PROMPTS, normalized_prompts)
            }
            result.theme_scores[track_id] = scores
            title, _, evidence = pending[track_id]
            ranked = sorted(scores, key=lambda theme: (-scores[theme], theme))
            if evidence == "title_only":
                cues = _title_theme_cues(title)
                # No cosine threshold is calibrated for title-only GTE outputs.
                # Thus a title without one explicit clue stays unknown despite
                # having an embedding for semantic-neighbor exploration. Two
                # distinct clues can also point to genuinely different stories.
                if len(cues) == 1:
                    result.primary_themes[track_id] = cues[0]
                elif len(cues) > 1:
                    result.secondary_themes[track_id] = cues
            elif ranked:
                lead = ranked[0]
                runner_up = ranked[1] if len(ranked) > 1 else None
                margin = scores[lead] - scores[runner_up] if runner_up else float("inf")
                min_margin = 0.015 if evidence == "lyrics" else 0.035
                if margin >= min_margin:
                    result.primary_themes[track_id] = lead
                result.secondary_themes[track_id] = tuple(
                    theme for theme in ranked[:3]
                    if theme != result.primary_themes[track_id]
                    and scores[theme] >= scores[lead] - 0.08
                )

    for track_id, theme_id in (manual_themes or {}).items():
        if theme_id not in THEME_PROMPTS and theme_id != "unknown":
            raise ValueError(f"unsupported manual theme: {theme_id}")
        if track_id in result.primary_themes:
            result.primary_themes[track_id] = theme_id
            result.evidence_sources[track_id] = "manual"
            result.secondary_themes[track_id] = ()
    result.points, result.projection_method = _project(result.embeddings)
    return result


def build_title_clue_map(
    tracks: Sequence[TrackEncoding], *, manual_themes: Mapping[str, str] | None = None,
) -> LyricsMapResult:
    """Offline, no-model theme preview from explicit title words and user choices.

    This is deliberately *not* an embedding-backed theme map: titles without a
    single clear cue remain unknown, and no lyric or sung-language claim is made.
    It keeps the island review/correction workflow usable before optional model
    dependencies and weights have been installed.
    """
    result = LyricsMapResult(model_version="title-clues-v1")
    for track in tracks:
        track_id = track.track_id
        metadata = getattr(track, "metadata", None)
        title = str(getattr(metadata, "title", "") or Path(track.source_path).stem).strip()
        cues = _title_theme_cues(title) if _title_is_informative(title) else ()
        result.primary_themes[track_id] = cues[0] if len(cues) == 1 else "unknown"
        result.secondary_themes[track_id] = cues if len(cues) > 1 else ()
        result.evidence_sources[track_id] = "title_clue" if cues else "unknown"
    for track_id, theme_id in (manual_themes or {}).items():
        if theme_id not in THEME_PROMPTS and theme_id != "unknown":
            raise ValueError(f"unsupported manual theme: {theme_id}")
        if track_id in result.primary_themes:
            result.primary_themes[track_id] = theme_id
            result.secondary_themes[track_id] = ()
            result.evidence_sources[track_id] = "manual"
    return result


def rank_theme_neighbors(
    result: LyricsMapResult,
    track_id: str,
    *,
    limit: int = 12,
) -> list[tuple[str, float]]:
    """Rank by original text embeddings; theme-island pixel distance is not used."""
    if limit <= 0 or track_id not in result.embeddings:
        return []
    focal = _unit_vector(result.embeddings[track_id])
    neighbors: list[tuple[str, float]] = []
    for other_id, values in result.embeddings.items():
        if other_id == track_id:
            continue
        other = _unit_vector(values)
        if len(other) != len(focal):
            continue
        neighbors.append((other_id, float(np.dot(focal, other))))
    return sorted(neighbors, key=lambda item: (-item[1], item[0]))[:limit]
