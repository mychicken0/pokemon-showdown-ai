"""Test-only helper: unregister the poke_env atexit callback that deadlocks.

poke_env.concurrency starts a daemon thread (Thread-1 __run_loop) running
POKE_LOOP.run_forever() at import time.  It also registers an atexit callback
(__clear_loop) that attempts to stop the loop and join the thread during
interpreter shutdown.  In some environments this join deadlocks — the loop
never processes the stop signal, so the process hangs until an external
timeout kills it (exit code 124).

This module unregisters that broken atexit callback.  The daemon thread is
marked daemon=True, so the interpreter will discard it on shutdown without
attempting a join.  No new cleanup callback is registered.

Production battle code never imports this module.  It is imported only by
test suites so they terminate naturally.

The operation is idempotent: importing this module multiple times or from
multiple test files is harmless.
"""
import atexit

import poke_env.concurrency  # noqa: F401 — triggers POKE_LOOP creation

_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass  # already unregistered or not registered
