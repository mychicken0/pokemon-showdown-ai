# Root compatibility wrapper for analyze_vgc2026_phaseV2e_failures.
# The implementation has moved to scripts/analyze/analyze_vgc2026_phaseV2e_failures.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_vgc2026_phaseV2e_failures` and `from analyze_vgc2026_phaseV2e_failures import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_vgc2026_phaseV2e_failures as _impl

sys.modules[__name__] = _impl
