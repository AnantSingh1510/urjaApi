"""Run from repository root: python scripts/export_openapi.py"""

import json
from pathlib import Path

from urja_api.app import create_app

path = Path(__file__).resolve().parents[1] / "openapi.json"
path.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
print(path)
