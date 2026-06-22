#!/usr/bin/env python3
"""
VGC 2026 Battle Runner with Controlled Team Preview — Phase V2c.3

Phase V2c.3 adds:
- Explicit smoke configuration: --smoke-battles, explicit arm sizes (A=2,B=2,C=2,D1=2,D2=2)
- Smoke args passed to runner, no inference from team pool size
- Test cleanup: poke_env_test_cleanup pattern for proper shutdown
- Artifact protection: tests use TemporaryDirectory, never touch logs/
- Observed lead: robust capture (first non-empty active state, no turn-0 dependency)
- Replaces mislabeled "phaseV2c2_smoke_test" (was 450 battles) with true 10-battle smoke

NOTE: The original raw V2c JSONL/CSV artifacts were accidentally truncated when
the V2c.1 analyzer ran (it called _init_csv which truncated files).
Only V2c.1 analysis reports survive; raw V2c battle data was lost.
"""

import json
import csv
import random
import asyncio
import time
import argparse
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vgc_team_pool import VGCTeamPool, load_vgc_pool
from team_preview_policy import choose_four_from_six, PreviewResult, validate_preview

# poke-env imports
from poke_env import AccountConfiguration, ServerConfiguration
from poke_env import RandomPlayer
from poke_env.player.player import Player
from poke_env.ps_client import PSClient
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder
from poke_env.concurrency import POKE_LOOP, create_in_poke_loop
from poke_env.battle.battle import Battle
from poke_env.battle.pokemon import Pokemon
import asyncio

# V2l — canonical shared engine for the VGC runtime.
# ``DoublesDamageAwarePlayer`` is the Random-Doubles
# decision engine and is reused as-is by VGC after
# preview.
from bot_doubles_damage_aware import DoublesDamageAwarePlayer

# ===== Constants =====

# Local server configuration (no security)
LOCAL_SERVER_CONFIG = ServerConfiguration(
    websocket_url='ws://localhost:8000/showdown/websocket',
    authentication_url='http://localhost:8000/action.php?'
)

# Watchdog timeouts
BATTLE_TIMEOUT = 300.0          # 5 minutes per battle
CLEANUP_TIMEOUT = 30.0          # 30 seconds for cleanup
HEARTBEAT_INTERVAL = 30.0       # 30 seconds heartbeat
STALL_DETECTION = 180.0         # 3 minutes stall detection
ARM_TIMEOUT = 3600.0            # 1 hour per arm

# Default artifact names (V2c default - never overwrite without --overwrite)
DEFAULT_CSV_NAME = "vgc2026_phaseV2c_benchmark.csv"
DEFAULT_JSONL_NAME = "vgc2026_phaseV2c_benchmark.jsonl"
DEFAULT_PREVIEW_CSV_NAME = "vgc2026_phaseV2c_preview_evidence.csv"

# ===== Custom PSClient =====

class NoAvatarPSClient(PSClient):
    async def log_in(self, split_message: list):
        self.logger.info("Bypassing authentication request (local server)")
        assertion = ""
        await self.send_message(f"/trn {self.username},0,{assertion}")

# ===== Controlled Team Preview Player =====

