"""Test package for the project.

Adds scripts/ and all scripts/<sub>/ sub-folders to sys.path
so test files in tests/ can import script modules that were moved
to sub-folders.

This is a temporary measure until a proper src/ layout is implemented.
"""
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
_scripts_dir = _root / "scripts"
if _scripts_dir.exists():
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    for sub in _scripts_dir.iterdir():
        if sub.is_dir() and not sub.name.startswith("__"):
            sub_path = str(sub)
            if sub_path not in sys.path:
                sys.path.insert(0, sub_path)
