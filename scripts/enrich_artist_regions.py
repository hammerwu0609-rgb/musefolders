"""Fill sourced artist regions for the existing local collection."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from musefolders.service import load_plan
from musefolders.qqmusic_catalog import cached_platform
from musefolders.tag_catalog import build_track_profiles
from musefolders.artist_regions import enrich_regions

if __name__ == '__main__':
    plan=load_plan(ROOT/'artifacts'/'collection_plan.json')
    profiles=build_track_profiles(plan.tracks,platform_metadata=cached_platform(plan.tracks,ROOT/'artifacts'))
    report=enrich_regions([profile.artist for profile in profiles.values()],ROOT/'artifacts',
                          progress=lambda done,total,name:print(f'{done}/{total} {name}',flush=True))
    print(report,flush=True)
