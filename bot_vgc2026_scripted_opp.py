#!/usr/bin/env python3
"""Phase SCENARIO-3 — Scripted Opponent Player.

A poke-env Player that follows a scripted
action sequence loaded from a scenario
file (see scenario_probe.py).

This player inherits from poke_env.Player
(NOT from any bot class) to prevent any
cross-talk with the damage-aware bot. The
scripted opp is intentionally a thin wrapper
that just executes the scenario script.

Anti-leak guarantees:
1. Inherits from base Player (not bot)
2. No access to the bot's scoring or
   config
3. Script is loaded from a file
   (no in-memory leakage)
4. choose_move returns the scripted
   action; falls back to a default safe
   action if the script is invalid

The player exposes metadata for the
audit logger:
- self.scenario_id
- self.scenario_failures: list of
  (turn, slot, action, reason)
- self.scenario_actions: list of
  (turn, slot, action, executed)
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.player.battle_order import (
    BattleOrder,
    DefaultBattleOrder,
    DoubleBattleOrder,
    PassBattleOrder,
    SingleBattleOrder,
)
from poke_env.player.player import Player

from scenario_probe import (
    Scenario,
    ScenarioAction,
    ScenarioValidationError,
    _normalize_move_id,
    _normalize_species,
    load_scenario_file,
)


class ScriptedOpponentPlayer(Player):
    """A poke-env player that follows a
    scenario script.

    The script is loaded from a scenario
    JSON file. On each turn, the player
    looks up the scripted action for that
    turn and slot, and constructs the
    corresponding order.

    If the scripted action is invalid
    (e.g., the mon is fainted, the move
    is not in the moveset, the target
    is invalid), the player falls back
    to a default safe action and records
    the failure in self.scenario_failures.

    The player's behavior is independent
    of the bot's scoring: it does not
    read the bot's actions, the bot's
    config, or the bot's internal state.
    """

    def __init__(
        self,
        scenario_path: str,
        *args: Any,
        **kwargs: Any,
    ):
        """Initialize the scripted opponent.

        Args:
            scenario_path: path to a scenario
                JSON file (see scenario_probe.py
                for the schema)
            *args, **kwargs: passed to the
                base Player
        """
        super().__init__(*args, **kwargs)
        self._accept_open_team_sheet = False
        # Load scenario
        self.scenario = load_scenario_file(scenario_path)
        # Metadata for audit
        self.scenario_id = self.scenario.scenario_id
        self.scenario_failures: List[Dict[str, Any]] = []
        self.scenario_actions: List[Dict[str, Any]] = []

    def teampreview(self, battle: AbstractBattle) -> str:
        """Phase SCENARIO-4: lead with the
        species specified in the scenario's
        ``lead`` field, if present.

        At teampreview time, ``battle.team``
        may have None placeholders or empty
        species. We use the team that was
        loaded at construction time
        (``self._team``) for the species
        lookup. The team has stable
        1-indexed positions matching the
        packed team string format.
        """
        int_to_species: Dict[int, str] = {}
        if self._team is not None:
            try:
                team_list = self._team.team
                for i, mon in enumerate(team_list, start=1):
                    sp = getattr(mon, "species", None) or ""
                    if not sp and hasattr(mon, "name"):
                        sp = getattr(mon, "name", "") or ""
                    if sp:
                        int_to_species[i] = sp
            except Exception:
                pass
        # Fallback to battle.team if
        # self._team is empty or unusable.
        if not int_to_species:
            for k, v in battle.team.items():
                if v is None:
                    continue
                sp = getattr(v, "species", None) or ""
                if not sp:
                    try:
                        sp = v.species
                    except AttributeError:
                        sp = ""
                if sp:
                    try:
                        int_to_species[int(k)] = sp
                    except (ValueError, TypeError):
                        continue
        lead_map = getattr(self.scenario, "lead", None) or {}
        if lead_map:
            return self._build_team_from_lead(
                int_to_species, lead_map, battle
            )
        return self.random_teampreview(battle)

    def _build_team_from_lead(
        self,
        int_to_species: Dict[int, str],
        lead_map: Dict[str, str],
        battle: AbstractBattle,
    ) -> str:
        """Build a /team order that brings
        4 mons and leads with the species
        named in ``lead_map``.

        Phase SCENARIO-5 fix: the
        showdown doubles /team format is
        ``lead, back, lead, back`` (the
        leads are at positions 1 and 3 of
        the 4-digit string). The /team
        ``6253`` means: lead 6, back 2,
        lead 5, back 3 — NOT lead 6, 2.
        """
        if not int_to_species:
            return self.random_teampreview(battle)
        species_to_pos = {
            self._norm(sp): pos
            for pos, sp in int_to_species.items()
        }
        lead_positions: list = []
        for slot_key, species in lead_map.items():
            if slot_key not in (
                "opp_slot_0", "opp_slot_1"
            ):
                continue
            pos = species_to_pos.get(self._norm(species))
            if pos is not None and pos not in lead_positions:
                lead_positions.append(pos)
        if len(lead_positions) < 2:
            for pos in sorted(int_to_species.keys()):
                if pos not in lead_positions:
                    lead_positions.append(pos)
                if len(lead_positions) == 2:
                    break
        if len(lead_positions) < 2:
            return self.random_teampreview(battle)
        members = list(int_to_species.keys())
        back_positions = [
            p for p in members if p not in lead_positions
        ]
        random.shuffle(back_positions)
        # /team format: lead, back, lead, back
        # Need at least 2 back positions for
        # 4-mon bring. If we have fewer,
        # fall back to random_teampreview.
        if len(back_positions) < 2:
            return self.random_teampreview(battle)
        chosen = [
            lead_positions[0],
            back_positions[0],
            lead_positions[1],
            back_positions[1],
        ]
        return "/team " + "".join(str(c) for c in chosen)

    @staticmethod
    def _norm(species: str) -> str:
        return _normalize_species(species)

    def _find_species_with_move(
        self, battle: AbstractBattle, move_name: str,
    ) -> Optional[str]:
        target = _normalize_move_id(move_name)
        for mon in battle.team.values():
            if mon is None:
                continue
            mon_moves = getattr(mon, "moves", None) or {}
            for mv in mon_moves.values():
                mv_id = getattr(mv, "id", "")
                if _normalize_move_id(mv_id) == target:
                    return getattr(mon, "species", None)
        return None

    def choose_move(
        self, battle: AbstractBattle,
    ) -> BattleOrder:
        """Choose a move for the current
        battle. Reads the script for the
        current turn and executes it.

        Falls back to a default safe action
        if the script is invalid for any
        reason.
        """
        if not isinstance(battle, DoubleBattle):
            return super().choose_move(battle)
        turn = battle.turn
        if turn is None or turn not in self.scenario.script:
            return self.choose_random_doubles_move(battle)
        scenario_turn = self.scenario.script[turn]
        first_order, second_order = self._build_orders(
            scenario_turn, battle
        )
        # DoubleBattleOrder expects
        # SingleBattleOrder objects directly
        # (not lists). first_order and
        # second_order are already
        # SingleBattleOrder instances.
        return DoubleBattleOrder(
            first_order=first_order,
            second_order=second_order,
        )

    def _build_orders(
        self,
        scenario_turn: Any,
        battle: DoubleBattle,
    ) -> Tuple[SingleBattleOrder, SingleBattleOrder]:
        """Build first and second orders from
        a scenario turn.
        """
        orders: List[Optional[SingleBattleOrder]] = [None, None]
        for slot_key, action in scenario_turn.actions.items():
            slot_idx = self._slot_key_to_index(slot_key)
            if slot_idx is None:
                continue
            order = self._build_order_for_action(
                battle, slot_idx, action
            )
            orders[slot_idx] = order
        # Fill in any None with a default
        # use choose_default_move (returns a
        # DefaultBattleOrder) instead of
        # choose_random_singles_move (which
        # returns a list for DoubleBattle,
        # not a SingleBattleOrder)
        results = []
        for o in orders:
            if o is None:
                results.append(
                    self.choose_default_move()
                )
            else:
                results.append(o)
        return results[0], results[1]

    def _slot_key_to_index(self, slot_key: str) -> Optional[int]:
        """Convert 'opp_slot_0' / 'opp_slot_1'
        to 0 / 1."""
        if slot_key == "opp_slot_0":
            return 0
        if slot_key == "opp_slot_1":
            return 1
        return None

    def _build_order_for_action(
        self,
        battle: DoubleBattle,
        slot_idx: int,
        action: ScenarioAction,
    ) -> SingleBattleOrder:
        """Build a SingleBattleOrder for one
        action. Records success/failure in
        scenario_actions / scenario_failures.
        """
        turn = battle.turn
        if action.is_noop():
            # Noop: pass
            return PassBattleOrder()
        if action.switch is not None:
            return self._build_switch_order(
                battle, slot_idx, action, turn
            )
        if action.move is not None:
            return self._build_move_order(
                battle, slot_idx, action, turn
            )
        # Should not reach here
        return PassBattleOrder()

    def _build_move_order(
        self,
        battle: DoubleBattle,
        slot_idx: int,
        action: ScenarioAction,
        turn: int,
    ) -> SingleBattleOrder:
        """Build a move order. Looks up the
        move in battle's available moves.
        """
        target_move_norm = _normalize_move_id(action.move)
        # Find the move in the active mon's
        # available moves (or the moves dict).
        active_mon = None
        if slot_idx < len(battle.active_pokemon):
            active_mon = battle.active_pokemon[slot_idx]
        if active_mon is None:
            self._record_failure(
                turn, slot_idx, action, "no_active_mon"
            )
            return PassBattleOrder()
        # Find the move by normalized ID
        move_obj = None
        # First check available_moves (poke-env
        # list of currently-usable moves)
        for mv in active_mon.moves.values():
            if _normalize_move_id(getattr(mv, "id", "")) == (
                target_move_norm
            ):
                move_obj = mv
                break
        if move_obj is None:
            # Fallback: check if the move name
            # matches any move by name (the bot
            # may have stripped the move due to
            # PP or similar).
            for mv in active_mon.moves.values():
                if _normalize_move_id(
                    getattr(mv, "name", "")
                ) == target_move_norm:
                    move_obj = mv
                    break
        if move_obj is None:
            self._record_failure(
                turn, slot_idx, action, "move_not_available"
            )
            return PassBattleOrder()
        # Build the order
        # target_pos: 1 -> opp slot 0,
        # 2 -> opp slot 1, -1 -> self, -2 -> ally
        # In poke-env DoubleBattle,
        # move_target uses:
        #   -2 for ally
        #   -1 for self
        #    1 for opp slot 0
        #    2 for opp slot 1
        # Our action.target_pos is in the same
        # convention.
        # EmptyTargetPosition is used as the
        # default for self-targeting or
        # no-target moves.
        target_pos = action.target_pos
        try:
            order = self.create_order(
                move_obj, move_target=target_pos,
            )
        except Exception as e:
            self._record_failure(
                turn, slot_idx, action,
                f"create_order_failed: {e}",
            )
            return PassBattleOrder()
        # Note: we don't pre-validate the order
        # here. poke-env's DoubleBattle doesn't
        # expose order_is_valid in this version.
        # The server is the final authority. If
        # the order is invalid, the server
        # will reject it and we'll record a
        # failure in scenario_failures via the
        # audit. The scripted player is best
        # seen as "advisory" — the server
        # decides.
        self._record_success(
            turn, slot_idx, action, order
        )
        return order

    def _build_switch_order(
        self,
        battle: DoubleBattle,
        slot_idx: int,
        action: ScenarioAction,
        turn: int,
    ) -> SingleBattleOrder:
        """Build a switch order. Looks up the
        Pokemon by species name in the
        available switches."""
        target_species_norm = _normalize_species(
            action.switch
        )
        # battle.available_switches is a list
        # of lists, indexed by slot
        if slot_idx >= len(battle.available_switches):
            self._record_failure(
                turn, slot_idx, action, "no_switch_available"
            )
            return PassBattleOrder()
        # Find a Pokemon with the matching
        # species in available_switches[slot_idx]
        pokemon = None
        for mon in battle.available_switches[slot_idx]:
            if _normalize_species(
                getattr(mon, "species", "")
            ) == target_species_norm:
                pokemon = mon
                break
        if pokemon is None:
            self._record_failure(
                turn, slot_idx, action,
                "switch_species_not_found",
            )
            return PassBattleOrder()
        order = SingleBattleOrder(pokemon)
        # Note: we don't pre-validate here; the
        # server is the final authority.
        self._record_success(
            turn, slot_idx, action, order
        )
        return order

    def _record_success(
        self,
        turn: int,
        slot_idx: int,
        action: ScenarioAction,
        order: Any,
    ) -> None:
        """Record a successful script
        execution in self.scenario_actions.
        """
        self.scenario_actions.append({
            "turn": turn,
            "slot_idx": slot_idx,
            "move": action.move,
            "switch": action.switch,
            "target_pos": action.target_pos,
            "executed": True,
            "order_message": str(order.message)
            if hasattr(order, "message") else str(order),
        })

    def _record_failure(
        self,
        turn: int,
        slot_idx: int,
        action: ScenarioAction,
        reason: str,
    ) -> None:
        """Record a script failure in
        self.scenario_failures.
        """
        self.scenario_failures.append({
            "turn": turn,
            "slot_idx": slot_idx,
            "move": action.move,
            "switch": action.switch,
            "target_pos": action.target_pos,
            "executed": False,
            "reason": reason,
        })


# ----------------------------------------------------------------------------
# Self-check
# ----------------------------------------------------------------------------

def main() -> int:
    """Self-check: print usage."""
    print("bot_vgc2026_scripted_opp.py — scripted opponent")
    print("Inherits from poke_env.Player.")
    print("Anti-leak: no access to bot's scoring/config.")
    print("Import ScriptedOpponentPlayer to use.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
