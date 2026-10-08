"""Restore the server demo library from its packaged copy and verify recordings."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import sys
import zipfile


def restore(bundle: Path):
    bundle = bundle.resolve()
    package = bundle / "experience.zip"
    if package.is_file():
        with zipfile.ZipFile(package) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if entry.is_dir():
                    continue
                if path.is_absolute() or any(part in ("..", ".") for part in path.parts) or "\\" in entry.filename or ":" in entry.filename:
                    raise ValueError("Invalid demo package path")
                allowed = entry.filename in {
                    "collection_plan.json", "artist_regions.json", "platform_catalog.json",
                    "ai_lyrics_tags.json", "user_annotations.json", "music_package.json",
                } or (path.parts and path.parts[0] in {"audio", "platform_lyrics"}
                      and path.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".lrc", ".txt", ".json"})
                if not allowed:
                    continue
                destination = (bundle / entry.filename).resolve()
                if not destination.is_relative_to(bundle):
                    raise ValueError("Demo package leaves its directory")
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
    plan = json.loads((bundle / "collection_plan.json").read_text(encoding="utf-8-sig"))
    tracks = plan.get("tracks", [])
    if not tracks:
        raise ValueError("Demo library is empty")
    for track in tracks:
        audio = (bundle / track["source_path"]).resolve()
        if not audio.is_relative_to(bundle / "audio") or not audio.is_file():
            raise ValueError("Missing demo recording")
        digest = hashlib.sha256()
        with audio.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != track["source_sha256"]:
            raise ValueError("Demo recording fingerprint mismatch")
    print(f"Verified {len(tracks)} server demo recordings; originals preserved.")


if __name__ == "__main__":
    restore(Path(sys.argv[1]))
