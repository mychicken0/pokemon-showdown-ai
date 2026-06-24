"""Phase 7 raw Showdown protocol capture for data expansion.

Ponytail: pure helper, no network, no I/O beyond file write.

Wraps a poke-env player to capture raw protocol lines
per battle. Used by the friendly-fire monitor v2 to
classify suspected events with full evidence.

Usage from the collection script::

    from rl_data_3b_raw_protocol_capture import (
        RawProtocolCapture,
    )
    capture = RawProtocolCapture(
        battle_id=btag,
        out_dir="logs/phase7_data_expansion/pilot_smoke20/raw_protocol",
    )
    bot = DoublesDamageAwarePlayer(..., raw_callback=capture.feed)
"""
import json
import os
import time
from typing import Any, Optional


class RawProtocolCapture:
    """Capture raw Showdown protocol lines for a single battle.

    Lines are appended to ``{out_dir}/{battle_id}.jsonl`` in the
    form::

        {"ts": <float>, "seq": <int>, "line": "<protocol line>"}

    The capture is process-safe only at the level of the
    current process; the collection script is the only writer
    for a given battle.
    """

    def __init__(
        self,
        battle_id: str,
        out_dir: str,
        enabled: bool = True,
    ):
        self.battle_id = battle_id
        self.out_dir = out_dir
        self.enabled = enabled
        self._seq = 0
        self._path = None
        if self.enabled:
            os.makedirs(self.out_dir, exist_ok=True)
            self._path = os.path.join(
                self.out_dir, f"{self.battle_id}.jsonl"
            )
            # Truncate on open
            try:
                open(self._path, "w").close()
            except Exception:
                self._path = None
                self.enabled = False

    def feed(self, line: str) -> None:
        """Append a single raw protocol line. Call this from
        the player's battle-message handler."""
        if not self.enabled or self._path is None:
            return
        self._seq += 1
        rec = {
            "ts": time.time(),
            "seq": self._seq,
            "battle_id": self.battle_id,
            "line": line,
        }
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            # Never let logging break the bot path.
            self.enabled = False

    def path(self) -> Optional[str]:
        return self._path
