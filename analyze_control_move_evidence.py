# Root compatibility wrapper for analyze_control_move_evidence.
# The implementation has moved to scripts/analyze/analyze_control_move_evidence.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_control_move_evidence` and `from analyze_control_move_evidence import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_control_move_evidence as _impl

sys.modules[__name__] = _impl
