# Root compatibility wrapper for analyze_doubles_support_move_target_safety_paired.
# The implementation has moved to scripts/analyze/analyze_doubles_support_move_target_safety_paired.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_doubles_support_move_target_safety_paired` and `from analyze_doubles_support_move_target_safety_paired import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_doubles_support_move_target_safety_paired as _impl

sys.modules[__name__] = _impl