class ControlledTeamPreviewPlayer(DoublesDamageAwarePlayer):
    """
    Player that uses a pre-planned team preview selection
    and runs the canonical
    :class:`DoublesDamageAwarePlayer` decision engine
    for every post-preview turn.

    V2l — runtime decision-engine unification.

    The pre-V2l implementation extended poke-env's
    :class:`RandomPlayer` and called
    ``super().choose_move(battle)`` which delegated to
    poke-env's random move selection. The VGC runtime
    therefore used a DIFFERENT engine than Random
    Doubles, which violates the spec invariant that VGC
    2026 after preview must use the same canonical
    decision engine as Random Doubles.

    The V2l fix makes this class extend
    :class:`DoublesDamageAwarePlayer` directly. The
    inherited ``choose_move`` is the canonical engine;
    only ``teampreview`` is overridden to emit the
    pre-planned order.

    Runtime mode boundary:

    - ``"random_doubles"``: the format is
      ``gen9randomdoublesbattle``. No team preview
      selection occurs; the six Pokémon are
      battle-ready from turn 1.
    - ``"vgc_selected_four"``: the format is
      ``gen9championsvgc2026regma`` (or a sibling
      VGC format). After preview, exactly four
      Pokémon are in the active team and the other
      two are on the bench.

    The mode only affects format-specific legality and
    team-preview behavior. It does NOT create a
    separate scoring / mechanics / joint-selection
    implementation — the canonical
    :class:`DoublesDamageAwarePlayer` engine is used in
    both modes.
    """

    RUNTIME_MODE = "vgc_selected_four"

    def __init__(
        self,
        *args,
        preview_result=None,
        battle_tag: str = "",
        pair_id: int = 0,
        side: str = "p1",
        audit_logger=None,
        **kwargs
    ):
        # VGC format uses gen9championsvgc2026regma by
        # default. The canonical engine accepts any
        # ``battle_format`` so the runner can pass it
        # explicitly.
        kwargs['avatar'] = None
        kwargs['start_listening'] = False
        # The canonical ``DoublesDamageAwarePlayer``
        # constructor sets up the per-turn tracking
        # dicts. We forward ``audit_logger`` so the
        # canonical engine records its decisions.
        kwargs.setdefault('audit_logger', audit_logger)
        super().__init__(*args, **kwargs)

        self.ps_client = NoAvatarPSClient(
            account_configuration=self.ps_client._account_configuration,
            avatar=None,
            log_level=self.ps_client._logger.level,
            on_battle_message=self.ps_client._on_battle_message,
            on_update_challenges=self.ps_client._on_update_challenges,
            on_challenge_request=self.ps_client._on_challenge_request,
            server_configuration=self.ps_client._server_configuration,
            start_listening=True,
            open_timeout=self.ps_client._open_timeout,
            ping_interval=self.ps_client._ping_interval,
            ping_timeout=self.ps_client._ping_timeout,
            loop=self.ps_client.loop,
        )

        self._preview_result = preview_result
        self._battle_tag = battle_tag
        self._pair_id = pair_id
        self._side = side
        self._teampreview_emitted = None
        self._teampreview_matches_plan = False
        self._actual_lead_on_turn1 = []       # Derived legacy field (from planned)
        self._observed_actual_lead_on_turn1 = []  # NEW: Observed from protocol
        self._selected_species = []
        # V2l — runtime mode boundary. The canonical
        # engine's ``audit_logger`` records this so the
        # parity inspector can prove which mode was
        # active for every turn. The base class
        # defaults to ``"random_doubles"``; the VGC
        # player overrides it here. The
        # ``shared_engine_used`` flag is the proof
        # bit the parity inspector checks.
        self._runtime_mode = self.RUNTIME_MODE
        self._concrete_player_class = type(self).__name__
        self._shared_engine_used = True
        # Selected four from preview. The engine
        # passes these into the audit log so the
        # inspector can prove the VGC runtime picked
        # exactly four Pokémon.
        if self._preview_result is not None:
            self._selected_four = list(
                self._preview_result.chosen_4
            )
            self._lead_2 = list(
                self._preview_result.lead_2
            )
            self._back_2 = list(
                self._preview_result.back_2
            )
            self._preview_policy = (
                self._preview_result.policy
            )
        else:
            self._selected_four = None
            self._lead_2 = None
            self._back_2 = None
            self._preview_policy = None

    def teampreview(self, battle: Battle) -> str:
        """
        Override teampreview to use the pre-planned PreviewResult.

        Maps chosen species to actual battle.team positions,
        preserves lead_2 order as first two positions,
        preserves back_2 order as positions three and four,
        marks each selected Pokemon _selected_in_teampreview = True,
        returns '/team ABCD' format.

        Raises ValueError for missing, duplicate, or ambiguous species mappings.
        """
        if self._preview_result is None:
            raise ValueError(f"ControlledTeamPreviewPlayer: no preview_result provided for {self._battle_tag}")

        # Get all 6 Pokemon in battle.team (they should be in party order)
        battle_team = list(battle.team.values())
        if len(battle_team) != 6:
            raise ValueError(f"Expected 6 Pokemon in battle.team, got {len(battle_team)} for {self._battle_tag}")

        # Build species to index mapping
        species_to_indices = {}
        for idx, p in enumerate(battle_team):
            species = p.species.lower()
            if species not in species_to_indices:
                species_to_indices[species] = []
            species_to_indices[species].append(idx)

        # Map chosen_4 species to positions
        planned_order = self._preview_result.lead_2 + self._preview_result.back_2  # 4 species
        if len(planned_order) != 4:
            raise ValueError(f"Planned order must have 4 species for {self._battle_tag}")

        selected_indices = []
        for species in planned_order:
            species_key = species.lower()
            if species_key not in species_to_indices:
                raise ValueError(f"Species '{species}' from preview not found in battle team for {self._battle_tag}")
            indices = species_to_indices[species_key]
            if len(indices) > 1:
                raise ValueError(f"Ambiguous mapping: species '{species}' appears {len(indices)} times in team for {self._battle_tag}")
            selected_indices.append(indices[0])

        # Check for duplicates
        if len(set(selected_indices)) != 4:
            raise ValueError(f"Duplicate species indices in preview selection for {self._battle_tag}")

        # Build /team string: positions are 1-indexed in Showdown
        team_positions = [str(idx + 1) for idx in selected_indices]
        teampreview_order = "/team " + "".join(team_positions)

        # Mark selected Pokemon
        for idx in selected_indices:
            battle_team[idx]._selected_in_teampreview = True
            self._selected_species.append(battle_team[idx].species)

        self._teampreview_emitted = teampreview_order
        self._teampreview_matches_plan = True

        return teampreview_order

    def choose_move(self, battle: Battle):
        """V2l — choose_move delegates to the canonical
        :class:`DoublesDamageAwarePlayer.choose_move` so
        VGC post-preview turns use the SAME engine as
        Random Doubles.

        Behavior is otherwise unchanged: capture the
        observed lead on first non-empty active state.
        """
        # Capture the first non-empty active Pokémon state exactly once
        if not self._observed_actual_lead_on_turn1:
            # Normalize active_pokemon: could be dict, list, or tuple
            active_pokemon = getattr(battle, 'active_pokemon', None)
            if active_pokemon:
                observed = []
                # Handle dict (position -> Pokemon), list, or tuple
                if isinstance(active_pokemon, dict):
                    for pos in sorted(active_pokemon.keys()):
                        p = active_pokemon[pos]
                        if p and getattr(p, 'species', None):
                            observed.append(p.species)
                elif isinstance(active_pokemon, (list, tuple)):
                    for p in active_pokemon:
                        if p and getattr(p, 'species', None):
                            observed.append(p.species)
                if len(observed) >= 2:
                    self._observed_actual_lead_on_turn1 = observed[:2]
        # Delegate to the canonical engine. The
        # ``DoublesDamageAwarePlayer.choose_move`` returns
        # the canonical ``DoubleBattleOrder`` for the
        # shared runtime.
        return DoublesDamageAwarePlayer.choose_move(self, battle)

    def get_preview_evidence(self) -> Dict[str, Any]:
        """
        Return preview evidence for logging.

        Note: actual_lead_on_turn1 is derived from planned lead_2 (legacía).
        observed_actual_lead_on_turn1 is captured from protocol state.
        """
        return {
            "battle_tag": self._battle_tag,
            "pair_id": self._pair_id,
            "side": self._side,
            "planned_chosen_4": self._preview_result.chosen_4 if self._preview_result else [],
            "planned_lead_2": self._preview_result.lead_2 if self._preview_result else [],
            "planned_back_2": self._preview_result.back_2 if self._preview_result else [],
            "emitted_teampreview": self._teampreview_emitted,
            "actual_selected_species": self._selected_species,
            "actual_lead_on_turn1": self._preview_result.lead_2 if self._preview_result else [],  # Legacy derived
            "observed_actual_lead_on_turn1": self._observed_actual_lead_on_turn1,  # NEW: Observed
            "preview_matches_plan": self._teampreview_matches_plan,
            "player_policy": self._preview_result.policy if self._preview_result else "unknown",
        }


