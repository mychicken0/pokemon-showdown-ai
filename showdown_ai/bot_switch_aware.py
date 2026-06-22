import asyncio
import random
from dataclasses import dataclass
from poke_env import AccountConfiguration
from bot_damage_aware import DamageAwarePlayer

@dataclass
class SwitchAwareConfig:
    low_hp_trigger: float = 0.25
    critical_hp_trigger: float = 0.10
    bad_status_hp_trigger: float = 0.40
    low_best_move_score: float = 50.0
    threatened_best_move_limit: float = 120.0
    high_score_attack_override: float = 220.0
    low_opponent_hp_attack_threshold: float = 0.25
    low_opponent_hp_attack_score: float = 150.0
    switch_margin: float = 20.0
    switch_penalty: float = 0.0
    min_candidate_hp: float = 0.15

class SwitchAwarePlayer(DamageAwarePlayer):
    """
    An improved bot subclass that extends DamageAwarePlayer by incorporating
    a conservative switch candidate scoring system and trigger evaluation.
    """
    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else SwitchAwareConfig()

    # 4. Safe helper functions
    def safe_hp_fraction(self, pokemon):
        if not pokemon:
            return 1.0
        try:
            return getattr(pokemon, "current_hp_fraction", 1.0)
        except Exception:
            return 1.0

    def safe_types(self, pokemon):
        if not pokemon:
            return []
        try:
            return getattr(pokemon, "types", [])
        except Exception:
            return []

    def safe_received_multiplier(self, pokemon, attacking_type):
        if not pokemon or not attacking_type:
            return 1.0
        try:
            return pokemon.damage_multiplier(attacking_type)
        except Exception:
            return 1.0

    def safe_status(self, pokemon):
        return self.get_status(pokemon)

    def safe_species(self, pokemon):
        if not pokemon:
            return "Unknown"
        try:
            return getattr(pokemon, "species", "Unknown")
        except Exception:
            return "Unknown"

    def should_attack_despite_low_hp(self, best_move_score, active_hp_fraction, opponent_hp_fraction, has_priority_ko):
        """
        Determines whether the bot should stay and attack despite meeting low HP/switching triggers.
        """
        # - If has_priority_ko: attack.
        if has_priority_ko:
            return True
        # - If opponent_hp_fraction < low_opponent_hp_attack_threshold and best_move_score >= low_opponent_hp_attack_score: attack.
        if opponent_hp_fraction < self.config.low_opponent_hp_attack_threshold and best_move_score >= self.config.low_opponent_hp_attack_score:
            return True
        # - If best_move_score >= high_score_attack_override and active_hp_fraction > critical_hp_trigger: attack.
        if best_move_score >= self.config.high_score_attack_override and active_hp_fraction > self.config.critical_hp_trigger:
            return True
        # - If active_hp_fraction <= critical_hp_trigger and no priority KO: allow switch consideration.
        if active_hp_fraction <= self.config.critical_hp_trigger and not has_priority_ko:
            return False
        return False

    def score_matchup(self, pokemon, opponent):
        """
        5. Switch candidate scoring:
        - Base score from HP fraction * 100.
        - Defensive matchup adjustments (immunities, resistances, weaknesses).
        - HP penalties for critically low health.
        - Offensive matchup adjustments for super effective type advantages.
        """
        if not pokemon:
            return 0.0
            
        score = 0.0
        
        # Base HP fraction score (0 to 100)
        hp_frac = self.safe_hp_fraction(pokemon)
        score += hp_frac * 100.0
        
        # Defensive matchup:
        if opponent:
            opp_types = self.safe_types(opponent)
            for opp_type in opp_types:
                if opp_type:
                    mult = self.safe_received_multiplier(pokemon, opp_type)
                    if mult == 0.0:
                        score += 50.0  # +50 for immunity
                    elif 0.0 < mult < 1.0:
                        score += 30.0  # +30 for resistance
                    elif 1.0 < mult < 4.0:
                        score -= 30.0  # -30 for weakness
                    elif mult >= 4.0:
                        score -= 60.0  # -60 for 4x weakness
                        
        # HP penalty:
        if hp_frac < 0.20:
            score -= 60.0
        elif hp_frac < 0.35:
            score -= 25.0
            
        # Offensive matchup:
        # Check if our types can deal super effective damage to opponent
        # TODO: later use candidate known moves instead of candidate types.
        if opponent:
            my_types = self.safe_types(pokemon)
            favorable = False
            for my_type in my_types:
                if my_type:
                    try:
                        if opponent.damage_multiplier(my_type) > 1.0:
                            favorable = True
                            break
                    except Exception:
                        pass
            if favorable:
                score += 20.0
                        
        return score

    def choose_move(self, battle):
        available_moves = battle.available_moves
        opponent = battle.opponent_active_pokemon
        active = battle.active_pokemon
        
        active_name = self.safe_species(active)
        active_hp = getattr(active, "current_hp", 0) if active else 0
        active_max_hp = getattr(active, "max_hp", 100) if active else 100
        active_types = self.safe_types(active)
        active_status = self.safe_status(active)
        
        opp_name = self.safe_species(opponent)
        opp_hp = getattr(opponent, "current_hp", 0) if opponent else 0
        opp_max_hp = getattr(opponent, "max_hp", 100) if opponent else 100
        opp_types = self.safe_types(opponent)
        opp_status = self.safe_status(opponent)
        
        if self.verbose:
            print(f"\n--- [SwitchAware] Battle: {getattr(battle, 'battle_tag', 'Unknown')} | Turn {getattr(battle, 'turn', 0)} ---")
            print(f"Our Active Pokémon: {active_name} ({active_hp}/{active_max_hp} HP)")
            print(f"Opponent Active Pokémon: {opp_name} ({opp_hp}/{opp_max_hp} HP)")

        # Reuse DamageAwarePlayer scoring logic to get moves and scores
        best_move, best_move_score, scored_moves = self.get_best_move_and_score(battle)

        # 1. Conservative switch triggers
        triggers = []
        active_hp_fraction = self.safe_hp_fraction(active)
        opp_hp_fraction = self.safe_hp_fraction(opponent)
        
        # Trigger A: active HP < low_hp_trigger
        if active_hp_fraction < self.config.low_hp_trigger:
            triggers.append(f"active HP < {self.config.low_hp_trigger}")
            
        # Trigger B: best_move_score < low_best_move_score
        if best_move_score < self.config.low_best_move_score:
            triggers.append(f"best_move_score < {self.config.low_best_move_score}")
            
        # Trigger C: active is threatened by opponent type AND best_move_score < threatened_best_move_limit
        is_threatened = False
        if opponent:
            for opp_type in opp_types:
                if opp_type and self.safe_received_multiplier(active, opp_type) >= 2.0:
                    is_threatened = True
                    break
        if is_threatened and best_move_score < self.config.threatened_best_move_limit:
            triggers.append(f"threatened by opponent type AND best_move_score < {self.config.threatened_best_move_limit}")
            
        # Trigger D: active is badly statused AND HP < bad_status_hp_trigger
        is_badly_statused = False
        if active_status:
            status_name = getattr(active_status, "name", str(active_status)).upper()
            if status_name in {"SLP", "FRZ", "TOX", "PSN", "BRN", "PAR"}:
                is_badly_statused = True
        if is_badly_statused and active_hp_fraction < self.config.bad_status_hp_trigger:
            triggers.append(f"badly statused AND HP < {self.config.bad_status_hp_trigger}")

        # Calculate stay_score for the active Pokémon
        stay_score = self.score_matchup(active, opponent)
        
        # Score switch candidates
        best_switch = None
        best_switch_score = -9999.0
        switch_scores = {}
        
        if battle.available_switches:
            for candidate in battle.available_switches:
                # Filter candidates by minimum HP
                if self.safe_hp_fraction(candidate) < self.config.min_candidate_hp:
                    continue
                cand_score = self.score_matchup(candidate, opponent)
                switch_scores[candidate] = cand_score
                
            if switch_scores:
                best_cand = max(switch_scores, key=switch_scores.get)
                # Subtract switch_penalty
                best_switch_score = switch_scores[best_cand] - self.config.switch_penalty
                best_switch = best_cand

        # Evaluate switch decisions
        should_switch = False
        switch_reason = ""
        
        if triggers and battle.available_switches:
            # 2. Stay-in Overrides
            has_priority_ko = False
            if available_moves:
                for m in available_moves:
                    if self.check_move_will_ko(m, active, opponent) and self.get_priority(m) > 0:
                        has_priority_ko = True
                        break
            
            opp_hp_fraction = self.safe_hp_fraction(opponent)
            
            # Do not switch if should_attack_despite_low_hp returns True.
            if self.should_attack_despite_low_hp(best_move_score, active_hp_fraction, opp_hp_fraction, has_priority_ko):
                should_switch = False
                switch_reason = f"Stay (attack despite low HP | score={best_move_score:.2f}, active_hp={active_hp_fraction:.2f}, opp_hp={opp_hp_fraction:.2f}, prio_ko={has_priority_ko})"
            else:
                # Switch only if best switch score beats stay score by switch_margin
                if best_switch is not None and best_switch_score > (stay_score + self.config.switch_margin):
                    should_switch = True
                    switch_reason = f"Switch! Best Switch: {best_switch.species} ({best_switch_score:.2f}) > Stay Score: {stay_score:.2f} + {self.config.switch_margin}"
                else:
                    switch_reason = f"Stay (Best switch candidate {best_switch.species if best_switch else 'None'} ({best_switch_score:.2f}) is not {self.config.switch_margin}pts better than Stay Score: {stay_score:.2f})"
        else:
            if not triggers:
                switch_reason = "No switch triggers active"
            else:
                switch_reason = "No legal switches available"

        # 7. Verbose Logging of Switch decisions
        if self.verbose:
            print("Switch Evaluation:")
            print(f"  - Active Triggers: {triggers}")
            print(f"  - Stay Score: {stay_score:.2f} (Best move: {best_move.id if best_move else 'None'} | score: {best_move_score:.2f})")
            if battle.available_switches:
                print("  - Switch Candidates:")
                for cand, score in switch_scores.items():
                    print(f"    * {cand.species} | HP: {self.safe_hp_fraction(cand):.2f} | Score: {score:.2f}")
            print(f"  - Decision: {'SWITCH' if should_switch else 'ATTACK'} | Reason: {switch_reason}")

        # Execute Switch Decision
        if should_switch and best_switch:
            # Increment strategic switches counter
            battle_tag = getattr(battle, "battle_tag", "Unknown")
            if not hasattr(self, "strategic_switches"):
                self.strategic_switches = {}
            self.strategic_switches[battle_tag] = self.strategic_switches.get(battle_tag, 0) + 1
            
            # 8. Logger compatibility (log switch choice details)
            if self.custom_logger:
                available_scores = {m.id: score for m, score in scored_moves.items()}
                self.custom_logger.log_turn(
                    battle_tag=getattr(battle, "battle_tag", "Unknown"),
                    turn=getattr(battle, "turn", 0),
                    active_pkmn=active_name,
                    active_hp=active_hp,
                    active_max_hp=active_max_hp,
                    active_types=active_types,
                    active_status=active_status,
                    opp_pkmn=opp_name,
                    opp_hp=opp_hp,
                    opp_max_hp=opp_max_hp,
                    opp_types=opp_types,
                    opp_status=opp_status,
                    available_moves=available_scores,
                    selected_action=f"switch {best_switch.species}",
                    selected_score=best_switch_score,
                    selected_action_type="switch",
                    switch_score=best_switch_score,
                    stay_score=stay_score,
                    switch_trigger_reasons=triggers,
                    active_hp_fraction=active_hp_fraction,
                    opponent_hp_fraction=opp_hp_fraction,
                    available_move_count=len(available_moves) if available_moves else 0,
                    is_forced_switch=False,
                    best_move_score=best_move_score,
                    best_move_id=best_move.id if best_move else None
                )
            return self.create_order(best_switch)

        # Execute Attack Decision (or Fallbacks)
        if available_moves:
            if self.verbose:
                print(f"Selected action: {best_move.id} (Score: {best_move_score:.2f})")
            if self.custom_logger:
                available_scores = {m.id: score for m, score in scored_moves.items()}
                self.custom_logger.log_turn(
                    battle_tag=getattr(battle, "battle_tag", "Unknown"),
                    turn=getattr(battle, "turn", 0),
                    active_pkmn=active_name,
                    active_hp=active_hp,
                    active_max_hp=active_max_hp,
                    active_types=active_types,
                    active_status=active_status,
                    opp_pkmn=opp_name,
                    opp_hp=opp_hp,
                    opp_max_hp=opp_max_hp,
                    opp_types=opp_types,
                    opp_status=opp_status,
                    available_moves=available_scores,
                    selected_action=best_move.id,
                    selected_score=best_move_score,
                    selected_action_type="move",
                    stay_score=stay_score,
                    switch_trigger_reasons=triggers,
                    active_hp_fraction=active_hp_fraction,
                    opponent_hp_fraction=opp_hp_fraction,
                    available_move_count=len(available_moves) if available_moves else 0,
                    is_forced_switch=False,
                    best_move_score=best_move_score,
                    best_move_id=best_move.id if best_move else None
                )
            return self.create_order(best_move)

        if battle.available_switches:
            selected_switch = random.choice(battle.available_switches)
            if self.verbose:
                print(f"No available moves. Selected switch: {selected_switch.species}")
            if self.custom_logger:
                self.custom_logger.log_turn(
                    battle_tag=getattr(battle, "battle_tag", "Unknown"),
                    turn=getattr(battle, "turn", 0),
                    active_pkmn=active_name,
                    active_hp=active_hp,
                    active_max_hp=active_max_hp,
                    active_types=active_types,
                    active_status=active_status,
                    opp_pkmn=opp_name,
                    opp_hp=opp_hp,
                    opp_max_hp=opp_max_hp,
                    opp_types=opp_types,
                    opp_status=opp_status,
                    available_moves={},
                    selected_action=f"switch {selected_switch.species}",
                    selected_score=0.0,
                    selected_action_type="switch",
                    switch_score=0.0,
                    stay_score=stay_score,
                    switch_trigger_reasons=["no_available_moves"],
                    active_hp_fraction=active_hp_fraction,
                    opponent_hp_fraction=opp_hp_fraction,
                    available_move_count=0,
                    is_forced_switch=True,
                    best_move_score=None,
                    best_move_id=None
                )
            return self.create_order(selected_switch)

        if self.verbose:
            print("Fallback: selecting random move/switch.")
        action = self.choose_random_move(battle)
        if self.custom_logger:
            self.custom_logger.log_turn(
                battle_tag=getattr(battle, "battle_tag", "Unknown"),
                turn=getattr(battle, "turn", 0),
                active_pkmn=active_name,
                active_hp=active_hp,
                active_max_hp=active_max_hp,
                active_types=active_types,
                active_status=active_status,
                opp_pkmn=opp_name,
                opp_hp=opp_hp,
                opp_max_hp=opp_max_hp,
                opp_types=opp_types,
                opp_status=opp_status,
                available_moves={},
                selected_action=f"fallback {action}",
                selected_score=0.0,
                selected_action_type="switch" if "switch" in str(action) else "move",
                stay_score=stay_score,
                switch_trigger_reasons=["fallback"],
                active_hp_fraction=active_hp_fraction,
                opponent_hp_fraction=opp_hp_fraction,
                available_move_count=len(available_moves) if available_moves else 0,
                is_forced_switch=(not available_moves and active_hp_fraction <= 0.0 and "switch" in str(action)),
                best_move_score=best_move_score if available_moves else None,
                best_move_id=best_move.id if (available_moves and best_move) else None
            )
        return action

async def main():
    bot = SwitchAwarePlayer(
        account_configuration=AccountConfiguration("SwitchAwareBot_1", None)
    )

    print("Switch-aware bot is starting and waiting for challenges...")
    await bot.accept_challenges(None, n_challenges=1)
    print("Battle finished!")

if __name__ == "__main__":
    asyncio.run(main())
