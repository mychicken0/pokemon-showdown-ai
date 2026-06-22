# Root compatibility wrapper for inspect_vgc2026_phaseV2g_pair.
# The implementation has moved to scripts/inspect/inspect_vgc2026_phaseV2g_pair.py.
# This wrapper re-exports the module under its original name so that
# test subprocess invocations like `python -c "import inspect_vgc2026_phaseV2g_pair"` work
# without modifying test code.
import sys

import scripts.inspect.inspect_vgc2026_phaseV2g_pair as _impl

sys.modules[__name__] = _impl
