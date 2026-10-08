"""Prepare an explicit CloudRun build context without credentials or user state."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def build(root: Path, output: Path):
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a new build directory; existing files will not be overwritten")
    package = root / "demo_library" / "experience.zip"
    if not package.is_file():
        raise ValueError("Prepare demo_library/experience.zip before building")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    output.mkdir(parents=True)
    for name in ("Dockerfile", ".dockerignore", "requirements-cloud.txt", "cloud_app.py"):
        shutil.copy2(root / name, output / name)
    shutil.copytree(root / "src", output / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    (output / ".streamlit").mkdir()
    shutil.copy2(root / ".streamlit" / "config.toml", output / ".streamlit" / "config.toml")
    (output / "scripts").mkdir()
    shutil.copy2(root / "scripts" / "restore_demo_library.py", output / "scripts" / "restore_demo_library.py")
    (output / "demo_library").mkdir()
    shutil.copy2(package, output / "demo_library" / "experience.zip")
    # The immutable source revision is also recorded in the built image metadata.
    dockerfile = output / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8") +
                         f'\nLABEL org.opencontainers.image.revision="{revision}"\n', encoding="utf-8")
    files = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
    report = {"revision": revision, "files": files,
              "bytes": sum((output / path).stat().st_size for path in files)}
    print(json.dumps({"revision": revision, "directory": str(output), "files": len(files),
                      "megabytes": round(report["bytes"] / 1024 / 1024, 1)}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output)