# ===== Player Factory =====

def create_controlled_player(
    account: AccountConfiguration,
    team_str: str,
    preview_result: PreviewResult,
    battle_tag: str,
    pair_id: int,
    side: str,
    format_name: str = "gen9championsvgc2026regma",
    audit_logger: Optional["DoublesDecisionAuditLogger"] = None,
) -> ControlledTeamPreviewPlayer:
    """Create a ``ControlledTeamPreviewPlayer`` with the
    given preview result.

    V2l.1 — ``audit_logger`` is forwarded to the
    canonical engine so every post-preview
    ``DoublesDamageAwarePlayer.choose_move`` call
    is recorded in the runtime-parity JSONL. Pass
    ``None`` for legacy use without audit logging
    (the canonical engine still runs; only audit
    recording is disabled).
    """
    player = ControlledTeamPreviewPlayer(
        account_configuration=account,
        server_configuration=LOCAL_SERVER_CONFIG,
        battle_format=format_name,
        team=team_str,
        preview_result=preview_result,
        battle_tag=battle_tag,
        pair_id=pair_id,
        side=side,
        audit_logger=audit_logger,
    )
    return player


# ===== Data Classes =====

@dataclass
class PreviewEvidence:
    """Evidence about team preview execution."""
    battle_tag: str
    pair_id: int
    side: str
    player_policy: str
    opponent_policy: str
    planned_chosen_4: List[str]
    planned_lead_2: List[str]
    planned_back_2: List[str]
    emitted_teampreview: str
    actual_selected_species: List[str]
    actual_lead_on_turn1: List[str]           # Legacy derived
    observed_actual_lead_on_turn1: List[str]  # NEW: Observed from protocol
    preview_matches_plan: bool

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BattleLog:
    """Complete battle log with preview evidence."""
    battle_tag: str
    pair_id: int
    side: str
    team_id: str
    rank: int
    player: str
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_id: str
    opponent_chosen_4: List[str]
    player_policy: str
    opponent_policy: str
    battle_result: str  # "win", "loss", "tie", "error", "timeout", "no_battle"
    our_win: bool
    opponent_win: bool
    tie: bool
    errors: str
    turns: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Preview evidence for both players
    our_preview_evidence: Optional[PreviewEvidence] = None
    opponent_preview_evidence: Optional[PreviewEvidence] = None

    def to_csv_row(self) -> List:
        return [
            self.battle_tag, self.pair_id, self.side,
            self.team_id, self.rank, self.player,
            "|".join(self.chosen_4), "|".join(self.lead_2), "|".join(self.back_2),
            self.opponent_team_id, "|".join(self.opponent_chosen_4),
            self.player_policy, self.opponent_policy,
            self.battle_result, self.our_win, self.opponent_win, self.tie,
            self.errors, self.turns, self.timestamp
        ]

    def to_json_dict(self) -> Dict:
        d = asdict(self)
        if self.our_preview_evidence:
            d['our_preview_evidence'] = self.our_preview_evidence.to_dict()
        if self.opponent_preview_evidence:
            d['opponent_preview_evidence'] = self.opponent_preview_evidence.to_dict()
        return d


# ===== Team Serialization =====

def build_team_string(team, chosen_4: List[str]) -> str:
    """Build team string with ALL 6 Pokemon using 'Species (Species) @ Item' format.

    Accepts either a VGCTeam object (with .pokemon attribute) or a plain list of Pokemon dicts.
    """
    all_pokemon = team.pokemon if hasattr(team, 'pokemon') else team
    team_lines = []
    for p in all_pokemon:
        item_str = p.get("item")
        species_cap = p['species'].capitalize()
        if item_str and item_str.lower() != "no item":
            team_lines.append(f"{species_cap} ({species_cap}) @ {item_str}")
        else:
            team_lines.append(f"{species_cap} ({species_cap})")
        if p.get("ability"):
            team_lines.append(f"Ability: {p['ability']}")
        if p.get("tera_type"):
            team_lines.append(f"Tera Type: {p['tera_type']}")
        team_lines.append(f"Level: {p.get('level', 50)}")

        evs = p.get("evs", {})
        ev_lines = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
        if ev_lines:
            team_lines.append(f"EVs: {' / '.join(ev_lines)}")

        if p.get("nature"):
            team_lines.append(f"{p['nature'].capitalize()} Nature")

        ivs = p.get("ivs", {})
        # FIX: IV line outputs the real IV value v, not 31-v
        iv_parts = [f"{v} {k.upper()}" for k, v in ivs.items() if v != 31]
        if iv_parts:
            team_lines.append(f"IVs: {' / '.join(iv_parts)}")

        for move in p.get("moves", []):
            team_lines.append(f"- {move}")

        team_lines.append("")

    return "\n".join(team_lines).strip()


def validate_team_for_battle(team_str: str) -> Tuple[bool, str]:
    """Parse team through ConstantTeambuilder to verify it works."""
    try:
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        if len(parsed) != 6:
            return False, f"Expected 6 Pokemon, got {len(parsed)}"
        for p in parsed:
            if not p.species:
                return False, f"Pokemon missing species: {p}"
        return True, ""
    except Exception as e:
        return False, f"Failed to parse team: {e}"


# ===== Account Configuration =====

def extract_rank(team_id: str) -> str:
    """Extract rank from team ID for username."""
    for part in team_id.split('_'):
        if part.isdigit():
            return f"{int(part):03d}"
    return team_id[-6:]


