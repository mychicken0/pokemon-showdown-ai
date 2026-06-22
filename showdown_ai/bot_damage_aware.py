import asyncio
import random
from poke_env.player import Player
from poke_env import AccountConfiguration
from poke_env.battle.side_condition import SideCondition

class DamageAwarePlayer(Player):
    def __init__(self, *args, verbose=True, logger=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose
        # Use custom_logger internally to avoid conflict with poke-env's built-in read-only logger property
        self.custom_logger = logger

    def get_priority(self, move):
        try:
            return getattr(move, "priority", 0)
        except Exception:
            return 0

    def get_recoil(self, move):
        try:
            return getattr(move, "recoil", 0.0)
        except Exception:
            return 0.0

    def get_accuracy(self, move):
        """
        Accuracy conversion helper:
        - None / True / special accuracy should be treated as 1.0.
        - 1.0 means 100%.
        - 100 means 100%.
        - 80 means 0.8.
        - 0.8 means 80%.
        """
        try:
            acc = getattr(move, "accuracy", 1.0)
            if acc is True or acc is None:
                return 1.0
            if isinstance(acc, (int, float)):
                if acc == 100:
                    return 1.0
                if acc > 1.0:
                    return acc / 100.0
                return acc
            return 1.0
        except Exception:
            return 1.0

    def get_stats(self, pokemon):
        try:
            return getattr(pokemon, "stats", {})
        except Exception:
            return {}

    def get_base_stats(self, pokemon):
        try:
            return getattr(pokemon, "base_stats", {})
        except Exception:
            return {}

    def get_boosts(self, pokemon):
        try:
            return getattr(pokemon, "boosts", {})
        except Exception:
            return {}

    def get_status(self, pokemon):
        try:
            return getattr(pokemon, "status", None)
        except Exception:
            return None

    def get_opponent_side_conditions(self, battle):
        try:
            return getattr(battle, "opponent_side_conditions", set())
        except Exception:
            return set()

    def get_boosted_stat(self, pokemon, stat_name):
        if not pokemon:
            return 100.0
        stats = self.get_stats(pokemon) or {}
        base_stats = self.get_base_stats(pokemon) or {}
        base_val = stats.get(stat_name) or base_stats.get(stat_name) or 100.0
        
        boosts = self.get_boosts(pokemon) or {}
        stage = boosts.get(stat_name, 0)
        
        if stage > 0:
            multiplier = (2.0 + stage) / 2.0
        elif stage < 0:
            multiplier = 2.0 / (2.0 - stage)
        else:
            multiplier = 1.0
        return float(base_val) * multiplier

    def get_type_effectiveness(self, move, opponent):
        """
        Safely calculate type effectiveness multiplier.
        """
        if not opponent:
            return 1.0
        try:
            return opponent.damage_multiplier(move)
        except Exception:
            try:
                move_type = getattr(move, "type", None)
                if move_type:
                    return opponent.damage_multiplier(move_type)
            except Exception:
                pass
        return 1.0

    def estimate_opponent_max_hp(self, opponent):
        """
        Estimate the opponent's max HP dynamically based on level.
        """
        if not opponent:
            return 300.0
        try:
            level = getattr(opponent, "level", 80) or 80
            return float(level) * 3.0  # e.g., level 80 -> 240 HP
        except Exception:
            return 240.0

    def check_move_will_ko(self, move, active, opponent):
        """
        Helper to check if a damaging move will secure a KO.
        """
        base_power = getattr(move, "base_power", 0)
        if base_power == 0 or not opponent:
            return False
            
        try:
            opp_hp_fraction = getattr(opponent, "current_hp_fraction", 1.0)
            if opp_hp_fraction is None:
                return False
                
            category = getattr(move, "category", None)
            category_name = getattr(category, "name", "PHYSICAL")
            
            if category_name == "SPECIAL":
                attacking_stat = self.get_boosted_stat(active, "spa")
                defending_stat = self.get_boosted_stat(opponent, "spd")
            else:
                attacking_stat = self.get_boosted_stat(active, "atk")
                defending_stat = self.get_boosted_stat(opponent, "def")
                
            level = getattr(active, "level", 100) if active else 100
            base_damage = (((2.0 * level / 5.0 + 2.0) * base_power * attacking_stat / max(defending_stat, 1.0)) / 50.0) + 2.0
            
            # STAB
            active_types = getattr(active, "types", []) if active else []
            move_type = getattr(move, "type", None)
            stab = 1.5 if (move_type and move_type in active_types) else 1.0
            
            # Effectiveness
            eff = self.get_type_effectiveness(move, opponent)
            
            estimated_damage = base_damage * stab * eff
            accuracy = self.get_accuracy(move)
            expected_damage = estimated_damage * accuracy
            
            opp_max_hp = self.estimate_opponent_max_hp(opponent)
            return expected_damage >= (opp_hp_fraction * opp_max_hp)
        except Exception:
            return False

    def score_single_move(self, move, active, opponent, battle, has_ko_move):
        """
        Calculates move score based on category and properties.
        """
        base_power = getattr(move, "base_power", 0)
        category = getattr(move, "category", None)
        category_name = getattr(category, "name", "STATUS")
        
        # 1. Status / Setup / Recovery Moves (base_power == 0 or category is STATUS)
        if category_name == "STATUS" or base_power == 0:
            if has_ko_move:
                return 5.0
                
            active_hp_fraction = getattr(active, "current_hp_fraction", 1.0) if active else 1.0
            
            # A. Recovery (recover, roost, slackoff, synthesis)
            if move.id in {"recover", "roost", "slackoff", "synthesis"}:
                if active_hp_fraction < 0.40:
                    return 350.0
                return 5.0
                
            # B. Setup (swordsdance, nastyplot, calmmind, dragondance, quiverdance)
            if move.id in {"swordsdance", "nastyplot", "calmmind", "dragondance", "quiverdance"}:
                opponent_is_threatening = False
                if opponent and active:
                    opp_boosts = self.get_boosts(opponent) or {}
                    if opp_boosts.get("atk", 0) >= 2 or opp_boosts.get("spa", 0) >= 2:
                        opponent_is_threatening = True
                    else:
                        try:
                            opp_types = getattr(opponent, "types", [])
                            for opp_type in opp_types:
                                if opp_type and active.damage_multiplier(opp_type) > 1.0:
                                    opponent_is_threatening = True
                                    break
                        except Exception:
                            pass
                            
                our_speed = self.get_boosted_stat(active, "spe")
                opp_speed = self.get_boosted_stat(opponent, "spe") if opponent else 100.0
                is_faster = our_speed >= opp_speed
                            
                our_boosts = self.get_boosts(active) or {}
                boosts_not_high = True
                if move.id == "swordsdance" and our_boosts.get("atk", 0) >= 3:
                    boosts_not_high = False
                elif move.id == "nastyplot" and our_boosts.get("spa", 0) >= 3:
                    boosts_not_high = False
                elif move.id == "calmmind" and (our_boosts.get("spa", 0) >= 3 or our_boosts.get("spd", 0) >= 3):
                    boosts_not_high = False
                elif move.id == "dragondance" and (our_boosts.get("atk", 0) >= 3 or our_boosts.get("spe", 0) >= 3):
                    boosts_not_high = False
                elif move.id == "quiverdance" and (our_boosts.get("spa", 0) >= 3 or our_boosts.get("spd", 0) >= 3 or our_boosts.get("spe", 0) >= 3):
                    boosts_not_high = False
                    
                if active_hp_fraction > 0.65 and not opponent_is_threatening and boosts_not_high and is_faster:
                    return 250.0
                return 5.0
                
            # C. Status (thunderwave, willowisp, toxic)
            if move.id in {"thunderwave", "willowisp", "toxic"}:
                if active_hp_fraction < 0.50:
                    return 5.0
                    
                opp_status = self.get_status(opponent) if opponent else None
                if opp_status is None and opponent:
                    opponent_types = []
                    try:
                        opponent_types = [t.name for t in getattr(opponent, "types", []) if t]
                    except Exception:
                        pass
                        
                    useful = True
                    if move.id == "thunderwave" and ("GROUND" in opponent_types or "ELECTRIC" in opponent_types):
                        useful = False
                    elif move.id == "willowisp" and "FIRE" in opponent_types:
                        useful = False
                    elif move.id == "toxic" and ("POISON" in opponent_types or "STEEL" in opponent_types):
                        useful = False
                        
                    if useful:
                        return 180.0
                return 5.0
                
            # D. Stealth Rock
            if move.id == "stealthrock":
                if active_hp_fraction < 0.50:
                    return 5.0
                    
                side_conditions = self.get_opponent_side_conditions(battle)
                has_stealthrock = False
                for cond in side_conditions:
                    if getattr(cond, "name", "") == "STEALTH_ROCK" or str(cond) == "stealthrock":
                        has_stealthrock = True
                        break
                if not has_stealthrock and battle.turn < 5:
                    return 220.0
                return 5.0
                
            return 5.0

        # 2. Damaging Moves (base_power > 0)
        if category_name == "SPECIAL":
            attacking_stat = self.get_boosted_stat(active, "spa")
            defending_stat = self.get_boosted_stat(opponent, "spd") if opponent else 100.0
        else:
            attacking_stat = self.get_boosted_stat(active, "atk")
            defending_stat = self.get_boosted_stat(opponent, "def") if opponent else 100.0

        active_types = getattr(active, "types", []) if active else []
        move_type = getattr(move, "type", None)
        stab_multiplier = 1.5 if (move_type and move_type in active_types) else 1.0

        type_multiplier = self.get_type_effectiveness(move, opponent)
        accuracy_multiplier = self.get_accuracy(move)

        # Raw damage score
        raw_score = float(base_power)
        raw_score *= (attacking_stat / max(defending_stat, 1.0))
        raw_score *= stab_multiplier
        raw_score *= type_multiplier
        raw_score *= accuracy_multiplier

        # Add priority bonus
        priority = self.get_priority(move)
        if priority > 0:
            raw_score += 15.0

        # Add KO bonus
        if opponent:
            opp_hp_fraction = getattr(opponent, "current_hp_fraction", 1.0)
            if opp_hp_fraction is not None:
                level = getattr(active, "level", 100) if active else 100
                base_damage = (((2.0 * level / 5.0 + 2.0) * base_power * attacking_stat / max(defending_stat, 1.0)) / 50.0) + 2.0
                estimated_damage = base_damage * stab_multiplier * type_multiplier
                expected_damage = estimated_damage * accuracy_multiplier
                
                opp_max_hp = self.estimate_opponent_max_hp(opponent)
                if expected_damage >= (opp_hp_fraction * opp_max_hp):
                    if priority > 0:
                        raw_score += 500.0
                    else:
                        raw_score += 50.0

        # Recoil penalty
        recoil = self.get_recoil(move)
        if recoil > 0:
            raw_score -= 15.0 * recoil

        # Self-destruct moves penalty
        self_destruct = getattr(move, "self_destruct", None)
        if self_destruct or move.id in {"selfdestruct", "explosion"}:
            raw_score -= 50.0

        # If multiplier is 0.0 (immunity), score becomes zero
        if type_multiplier == 0.0:
            raw_score = 0.0

        return max(raw_score, 0.0)

    # 3. Expose score_move helper
    def score_move(self, move, battle):
        opponent = battle.opponent_active_pokemon
        active = battle.active_pokemon
        
        has_ko_move = False
        available_moves = battle.available_moves
        if available_moves:
            for m in available_moves:
                if self.check_move_will_ko(m, active, opponent):
                    has_ko_move = True
                    break
        return self.score_single_move(move, active, opponent, battle, has_ko_move)

    # 3. Expose get_best_move_and_score helper
    def get_best_move_and_score(self, battle):
        available_moves = battle.available_moves
        if not available_moves:
            return None, 0.0, {}
            
        opponent = battle.opponent_active_pokemon
        active = battle.active_pokemon
        
        has_ko_move = False
        for m in available_moves:
            if self.check_move_will_ko(m, active, opponent):
                has_ko_move = True
                break
                
        scored_moves = {}
        for move in available_moves:
            scored_moves[move] = self.score_single_move(move, active, opponent, battle, has_ko_move)
            
        best_move = max(scored_moves, key=scored_moves.get)
        return best_move, scored_moves[best_move], scored_moves

    def choose_move(self, battle):
        available_moves = battle.available_moves
        opponent = battle.opponent_active_pokemon
        active = battle.active_pokemon
        
        # Safe properties extraction for print statements and logging
        active_name = getattr(active, "species", "Unknown") if active else "Unknown"
        active_hp = getattr(active, "current_hp", 0) if active else 0
        active_max_hp = getattr(active, "max_hp", 100) if active else 100
        active_types = getattr(active, "types", []) if active else []
        active_status = getattr(active, "status", None) if active else None
        
        opp_name = getattr(opponent, "species", "Unknown") if opponent else "Unknown"
        opp_hp = getattr(opponent, "current_hp", 0) if opponent else 0
        opp_max_hp = getattr(opponent, "max_hp", 100) if opponent else 100
        opp_types = getattr(opponent, "types", []) if opponent else []
        opp_status = getattr(opponent, "status", None) if opponent else None
        
        if self.verbose:
            print(f"\n--- Battle: {getattr(battle, 'battle_tag', 'Unknown')} | Turn {getattr(battle, 'turn', 0)} ---")
            print(f"Our Active Pokémon: {active_name} ({active_hp}/{active_max_hp} HP)")
            print(f"Opponent Active Pokémon: {opp_name} ({opp_hp}/{opp_max_hp} HP)")
                
        if available_moves:
            # Reuses get_best_move_and_score
            best_move, best_score, scored_moves = self.get_best_move_and_score(battle)
            
            if self.verbose:
                print("Evaluating and scoring all legal moves:")
                has_ko_move = any(self.check_move_will_ko(m, active, opponent) for m in available_moves)
                if has_ko_move:
                    print("  [KO Move Detected! Disabling non-damaging setup/status/recovery.]")
                for move, score in scored_moves.items():
                    print(
                        f"  - Move: {move.id} "
                        f"| Base Power: {getattr(move, 'base_power', 0)} "
                        f"| Type: {getattr(move, 'type', None)} "
                        f"| Category: {getattr(move, 'category', None)} "
                        f"| Accuracy: {getattr(move, 'accuracy', 1.0)} "
                        f"| Score: {score:.2f}"
                    )
            
            # HP-based Switching Logic
            active_hp_fraction = getattr(active, "current_hp_fraction", 1.0) if active else 1.0
            if active_hp_fraction < 0.25 and best_score < 50.0 and battle.available_switches:
                selected_switch = random.choice(battle.available_switches)
                if self.verbose:
                    print(f"Switching triggered (HP={active_hp_fraction:.2f}, best score={best_score:.2f}). Selected switch: {selected_switch.species}")
                
                # Log the switch decision
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
                        selected_action=f"switch {selected_switch.species}",
                        selected_score=0.0
                    )
                return self.create_order(selected_switch)
                
            if self.verbose:
                print(f"Selected action: {best_move.id} (Score: {best_score:.2f})")
                
            # Log the move decision
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
                    selected_score=best_score
                )
            return self.create_order(best_move)

        if battle.available_switches:
            selected_switch = random.choice(battle.available_switches)
            if self.verbose:
                print(f"No available moves. Selected switch: {selected_switch.species}")
            
            # Log empty-move switch decision
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
                    selected_score=0.0
                )
            return self.create_order(selected_switch)
            
        if self.verbose:
            print("Fallback: selecting random move/switch.")
            
        # Fallback random choice
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
                selected_score=0.0
            )
        return action

async def main():
    bot = DamageAwarePlayer(
        account_configuration=AccountConfiguration("DamageAwareBot_1", None)
    )

    print("Damage-aware bot is starting and waiting for challenges...")
    await bot.accept_challenges(None, n_challenges=1)
    print("Battle finished!")

if __name__ == "__main__":
    asyncio.run(main())
