"""Package existing portable music data; never include credentials or local settings."""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="demo_library directory with portable audio paths")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from musefolders.library_import import build_music_package
    manifest = build_music_package(args.bundle, args.output)
    print(f"Packaged {manifest['tracks']} tracks, {len(manifest['files'])} files: {args.output.resolve()}")
    print(f"Size: {args.output.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
