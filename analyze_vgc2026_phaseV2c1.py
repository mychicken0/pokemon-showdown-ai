# Root compatibility wrapper for analyze_vgc2026_phaseV2c1.
# The implementation has moved to scripts/analyze/analyze_vgc2026_phaseV2c1.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_vgc2026_phaseV2c1` and `from analyze_vgc2026_phaseV2c1 import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_vgc2026_phaseV2c1 as _impl

sys.modules[__name__] = _impl
