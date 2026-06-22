"""
poke-env test cleanup helper.

This module unregisters the broken poke-env atexit callback that hangs
when stopping the global event loop (POKE_LOOP). It must be imported
BEFORE any poke-env production module that triggers POKE_LOOP creation.

Usage:
    import poke_env_test_cleanup  # must be first import
    # now safe to import poke_env, bot_vgc2026_phaseV2c, etc.
"""

import atexit
import sys


def _unregister_poke_env_atexit():
    """Remove poke-env's __clear_loop from atexit registry."""
    try:
        from poke_env import concurrency
        # poke-env registers concurrency.__clear_loop via atexit
        atexit.unregister(concurrency.__clear_loop)
    except (ImportError, AttributeError, ValueError):
        # Already unregistered, not registered, or poke-env not available
        pass


# Execute immediately on import
_unregister_poke_env_atexit()

# Also provide a function for explicit calls
unregister_poke_env_atexit = _unregister_poke_env_atexit