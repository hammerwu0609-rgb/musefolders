"""Consumer entry point. Original workspace: legacy_app.py."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from musefolders.simple_ui import render_app
render_app(ROOT)
