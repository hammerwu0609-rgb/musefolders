"""Suggest metadata matches from MusicBrainz without changing the source plan."""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://musicbrainz.org/ws/2/recording/"
USER_AGENT = "MuseFolders/0.1 (metadata-enrichment; local competition demo)"


def search(title: str, artist: str) -> list[dict]:
    query = f'recording:"{title}" AND artist:"{artist}"'
    url = API + "?" + urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("recordings", []) if isinstance(payload, dict) else []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "artifacts" / "collection_plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "metadata_enrichment.json")
    parser.add_argument("--delay", type=float, default=1.1)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    previous = {}
    if args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
    results = previous.get("results", {})
    for index, track in enumerate(plan.get("tracks", [])):
        meta = track.get("metadata", {})
        track_id = track.get("track_id", "")
        if track_id in results:
            continue
        title, artist = str(meta.get("title", "")), str(meta.get("artist", ""))
        item = {"track_id": track_id, "local": meta, "query": {"title": title, "artist": artist}, "matches": [], "status": "ok"}
        try:
            matches = search(title, artist)
            for match in matches:
                artist_credit = " / ".join(str(x.get("name", "")) for x in match.get("artist-credit", []) if isinstance(x, dict))
                releases = match.get("releases", [])
                item["matches"].append({
                    "recording_id": match.get("id", ""), "title": match.get("title", ""),
                    "artist": artist_credit, "length_ms": match.get("length"),
                    "disambiguation": match.get("disambiguation", ""),
                    "releases": [{"title": r.get("title", ""), "date": r.get("date", "")} for r in releases[:5]],
                })
            if not item["matches"]:
                item["status"] = "no_match"
        except Exception as error:
            item["status"] = "error"
            item["error_type"] = type(error).__name__
        results[track_id] = item
        print(f"{index + 1}/{len(plan.get('tracks', []))} {artist} - {title}: {item['status']}")
        if index + 1 < len(plan.get("tracks", [])):
            time.sleep(max(0.0, args.delay))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema_version": "musicbrainz-suggestions-v1", "source": API, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(results), "matched": sum(bool(v.get("matches")) for v in results.values()), "no_match": sum(v.get("status") == "no_match" for v in results.values()), "errors": sum(v.get("status") == "error" for v in results.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
