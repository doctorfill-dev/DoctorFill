"""Tests de textlayer.py : seul pypdfium2 est requis, pas marker ni le GPU."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