def create_account_configs(
    our_team_id: str,
    opp_team_id: str,
    battle_index: int,
    pair_id: int,
    side: str
) -> Tuple[AccountConfiguration, AccountConfiguration]:
    """Create unique account configurations for both players."""
    import time
    import random as _rnd

    # Keep under 18 chars: b_ + rank(3) + _ + suffix(12) = 17
    base_suffix = f"{battle_index:04d}{int(time.time() * 1000) % 10000:04d}{_rnd.randint(10,99):02d}"
    our_rank = extract_rank(our_team_id)
    opp_rank = extract_rank(opp_team_id)

    # Differentiate p1 and p2
    suffix1 = f"{base_suffix}0"
    suffix2 = f"{base_suffix}1"

    if side == "p1":
        our_account = AccountConfiguration(f"b_{our_rank}_{suffix1}", None)
        opp_account = AccountConfiguration(f"b_{opp_rank}_{suffix2}", None)
    else:
        our_account = AccountConfiguration(f"b_{our_rank}_{suffix2}", None)
        opp_account = AccountConfiguration(f"b_{opp_rank}_{suffix1}", None)

    return our_account, opp_account


# ===== Artifact Safety =====

def resolve_artifact_paths(log_dir: Path, artifact_tag: Optional[str] = None) -> Tuple[Path, Path, Path]:
    """Resolve artifact file paths based on artifact tag.

    If artifact_tag is None, uses default V2c names.
    If artifact_tag is provided, appends it to create unique names.
    """
    if artifact_tag is None:
        csv_name = DEFAULT_CSV_NAME
        jsonl_name = DEFAULT_JSONL_NAME
        preview_name = DEFAULT_PREVIEW_CSV_NAME
    else:
        # Insert tag before extension
        csv_name = f"vgc2026_phaseV2c_{artifact_tag}_benchmark.csv"
        jsonl_name = f"vgc2026_phaseV2c_{artifact_tag}_benchmark.jsonl"
        preview_name = f"vgc2026_phaseV2c_{artifact_tag}_preview_evidence.csv"

    return (
        log_dir / csv_name,
        log_dir / jsonl_name,
        log_dir / preview_name
    )


def check_artifacts_exist(log_dir: Path, artifact_tag: Optional[str] = None) -> bool:
    """Check if any target artifact files exist."""
    csv_path, jsonl_path, preview_path = resolve_artifact_paths(log_dir, artifact_tag)
    return csv_path.exists() or jsonl_path.exists() or preview_path.exists()


def init_artifacts_atomic(
    csv_path: Path,
    jsonl_path: Path,
    preview_path: Path,
    overwrite: bool = False
) -> None:
    """Initialize artifact files atomically.

    Refuses to initialize if files exist and overwrite=False.
    Creates files atomically using temporary files.
    """
    if not overwrite and (csv_path.exists() or jsonl_path.exists() or preview_path.exists()):
        raise FileExistsError(
            f"Artifact files already exist (use --overwrite to replace): "
            f"csv={csv_path.exists()}, jsonl={jsonl_path.exists()}, preview={preview_path.exists()}"
        )

    # Create temp files first, then atomically move
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', dir=csv_path.parent) as tf:
        writer = csv.writer(tf)
        writer.writerow([
            "battle_tag", "pair_id", "side",
            "team_id", "rank", "player",
            "chosen_4", "lead_2", "back_2",
            "opponent_team_id", "opponent_chosen_4",
            "player_policy", "opponent_policy",
            "battle_result", "our_win", "opponent_win", "tie",
            "errors", "turns", "timestamp"
        ])
        temp_csv = tf.name

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', dir=preview_path.parent) as tf:
        writer = csv.writer(tf)
        writer.writerow([
            "battle_tag", "pair_id", "side",
            "player_policy", "opponent_policy",
            "planned_chosen_4", "planned_lead_2", "planned_back_2",
            "emitted_teampreview", "actual_selected_species", "actual_lead_on_turn1",
            "observed_actual_lead_on_turn1",
            "preview_matches_plan"
        ])
        temp_preview = tf.name

    # Move temp files to final locations
    import shutil
    shutil.move(temp_csv, csv_path)
    jsonl_path.write_text("")
    shutil.move(temp_preview, preview_path)


# ===== Battle Runner =====

