# Root compatibility wrapper for inspect_vgc2026_phaseV2i_matchup.
# The implementation has moved to scripts/inspect/inspect_vgc2026_phaseV2i_matchup.py.
# This wrapper re-exports the module under its original name so that
# test subprocess invocations like `python -c "import inspect_vgc2026_phaseV2i_matchup"` work
# without modifying test code.
import sys

import scripts.inspect.inspect_vgc2026_phaseV2i_matchup as _impl

sys.modules[__name__] = _impl
