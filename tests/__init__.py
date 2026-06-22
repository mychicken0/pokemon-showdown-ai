"""Test package for the project.

Adds showdown_ai/, scripts/, and all scripts/<sub>/ sub-folders to sys.path
so test files in tests/ can import production code and script modules
that were moved out of root.

For example:
  `import ability_rules` resolves to showdown_ai/ability_rules.py
  `import analyze_X` resolves to scripts/analyze/analyze_X.py
  `import inspect_X` resolves to scripts/inspect/inspect_X.py
"""
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
_showdown_ai_dir = _root / "showdown_ai"
_scripts_dir = _root / "scripts"

if _showdown_ai_dir.exists() and str(_showdown_ai_dir) not in sys.path:
    sys.path.insert(0, str(_showdown_ai_dir))

if _scripts_dir.exists():
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    for sub in _scripts_dir.iterdir():
        if sub.is_dir() and not sub.name.startswith("__"):
            sub_path = str(sub)
            if sub_path not in sys.path:
                sys.path.insert(0, sub_path)
