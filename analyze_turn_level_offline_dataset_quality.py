# Root compatibility wrapper for analyze_turn_level_offline_dataset_quality.
# The implementation has moved to scripts/analyze/analyze_turn_level_offline_dataset_quality.py.
# This wrapper re-exports the module under its original name so that
# existing imports like `import analyze_turn_level_offline_dataset_quality` and `from analyze_turn_level_offline_dataset_quality import X`
# continue to work without modification.
import sys

import scripts.analyze.analyze_turn_level_offline_dataset_quality as _impl

sys.modules[__name__] = _impl