class VGCBattleRunnerV2c:
    """VGC 2026 Battle Runner with Controlled Team Preview — Phase V2c.2.

    V2l.1 — runtime audit logging.

    The runner owns a unique runtime-parity JSONL
    path. Both players (p1 and p2) get separate
    audit loggers so the post-preview
    ``DoublesDamageAwarePlayer.choose_move`` flows
    from BOTH sides land in a single shared
    runtime-parity JSONL. The path defaults to
    ``logs/<artifact_tag>_runtime_audit.jsonl`` and
    can be supplied explicitly via
    ``runtime_audit_path``. Legacy use without
    runtime audit logging continues to work — pass
    ``runtime_audit_path=None`` (default behavior
    when the user does not request parity proof).
    """

    def __init__(
        self,
        format_name: str = "gen9championsvgc2026regma",
        max_rank: Optional[int] = None,
        parse_status: str = "any",
        limit_teams: Optional[int] = None,
        seed: int = 42,
        log_dir: str = "logs",
        artifact_tag: Optional[str] = None,
        overwrite: bool = False,
        smoke: bool = False,
        smoke_battles: int = 2,  # per arm
        runtime_audit_path: Optional[str] = None,
    ):
        self.format_name = format_name
        self.max_rank = max_rank
        self.parse_status = parse_status
        self.limit_teams = limit_teams
        self.seed = seed
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.artifact_tag = artifact_tag
        self.overwrite = overwrite
        self.smoke = smoke
        self.smoke_battles = smoke_battles

        # Resolve artifact paths
        self.csv_path, self.jsonl_path, self.preview_csv_path = resolve_artifact_paths(
            self.log_dir, self.artifact_tag
        )

        # Artifact safety: refuse to start if artifacts exist without --overwrite
        if check_artifacts_exist(self.log_dir, self.artifact_tag) and not self.overwrite:
            raise FileExistsError(
                f"Artifact files already exist for tag '{self.artifact_tag or 'default'}'. "
                f"Use --overwrite to replace: "
                f"csv={self.csv_path.exists()}, jsonl={self.jsonl_path.exists()}, preview={self.preview_csv_path.exists()}"
            )

        self.my_pool = load_vgc_pool(
            max_rank=max_rank,
            parse_status=parse_status,
            limit=limit_teams,
            seed=seed
        )
        self.opponent_pool = load_vgc_pool(
            max_rank=max_rank,
            parse_status=parse_status,
            limit=limit_teams,
            seed=seed + 1000
        )

        # Smoke uses unique tag by default
        if self.smoke and not self.artifact_tag:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.artifact_tag = f"phaseV2c3_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.csv_path, self.jsonl_path, self.preview_csv_path = resolve_artifact_paths(
                self.log_dir, self.artifact_tag
            )
            # Smoke never uses default paths - must have unique tag

        # Atomic initialization
        init_artifacts_atomic(self.csv_path, self.jsonl_path, self.preview_csv_path, overwrite=self.overwrite)

        # V2l.1 — runtime-parity audit JSONL.
        # If the caller did not supply a path, we
        # derive one from the artifact tag. The JSONL
        # is collision-safe for both players (p1 and
        # p2 share the same file). Legacy callers that
        # do not request runtime audit logging should
        # pass ``runtime_audit_path=None`` and we will
        # leave ``runtime_audit_logger`` unset, which
        # causes ``ControlledTeamPreviewPlayer`` to
        # use the canonical engine without audit
        # recording.
        if runtime_audit_path is not None:
            self.runtime_audit_path = Path(runtime_audit_path)
        elif self.artifact_tag:
            self.runtime_audit_path = (
                self.log_dir
                / f"{self.artifact_tag}_runtime_audit.jsonl"
            )
        else:
            self.runtime_audit_path = None
        # Audit state must be isolated per player. The
        # logger stores pending turns by battle tag, so
        # sharing one logger object between p1 and p2
        # would let the two perspectives overwrite each
        # other. Separate logger objects append to the
        # same JSONL while retaining independent state.
        self._runtime_audit_logger = None  # legacy alias
        self._runtime_audit_logger_lock = None
        self._runtime_audit_loggers_by_player: Dict[
            str, "DoublesDecisionAuditLogger"
        ] = {}

        self._pair_counter = 0

    def _get_runtime_audit_logger(
        self, side_label: str
    ) -> Optional["DoublesDecisionAuditLogger"]:
        """V2l.1 — lazy-create the runtime audit
        logger for one player side. Both p1 and p2
        append to the same JSONL file, but each side
        owns an independent logger state machine.
        """
        if self.runtime_audit_path is None:
            return None
        try:
            from doubles_decision_audit_logger import (
                DoublesDecisionAuditLogger
            )
        except ImportError:
            return None
        logger = self._runtime_audit_loggers_by_player.get(side_label)
        if logger is None:
            reset = not self._runtime_audit_loggers_by_player
            logger = DoublesDecisionAuditLogger(
                filepath=str(self.runtime_audit_path),
                reset=reset,
                detail_level="top5",
            )
            self._runtime_audit_loggers_by_player[side_label] = logger
            if self._runtime_audit_logger is None:
                self._runtime_audit_logger = logger
        return logger

    def _log_battle(self, log: BattleLog):
        """Log battle to CSV and JSONL."""
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(log.to_csv_row())

        with open(self.jsonl_path, 'a') as f:
            f.write(json.dumps(log.to_json_dict()) + "\n")

        # Log preview evidence separately
        if log.our_preview_evidence:
            with open(self.preview_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                p = log.our_preview_evidence
                writer.writerow([
                    p.battle_tag, p.pair_id, p.side,
                    p.player_policy, p.opponent_policy,
                    "|".join(p.planned_chosen_4), "|".join(p.planned_lead_2), "|".join(p.planned_back_2),
                    p.emitted_teampreview, "|".join(p.actual_selected_species), "|".join(p.actual_lead_on_turn1),
                    "|".join(p.observed_actual_lead_on_turn1),
                    p.preview_matches_plan
                ])

        if log.opponent_preview_evidence:
            with open(self.preview_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                p = log.opponent_preview_evidence
                writer.writerow([
                    p.battle_tag, p.pair_id, p.side,
                    p.player_policy, p.opponent_policy,
                    "|".join(p.planned_chosen_4), "|".join(p.planned_lead_2), "|".join(p.planned_back_2),
                    p.emitted_teampreview, "|".join(p.actual_selected_species), "|".join(p.actual_lead_on_turn1),
                    "|".join(p.observed_actual_lead_on_turn1),
                    p.preview_matches_plan
                ])

    def _log_preview_error(self, battle_tag: str, pair_id: int, side: str,
                           player_policy: str, opponent_policy: str,
                           planned_chosen_4: List[str], planned_lead_2: List[str], planned_back_2: List[str],
                           error: str):
        """Log preview validation error."""
        with open(self.preview_csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                battle_tag, pair_id, side,
                player_policy, opponent_policy,
                "|".join(planned_chosen_4), "|".join(planned_lead_2), "|".join(planned_back_2),
                f"ERROR: {error}", "", "", False
            ])

    async def _run_single_battle(
        self,
        our_team,
        opponent_team,
        battle_tag: str,
        pair_id: int,
        side: str,
        player_policy: str,
        opponent_policy: str,
        battle_index: int
    ) -> BattleLog:
        """Run a single battle with controlled team preview for both players."""
        our_pokemon = our_team.pokemon
        opp_pokemon = opponent_team.pokemon

        # Generate previews for both players
        our_seed, opp_seed = self.get_preview_seeds(
            pair_id, battle_index, player_policy, opponent_policy
        )

        our_preview = choose_four_from_six(
            our_pokemon, opponent_team=opp_pokemon,
            policy=player_policy, seed=our_seed
        )
        opp_preview = choose_four_from_six(
            opp_pokemon, opponent_team=our_pokemon,
            policy=opponent_policy, seed=opp_seed
        )

        # Validate both previews
        valid, errors = validate_preview(our_pokemon, our_preview)
        if not valid:
            self._log_preview_error(
                battle_tag, pair_id, side,
                player_policy, opponent_policy,
                our_preview.chosen_4, our_preview.lead_2, our_preview.back_2,
                f"Our preview invalid: {errors}"
            )
            return BattleLog(
                battle_tag=battle_tag, pair_id=pair_id, side=side,
                team_id=our_team.id, rank=our_team.rank, player=our_team.player,
                chosen_4=our_preview.chosen_4, lead_2=our_preview.lead_2, back_2=our_preview.back_2,
                opponent_team_id=opponent_team.id, opponent_chosen_4=opp_preview.chosen_4,
                player_policy=player_policy, opponent_policy=opponent_policy,
                battle_result="error", our_win=False, opponent_win=False, tie=False,
                errors=f"Preview validation: {errors}", turns=0
            )

        valid, errors = validate_preview(opp_pokemon, opp_preview)
        if not valid:
            self._log_preview_error(
                battle_tag, pair_id, side,
                player_policy, opponent_policy,
                opp_preview.chosen_4, opp_preview.lead_2, opp_preview.back_2,
                f"Opponent preview invalid: {errors}"
            )
            return BattleLog(
                battle_tag=battle_tag, pair_id=pair_id, side=side,
                team_id=our_team.id, rank=our_team.rank, player=our_team.player,
                chosen_4=our_preview.chosen_4, lead_2=our_preview.lead_2, back_2=our_preview.back_2,
                opponent_team_id=opponent_team.id, opponent_chosen_4=opp_preview.chosen_4,
                player_policy=player_policy, opponent_policy=opponent_policy,
                battle_result="error", our_win=False, opponent_win=False, tie=False,
                errors=f"Opponent preview validation: {errors}", turns=0
            )

        # Build team strings
        our_team_str = build_team_string(our_team, our_preview.chosen_4)
        opp_team_str = build_team_string(opponent_team, opp_preview.chosen_4)

        # Validate team strings parse correctly
        valid, error = validate_team_for_battle(our_team_str)
        if not valid:
            return BattleLog(
                battle_tag=battle_tag, pair_id=pair_id, side=side,
                team_id=our_team.id, rank=our_team.rank, player=our_team.player,
                chosen_4=our_preview.chosen_4, lead_2=our_preview.lead_2, back_2=our_preview.back_2,
                opponent_team_id=opponent_team.id, opponent_chosen_4=opp_preview.chosen_4,
                player_policy=player_policy, opponent_policy=opponent_policy,
                battle_result="error", our_win=False, opponent_win=False, tie=False,
                errors=f"Our team serialization: {error}", turns=0
            )

        valid, error = validate_team_for_battle(opp_team_str)
        if not valid:
            return BattleLog(
                battle_tag=battle_tag, pair_id=pair_id, side=side,
                team_id=our_team.id, rank=our_team.rank, player=our_team.player,
                chosen_4=our_preview.chosen_4, lead_2=our_preview.lead_2, back_2=our_preview.back_2,
                opponent_team_id=opponent_team.id, opponent_chosen_4=opp_preview.chosen_4,
                player_policy=player_policy, opponent_policy=opponent_policy,
                battle_result="error", our_win=False, opponent_win=False, tie=False,
                errors=f"Opponent team serialization: {error}", turns=0
            )

        # Create account configs
        our_account, opp_account = create_account_configs(
            our_team.id, opponent_team.id, battle_index, pair_id, side
        )

        # Each player gets independent pending/completed
        # state while both loggers append to one file.
        our_runtime_audit_logger = self._get_runtime_audit_logger(
            f"{battle_tag}|p1"
        )
        opp_runtime_audit_logger = self._get_runtime_audit_logger(
            f"{battle_tag}|p2"
        )

        # Create players with controlled preview
        our_bot = create_controlled_player(
            our_account, our_team_str, our_preview,
            battle_tag, pair_id, "p1", self.format_name,
            audit_logger=our_runtime_audit_logger,
        )
        opp_bot = create_controlled_player(
            opp_account, opp_team_str, opp_preview,
            battle_tag, pair_id, "p2", self.format_name,
            audit_logger=opp_runtime_audit_logger,
        )

        # V2l.1 — record the audit logger instances
        # handed to each player for the parity test.
        if our_runtime_audit_logger is not None:
            self._runtime_audit_loggers_by_player[
                f"{battle_tag}|p1"
            ] = our_runtime_audit_logger
            self._runtime_audit_loggers_by_player[
                f"{battle_tag}|p2"
            ] = opp_runtime_audit_logger

        # Run battle with watchdog
        errors = ""
        our_win = False
        opponent_win = False
        tie = False
        battle_result = "error"
        turns = 0

        try:
            # Battle with timeout
            await asyncio.wait_for(
                our_bot.battle_against(opp_bot, n_battles=1),
                timeout=BATTLE_TIMEOUT
            )

            # Get battle result
            our_battle = list(our_bot.battles.values())[0] if our_bot.battles else None
            if our_battle:
                if our_battle.won:
                    our_win = True
                    opponent_win = False
                    battle_result = "win"
                elif our_battle.lost:
                    our_win = False
                    opponent_win = True
                    battle_result = "loss"
                else:
                    tie = True
                    battle_result = "tie"
                turns = our_battle.turn
            else:
                battle_result = "no_battle"
                turns = 0

        except asyncio.TimeoutError:
            battle_result = "timeout"
            errors = f"Battle timed out after {BATTLE_TIMEOUT}s"
        except Exception as e:
            battle_result = "error"
            errors = str(e)

        # Collect preview evidence
        our_evidence = our_bot.get_preview_evidence() if hasattr(our_bot, 'get_preview_evidence') else None
        opp_evidence = opp_bot.get_preview_evidence() if hasattr(opp_bot, 'get_preview_evidence') else None

        # Add opponent policy to both evidence dicts
        if our_evidence:
            our_evidence['opponent_policy'] = opponent_policy
        if opp_evidence:
            opp_evidence['opponent_policy'] = player_policy  # From opponent's perspective

        return BattleLog(
            battle_tag=battle_tag, pair_id=pair_id, side=side,
            team_id=our_team.id, rank=our_team.rank, player=our_team.player,
            chosen_4=our_preview.chosen_4, lead_2=our_preview.lead_2, back_2=our_preview.back_2,
            opponent_team_id=opponent_team.id, opponent_chosen_4=opp_preview.chosen_4,
            player_policy=player_policy, opponent_policy=opponent_policy,
            battle_result=battle_result, our_win=our_win, opponent_win=opponent_win, tie=tie,
            errors=errors, turns=turns,
            our_preview_evidence=PreviewEvidence(**our_evidence) if our_evidence else None,
            opponent_preview_evidence=PreviewEvidence(**opp_evidence) if opp_evidence else None
        )

    def get_preview_seeds(
        self,
        pair_id: int,
        battle_index: int,
        player_policy: str,
        opponent_policy: str,
    ) -> Tuple[int, int]:
        """Return preview seeds for both sides.

        Subclasses may override this to keep policy randomness stable across
        paired side swaps.
        """
        our_seed = self.seed + pair_id * 1000 + battle_index
        return our_seed, our_seed + 1

    async def run_arm(
        self,
        arm_name: str,
        battles: List[Dict[str, Any]]
    ) -> List[BattleLog]:
        """Run a specific arm of the benchmark."""
        print(f"Running {arm_name}: {len(battles)} battles...")

        my_teams = list(self.my_pool)
        opp_teams = list(self.opponent_pool)
        results = []

        start_time = time.time()
        last_heartbeat = start_time

        for i, battle_spec in enumerate(battles):
            # Watchdog: total arm timeout
            if time.time() - start_time > ARM_TIMEOUT:
                print(f"  ARM TIMEOUT after {ARM_TIMEOUT}s")
                break

            # Heartbeat
            if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                print(f"  Heartbeat: {i}/{len(battles)} battles completed in {arm_name}")
                last_heartbeat = time.time()

            our_team = my_teams[battle_spec['our_team_idx'] % len(my_teams)]
            opp_team = opp_teams[battle_spec['opp_team_idx'] % len(opp_teams)]

            battle_tag = f"{arm_name}_{battle_spec['pair_id']:04d}_{battle_spec['side']}"

            try:
                log = await asyncio.wait_for(
                    self._run_single_battle(
                        our_team, opp_team,
                        battle_tag, battle_spec['pair_id'], battle_spec['side'],
                        battle_spec['player_policy'], battle_spec['opponent_policy'],
                        i
                    ),
                    timeout=BATTLE_TIMEOUT + CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                log = BattleLog(
                    battle_tag=battle_tag, pair_id=battle_spec['pair_id'], side=battle_spec['side'],
                    team_id=our_team.id, rank=our_team.rank, player=our_team.player,
                    chosen_4=[], lead_2=[], back_2=[],
                    opponent_team_id=opp_team.id, opponent_chosen_4=[],
                    player_policy=battle_spec['player_policy'], opponent_policy=battle_spec['opponent_policy'],
                    battle_result="timeout", our_win=False, opponent_win=False, tie=False,
                    errors=f"Arm timeout after {BATTLE_TIMEOUT + CLEANUP_TIMEOUT}s", turns=0
                )

            results.append(log)
            self._log_battle(log)

            if i % 10 == 0 and i > 0:
                print(f"  Completed {i}/{len(battles)}")

        print(f"  Completed {len(results)}/{len(battles)} in {arm_name}")
        return results

    def generate_arm_specifications(self) -> Dict[str, List[Dict]]:
        """Generate battle specifications for all arms."""
        my_teams = list(self.my_pool)
        opp_teams = list(self.opponent_pool)

        specs = {
            "A": [],  # basic_top4 vs random_4_from_6 — stability smoke
            "B": [],  # basic_top4 vs basic_top4 — mirror sanity
            "C": [],  # random_4_from_6 vs random_4_from_6 — mirror sanity
            "D1": [], # basic_top4 as p1 vs random_4_from_6 as p2 (paired)
            "D2": [], # random_4_from_6 as p1 vs basic_top4 as p2 (paired)
        }

        pair_id = 0

        # Arm A: basic_top4 vs random_4_from_6 (smoke_battles for smoke, 50 for full)
        n_a = self.smoke_battles if self.smoke else 50
        for i in range(n_a):
            specs["A"].append({
                'pair_id': i,
                'our_team_idx': i % len(my_teams),
                'opp_team_idx': i % len(opp_teams),
                'side': 'p1',
                'player_policy': 'basic_top4',
                'opponent_policy': 'random'
            })

        # Arm B: basic_top4 vs basic_top4 mirror (smoke_battles for smoke, 100 for full)
        n_b = self.smoke_battles if self.smoke else 100
        for i in range(n_b):
            specs["B"].append({
                'pair_id': i,
                'our_team_idx': i % len(my_teams),
                'opp_team_idx': (i + 1) % len(opp_teams),
                'side': 'p1',
                'player_policy': 'basic_top4',
                'opponent_policy': 'basic_top4'
            })

        # Arm C: random_4_from_6 vs random_4_from_6 mirror (smoke_battles for smoke, 100 for full)
        n_c = self.smoke_battles if self.smoke else 100
        for i in range(n_c):
            specs["C"].append({
                'pair_id': i,
                'our_team_idx': i % len(my_teams),
                'opp_team_idx': (i + 2) % len(opp_teams),
                'side': 'p1',
                'player_policy': 'random',
                'opponent_policy': 'random'
            })

        # Arms D1/D2: Paired basic_top4 vs random_4_from_6 (smoke_battles pairs for smoke, 100 for full)
        n_d = self.smoke_battles if self.smoke else 100
        for i in range(n_d):
            # D1: basic_top4 as p1 vs random as p2
            specs["D1"].append({
                'pair_id': i,
                'our_team_idx': i % len(my_teams),
                'opp_team_idx': i % len(opp_teams),
                'side': 'p1',
                'player_policy': 'basic_top4',
                'opponent_policy': 'random'
            })
            # D2: random as p1 vs basic_top4 as p2 (same teams, swapped sides)
            specs["D2"].append({
                'pair_id': i,
                'our_team_idx': i % len(my_teams),
                'opp_team_idx': i % len(opp_teams),
                'side': 'p2',
                'player_policy': 'random',
                'opponent_policy': 'basic_top4'
            })

        return specs

    async def run_all(self):
        """Run all benchmark arms."""
        print(f"Starting VGC 2026 Phase V2c.2 Benchmark (CONTROLLED PREVIEW)")
        print(f"Format: {self.format_name}")
        print(f"Teams: {len(self.my_pool)} (my) vs {len(self.opponent_pool)} (opp)")
        print(f"Seed: {self.seed}")
        print(f"Artifact tag: {self.artifact_tag or 'default'}")
        print(f"Overwrite: {self.overwrite}")

        specs = self.generate_arm_specifications()
        self._pair_counter = max(len(specs.get("D1", [])), len(specs.get("D2", [])))

        all_results = {}

        # Run arms in order
        all_results["A"] = await self.run_arm("A", specs["A"])
        all_results["B"] = await self.run_arm("B", specs["B"])
        all_results["C"] = await self.run_arm("C", specs["C"])
        all_results["D1"] = await self.run_arm("D1", specs["D1"])
        all_results["D2"] = await self.run_arm("D2", specs["D2"])

        print("\nAll benchmark arms completed!")
        self._print_summary(all_results)

        return all_results

    def _print_summary(self, results: Dict[str, List[BattleLog]]):
        """Print summary of results."""
        print("\n=== Summary ===")
        total = sum(len(r) for r in results.values())
        print(f"Total battles: {total}")

        for arm, logs in results.items():
            if not logs:
                continue
            wins = sum(1 for l in logs if l.our_win)
            losses = sum(1 for l in logs if l.opponent_win)
            ties = sum(1 for l in logs if l.tie)
            timeouts = sum(1 for l in logs if l.battle_result == "timeout")
            errors = sum(1 for l in logs if l.battle_result == "error")
            no_battle = sum(1 for l in logs if l.battle_result == "no_battle")

            print(f"  {arm}: {wins}W / {losses}L / {ties}T / {timeouts}TO / {errors}Err / {no_battle}NB")

            # Preview match rate
            preview_matches = sum(1 for l in logs
                if l.our_preview_evidence and l.our_preview_evidence.preview_matches_plan)
            preview_total = sum(1 for l in logs if l.our_preview_evidence)
            if preview_total > 0:
                print(f"    Preview match: {preview_matches}/{preview_total}")


# ===== Main Entry Point =====

def parse_args():
    parser = argparse.ArgumentParser(description="VGC 2026 Phase V2c.3 Battle Runner — Controlled Team Preview")
    parser.add_argument("--format", default="gen9championsvgc2026regma")
    parser.add_argument("--max-rank", type=int, default=None)
    parser.add_argument("--parse-status", choices=["complete_ots", "partial_ots", "any"], default="any")
    parser.add_argument("--limit-teams", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test (limited battles per arm)")
    parser.add_argument("--smoke-battles", type=int, default=2, help="Battles per arm for smoke (default: 2)")
    parser.add_argument("--artifact-tag", type=str, default=None, help="Unique artifact tag (required for smoke, auto-generated if omitted)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing artifacts")
    parser.add_argument(
        "--runtime-audit-path",
        type=str,
        default=None,
        help="V2l.1 — path to the runtime-parity audit "
        "JSONL. When supplied, the runner wires a "
        "separate DoublesDecisionAuditLogger state "
        "machine into each side; both append to the "
        "same JSONL. Defaults to "
        "<artifact_tag>_runtime_audit.jsonl when an "
        "artifact tag is given; otherwise None "
        "(legacy use without runtime audit logging).",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Auto-generate artifact tag for smoke if not provided
    if args.smoke and args.artifact_tag is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.artifact_tag = f"phaseV2c3_smoke_{timestamp}"
        print(f"Auto-generated artifact tag for smoke: {args.artifact_tag}")

    # Full run without artifact tag uses default paths (requires --overwrite to replace)
    if not args.smoke and args.artifact_tag is None:
        print("Warning: Running full benchmark with default artifact names. Use --artifact-tag for unique naming.")

    runner = VGCBattleRunnerV2c(
        format_name=args.format,
        max_rank=args.max_rank,
        parse_status=args.parse_status,
        limit_teams=args.limit_teams,
        seed=args.seed,
        log_dir=args.log_dir,
        artifact_tag=args.artifact_tag,
        overwrite=args.overwrite,
        smoke=args.smoke,
        smoke_battles=args.smoke_battles,
        runtime_audit_path=args.runtime_audit_path,
    )

    if args.smoke:
        print("Running smoke test...")

    await runner.run_all()


if __name__ == "__main__":
    asyncio.run(main())
