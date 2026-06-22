# Root compatibility wrapper for analyze_vgc2026_phaseV3a2_reality.
# The implementation has moved to scripts/analyze/analyze_vgc2026_phaseV3a2_reality.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_vgc2026_phaseV3a2_reality` and `from analyze_vgc2026_phaseV3a2_reality import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_vgc2026_phaseV3a2_reality as _impl

sys.modules[__name__] = _impl
