# Root compatibility wrapper for analyze_doubles_narrow_ally_heal_paired_repair.
# The implementation has moved to scripts/analyze/analyze_doubles_narrow_ally_heal_paired_repair.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_doubles_narrow_ally_heal_paired_repair` and `from analyze_doubles_narrow_ally_heal_paired_repair import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_doubles_narrow_ally_heal_paired_repair as _impl

sys.modules[__name__] = _impl
