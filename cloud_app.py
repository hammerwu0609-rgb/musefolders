from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from musefolders.demo_mode import render_demo
render_demo(ROOT / "demo_library")
