"""Prepare portable demo data locally; do not publish the resulting bundle to Git."""
import argparse
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('demo_library'))
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('输出目录已有文件，请选择新的空目录，避免混入旧曲库。')
    sys.path.insert(0, str(project/'src'))
    from musefolders.service import load_plan
    from musefolders.lyrics_map import resolve_track_lyrics
    from musefolders.qqmusic_catalog import cached_platform, platform_lyrics
    from musefolders.user_annotations import confirmed_instrumental_ids
    artifacts = project/'artifacts'
    raw = json.loads((artifacts/'collection_plan.json').read_text(encoding='utf-8'))
    plan = load_plan(artifacts/'collection_plan.json')
    fallback = platform_lyrics(cached_platform(plan.tracks, artifacts), artifacts)
    instrumental = confirmed_instrumental_ids(plan.tracks, artifacts)
    if not plan.tracks or any(not Path(t.source_path).is_file() for t in plan.tracks):
        parser.error('请先在本地版分析具有真实音频的曲库。')
    audio = output/'audio'
    audio.mkdir(parents=True, exist_ok=True)
    lyrics = 0
    for entry, track in zip(raw['tracks'], plan.tracks):
        source = Path(track.source_path)
        # Derived name must not turn a malformed track ID into a filesystem path.
        import hashlib
        filename = hashlib.sha256(track.track_id.encode()).hexdigest()+source.suffix.lower()
        shutil.copy2(source, audio/filename)
        entry['source_path'] = 'audio/'+filename
        entry['source_mtime_ns'] = entry['source_ctime_ns'] = 0
        lyric = resolve_track_lyrics(track, lyrics_root=Path(plan.source_root), all_tracks=plan.tracks,
            fallback_path=None if track.track_id in instrumental else fallback.get(track.track_id))
        if lyric.status == 'valid' and track.track_id not in instrumental:
            (audio/Path(filename).with_suffix('.lrc')).write_text(lyric.text, encoding='utf-8')
            lyrics += 1
    raw.update(source_root='audio', unsupported_files=[], failures=[])
    (output/'collection_plan.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ('user_annotations.json','platform_catalog.json','ai_lyrics_tags.json','artist_regions.json'):
        if (artifacts/name).is_file():
            shutil.copy2(artifacts/name, output/name)
    print(f'Prepared {len(plan.tracks)} tracks, {lyrics} lyrics. Bundle is local data; never commit it.')


if __name__ == '__main__':
    main()
