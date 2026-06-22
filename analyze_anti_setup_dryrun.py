# Root compatibility wrapper for analyze_anti_setup_dryrun.
# The implementation has moved to scripts/analyze/analyze_anti_setup_dryrun.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_anti_setup_dryrun` and `from analyze_anti_setup_dryrun import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_anti_setup_dryrun as _impl

sys.modules[__name__] = _impl
