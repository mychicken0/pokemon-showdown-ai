# Root compatibility wrapper for analyze_doubles_turn_level.
# The implementation has moved to scripts/analyze/analyze_doubles_turn_level.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_doubles_turn_level` and `from analyze_doubles_turn_level import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_doubles_turn_level as _impl

sys.modules[__name__] = _impl
