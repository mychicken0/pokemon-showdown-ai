"""Phase 6.3.7k.1 — Verification Defect Repair."""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import sys, os, json, tempfile, shutil, io
sys.path.insert(0, os.path.dirname(__file__))
import poke_env_test_cleanup  # noqa

from poke_env.battle.move import Move

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig, get_effective_move_type, resolve_effective_move_type,
    get_known_ability, ability_hard_blocks_move, is_type_immune,
    record_observed_form_change, get_observed_form, clear_observed_form_state,
    _scan_replay_for_form_changes, classify_dynamic_type_absorb_candidates,
)

STRENGTH_NORMAL = 1000


def _make_move(mid, mtype, bp=80):
    m = MagicMock(spec=Move)
    type(m).id = PropertyMock(return_value=mid)
    type(m).base_power = PropertyMock(return_value=bp)
    type_mock = MagicMock()
    type_mock.name = mtype
    type(m).type = PropertyMock(return_value=type_mock)
    cat_mock = MagicMock()
    cat_mock.name = "PHYSICAL"
    type(m).category = PropertyMock(return_value=cat_mock)
    m.flags = {}
    m.priority = 0
    m.accuracy = 100
    m.deduced_target = None
    m.target = "normal"
    m.recoil = 0
    return m


class MockPokemon:
    def __init__(self, species, ability=None, types=None, base_species=None):
        self.species = species; self._ability = ability
        self._types = types or []; self.current_hp_fraction = 1.0
        self.base_species = base_species or species; self.boosts = {}; self.level = 100
    @property
    def ability(self): return self._ability
    @property
    def types(self): return self._types
    @property
    def type_1(self): return self._types[0] if self._types else None
    @property
    def type_2(self): return self._types[1] if len(self._types) > 1 else None

def _make_order(move_or_pokemon, target=1):
    class O: pass
    o = O(); o.order = move_or_pokemon; o.move_target = target; return o

def _absorb_config():
    c = DoublesDamageAwareConfig()
    c.ability_hard_safety_avoid_absorb = True
    return c

# ====== Object Identity Tests ======
class TestObjectIdentity(unittest.TestCase):
    def tearDown(self):
        for bt in ("oi","oi2","rc","bv"):
            clear_observed_form_state(bt)
    def test_p1a_hangry_p2a_fullbelly_isolated(self):
        clear_observed_form_state("oi"); p1=MockPokemon("morpeko",base_species="morpeko"); p2=MockPokemon("morpeko",base_species="morpeko"); b=MagicMock(battle_tag="oi")
        record_observed_form_change("oi","p1a: Morpeko","morpekohangry",pokemon=p1); record_observed_form_change("oi","p2a: Morpeko","morpeko",pokemon=p2)
        self.assertEqual(get_observed_form(b,p1),"morpekohangry"); self.assertEqual(get_observed_form(b,p2),"morpeko")
    def test_reverse_fullbelly_hangry_fullbelly(self):
        clear_observed_form_state("rc"); p=MockPokemon("morpeko",base_species="morpeko"); b=MagicMock(battle_tag="rc")
        record_observed_form_change("rc","p1a: Morpeko","morpekohangry",pokemon=p); self.assertEqual(get_observed_form(b,p),"morpekohangry")
        record_observed_form_change("rc","p1a: Morpeko","morpeko",pokemon=p); self.assertEqual(get_observed_form(b,p),"morpeko")
    def test_separate_objects_never_collide(self):
        clear_observed_form_state("oi2"); p1=MockPokemon("morpeko",base_species="morpeko"); p2=MockPokemon("morpeko",base_species="morpeko"); b=MagicMock(battle_tag="oi2")
        record_observed_form_change("oi2","p1a: Morpeko","morpekohangry",pokemon=p1); self.assertIsNone(get_observed_form(b,p2))
    def test_different_battles_isolated(self):
        clear_observed_form_state("bv"); clear_observed_form_state("bv2")
        p1=MockPokemon("morpeko",base_species="morpeko"); b1=MagicMock(battle_tag="bv"); b2=MagicMock(battle_tag="bv2")
        record_observed_form_change("bv","p1a: Morpeko","morpekohangry",pokemon=p1); self.assertIsNone(get_observed_form(b2,p1))


# ====== Replay Scan Tests ======
class TestReplayScan(unittest.TestCase):
    def _b(self):
        from poke_env.battle.double_battle import DoubleBattle
        from poke_env.battle.pokemon import Pokemon
        from poke_env.battle.pokemon_type import PokemonType
        b = DoubleBattle.__new__(DoubleBattle)
        for a in ('_battle_tag','_format','_replay_data','_fields','_weather','_side_conditions','_opponent_side_conditions','_player_role','_opponent_role','_username','_opponent_username','_trick_room','_available_moves','_available_switches','_force_switch','_active_pokemon','_opponent_active_pokemon'):
            setattr(b, a, None)
        b._battle_tag='rs'; b._format='gen9randomdoublesbattle'; b._replay_data=[]; b._fields={}; b._weather={}
        b._side_conditions={}; b._opponent_side_conditions={}; b._available_moves=[[],[]]; b._available_switches=[[],[]]; b._force_switch=[False,False]; b._active_pokemon={}
        def mk(sp):
            p=Pokemon.__new__(Pokemon); p._gen=9; p._species=sp; p._current_hp=100; p._max_hp=100
            p._type_1=PokemonType.ELECTRIC; p._type_2=PokemonType.DARK
            p._possible_abilities=[]; p._ability=None; p._moves={}; p._boosts={}; p._status=None; p._level=50
            p._heightm=1.0; p._weightkg=10.0; p._terastallized=False; p._last_details=''; p._last_request=None
            p._forme_change_ability=None; p._item=None; p._active=True; p._active_turns=0
            p._base_stats={}; p._evs={}; p._ivs={}; p._dancing=False; p._effects={}; p._gender='M'
            return p
        p1=mk('morpeko'); b._active_pokemon={0:p1,1:mk('g')}; b.get_pokemon=lambda ident,**kw: p1; return b,p1
    def tearDown(self): clear_observed_form_state("rs")
    def test_replay_events_processed_once(self):
        b,p1=self._b(); b._replay_data=[["","-formechange","0","Morpeko-Hangry"]]
        _scan_replay_for_form_changes(b); _scan_replay_for_form_changes(b)
        b2=MagicMock(battle_tag="rs"); self.assertIsNotNone(get_observed_form(b2,p1))
    def test_reverse_processed_and_recorded(self):
        b,p1=self._b(); b._replay_data=[["","-formechange","0","Morpeko-Hangry"],["","-formechange","0","Morpeko"]]
        _scan_replay_for_form_changes(b); b2=MagicMock(battle_tag="rs"); self.assertIsNotNone(get_observed_form(b2,p1))


# ====== Core Effective Type ======
class TestCore(unittest.TestCase):
    def test_full_belly_electric(self):
        self.assertEqual(get_effective_move_type(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpeko")),"ELECTRIC")
    def test_hangry_dark(self):
        self.assertEqual(get_effective_move_type(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpekohangry")),"DARK")
    def test_unknown_fallback(self):
        self.assertEqual(get_effective_move_type(_make_move("aurawheel","ELECTRIC"),None),"ELECTRIC")
    def test_ordinary_move_unchanged(self):
        self.assertEqual(get_effective_move_type(_make_move("thunderbolt","ELECTRIC"),MockPokemon("morpekohangry")),"ELECTRIC")
    def test_form_roundtrip(self):
        m=_make_move("aurawheel","ELECTRIC")
        self.assertEqual(get_effective_move_type(m,MockPokemon("morpeko")),"ELECTRIC")
        self.assertEqual(get_effective_move_type(m,MockPokemon("morpekohangry")),"DARK")
        self.assertEqual(get_effective_move_type(m,MockPokemon("morpeko")),"ELECTRIC")

class TestVoltAbsorbAndSafety(unittest.TestCase):
    def test_full_belly_blocked_by_volt_absorb(self):
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            self.assertTrue(ability_hard_blocks_move(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpeko"),MockPokemon("t"))[0])
    def test_hangry_not_blocked_by_volt_absorb(self):
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            self.assertFalse(ability_hard_blocks_move(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpekohangry"),MockPokemon("t"))[0])
    def test_waterfall_water_absorb_still_works(self):
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="waterabsorb"):
            self.assertTrue(ability_hard_blocks_move(_make_move("waterfall","WATER"),MockPokemon("g"),MockPokemon("v"))[0])
    def test_flamethrower_flash_fire_still_works(self):
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="flashfire"):
            self.assertTrue(ability_hard_blocks_move(_make_move("flamethrower","FIRE"),MockPokemon("c"),MockPokemon("a"))[0])
    def test_earthquake_levitate_still_works(self):
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="levitate"):
            self.assertTrue(ability_hard_blocks_move(_make_move("earthquake","GROUND"),MockPokemon("g"),MockPokemon("r"))[0])

class TestImmunity(unittest.TestCase):
    def test_full_belly_immune_ground(self):
        self.assertTrue(is_type_immune(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpeko"),MockPokemon("g",types=["DRAGON","GROUND"]))[0])
    def test_hangry_not_immune_ground(self):
        self.assertFalse(is_type_immune(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpekohangry"),MockPokemon("g",types=["DRAGON","GROUND"]))[0])


# ====== classify_dynamic_type_absorb_candidates Tests ======
class TestClassifyHelper(unittest.TestCase):
    def _patch_dynamic(self, etype, dyn=True, form="morpeko"):
        return patch("bot_doubles_damage_aware.resolve_effective_move_type",
                     return_value={"declared_type":"ELECTRIC","effective_type":etype,
                                    "source":"dynamic_form:"+form,"dynamic_applied":dyn,"observed_form":form})

    def test_full_belly_blocked_protect_selected_avoided(self):
        move = _make_move("aurawheel","ELECTRIC"); protect = _make_move("protect","NORMAL",bp=0)
        bc = _make_order(move,1); pc = _make_order(protect,0)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates([bc,pc],pc,MockPokemon("morpeko"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(bc):100,id(pc):80})
        self.assertTrue(r["candidate_blocked"]); self.assertFalse(r["selected"]); self.assertTrue(r["avoided"])

    def test_full_belly_selected(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates([c],c,MockPokemon("morpeko"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(c):100})
        self.assertTrue(r["candidate_blocked"]); self.assertTrue(r["selected"]); self.assertFalse(r["avoided"])

    def test_hangry_no_block(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus")
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            with self._patch_dynamic("DARK",form="morpekohangry"):
                r = classify_dynamic_type_absorb_candidates([c],c,MockPokemon("morpeko"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(c):100})
        self.assertFalse(r["candidate_blocked"])

    def test_static_thunderbolt_not_classified(self):
        move = _make_move("thunderbolt","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus")
        with patch("bot_doubles_damage_aware.get_known_ability",return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC",dyn=False):
                r = classify_dynamic_type_absorb_candidates([c],c,MockPokemon("raichu"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(c):100})
        self.assertFalse(r["candidate_blocked"])

    def test_unknown_ability_no_block(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus")
        with patch("bot_doubles_damage_aware.get_known_ability",return_value=None):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates([c],c,MockPokemon("morpeko"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(c):100})
        self.assertFalse(r["candidate_blocked"])

    def test_two_blocked_lower_score_selected_matches_selected_metadata(self):
        aw = _make_move("aurawheel","ELECTRIC")
        tb = _make_move("thunderbolt","ELECTRIC")
        bc_aw = _make_order(aw, 1)
        bc_tb = _make_order(tb, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates(
                    [bc_aw, bc_tb], bc_aw, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc_aw): 50, id(bc_tb): 100})
        self.assertTrue(r["candidate_blocked"])
        self.assertTrue(r["selected"])
        self.assertFalse(r["avoided"])
        self.assertEqual(r["reason"], "electric_into_voltabsorb")
        self.assertEqual(r["target_species"], "thundurus")
        self.assertEqual(r["target_ability"], "voltabsorb")
        self.assertEqual(r["blocked_order_id"], "aurawheel")
        self.assertEqual(r["blocked_candidate_score"], 50)

    def test_reason_not_in_allowlist_skipped(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="levitate"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates([c],c,MockPokemon("morpeko"),[t,None],MagicMock(battle_tag="t"),_absorb_config(),{id(c):100})
        self.assertFalse(r["candidate_blocked"])
        self.assertTrue(r["dynamic_candidate_available"])
        self.assertEqual(r["dynamic_candidate_move_id"], "aurawheel")

    def test_hangry_candidate_available_not_blocked(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus")
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("DARK", form="morpekohangry"):
                r = classify_dynamic_type_absorb_candidates(
                    [c], c, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(), {id(c): 100})
        self.assertTrue(r["dynamic_candidate_available"])
        self.assertEqual(r["dynamic_candidate_effective_type"], "DARK")
        self.assertEqual(r["dynamic_candidate_form"], "morpekohangry")
        self.assertFalse(r["candidate_blocked"])
        self.assertFalse(r["selected"])
        self.assertFalse(r["avoided"])

    def test_full_belly_volt_absorb_blocked_candidate_available(self):
        move = _make_move("aurawheel","ELECTRIC"); c = _make_order(move, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates(
                    [c], c, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(), {id(c): 100})
        self.assertTrue(r["dynamic_candidate_available"])
        self.assertEqual(r["dynamic_candidate_effective_type"], "ELECTRIC")
        self.assertEqual(r["dynamic_candidate_form"], "morpeko")
        self.assertTrue(r["candidate_blocked"])

    def test_duplicate_target_orders_count_one_opportunity(self):
        aw = _make_move("aurawheel","ELECTRIC")
        bc1 = _make_order(aw, 1)
        bc2 = _make_order(aw, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates(
                    [bc1, bc2], bc1, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc1): 50, id(bc2): 50})
        self.assertTrue(r["dynamic_candidate_available"])
        self.assertTrue(r["candidate_blocked"])

    def test_reverse_full_belly_hangry_full_belly_candidate_tracking(self):
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                r1 = classify_dynamic_type_absorb_candidates(
                    [_make_order(_make_move("aurawheel","ELECTRIC"), 1)],
                    _make_order(_make_move("aurawheel","ELECTRIC"), 1),
                    MockPokemon("morpeko"), [t, None],
                    MagicMock(battle_tag="t"), _absorb_config(),
                    {id(_make_order(_make_move("aurawheel","ELECTRIC"), 1)): 100})
            self.assertEqual(r1["dynamic_candidate_form"], "morpeko")
            self.assertTrue(r1["candidate_blocked"])

            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"DARK",
                                      "source":"dynamic_form:morpekohangry",
                                      "dynamic_applied":True,"observed_form":"morpekohangry"}):
                r2 = classify_dynamic_type_absorb_candidates(
                    [_make_order(_make_move("aurawheel","ELECTRIC"), 1)],
                    _make_order(_make_move("aurawheel","ELECTRIC"), 1),
                    MockPokemon("morpeko"), [t, None],
                    MagicMock(battle_tag="t"), _absorb_config(),
                    {id(_make_order(_make_move("aurawheel","ELECTRIC"), 1)): 100})
                self.assertEqual(r2["dynamic_candidate_form"], "morpekohangry")
                self.assertFalse(r2["candidate_blocked"])

    def test_static_move_no_candidate_opportunity(self):
        move = _make_move("thunderbolt","ELECTRIC"); c = _make_order(move, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC", dyn=False):
                r = classify_dynamic_type_absorb_candidates(
                    [c], c, MockPokemon("raichu"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(), {id(c): 100})
        self.assertFalse(r["dynamic_candidate_available"])
        self.assertFalse(r["candidate_blocked"])

    def test_full_belly_avoided_by_protect_candidate_available(self):
        move = _make_move("aurawheel","ELECTRIC"); protect = _make_move("protect","NORMAL",bp=0)
        bc = _make_order(move, 1); pc = _make_order(protect, 0)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with self._patch_dynamic("ELECTRIC"):
                r = classify_dynamic_type_absorb_candidates(
                    [bc, pc], pc, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc): 100, id(pc): 80})
        self.assertTrue(r["dynamic_candidate_available"])
        self.assertTrue(r["candidate_blocked"])
        self.assertFalse(r["selected"])
        self.assertTrue(r["avoided"])


# ====== Production API Tests (real scoring methods) ======
class TestProductionAPIs(unittest.TestCase):
    def _make_player(self, absorb_on=True):
        from bot_doubles_damage_aware import DoublesDamageAwarePlayer
        p = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        p.config = DoublesDamageAwareConfig()
        if absorb_on:
            p._real_config.ability_hard_safety_avoid_absorb = True
        p._real_config.enable_speed_priority_awareness = False
        p._active_config_override = None
        p.meta_engine = None; p.random_set_engine = None; p.verbose = False
        p.is_spread_move = MagicMock(return_value=False)
        p.is_opponent_spread_move = MagicMock(return_value=False)
        p.get_boosted_stat = MagicMock(return_value=STRENGTH_NORMAL)
        p.get_type_effectiveness = MagicMock(return_value=1.0)
        p.get_accuracy = MagicMock(return_value=1.0)
        p.estimate_opponent_max_hp = MagicMock(return_value=300)
        p.get_type_multiplier = MagicMock(return_value=1.0)
        p.check_move_will_ko = MagicMock(return_value=False)
        p.has_legal_protect_like_action = MagicMock(return_value=False)
        p.estimate_speed_priority_threat = MagicMock(return_value={"only_conditional_priority": False})
        p.selected_target_will_be_koed_before_second_action = MagicMock(return_value=False)
        p.get_pokemon_identifier = MagicMock(return_value="p1a: Morpeko")
        p.is_trick_room_active = MagicMock(return_value=False)
        p.initial_order_scoring_tune = MagicMock(return_value=0.0)
        p.analyze_move_type_matchup = MagicMock(return_value=MagicMock())
        p.score_opponent_threat = MagicMock()
        p.is_defensive_mon = MagicMock()
        p.is_offensive_mon = MagicMock()
        p.score_ally_fragility = MagicMock()
        p.estimate_defensive_fragility = MagicMock()
        p.estimate_offensive_threat = MagicMock()
        p.is_support_mon = MagicMock()
        p.increment_metric = MagicMock()
        for m in ['partial_immune_spread_by_battle','partial_ability_immune_spread_by_battle',
                   'efficient_partial_spread_by_battle','inefficient_partial_spread_by_battle',
                   'immune_target_species_by_battle','damaged_target_species_by_battle',
                   'best_single_alternative_by_battle','_ability_hard_block_avoided',
                   '_ability_immune_move_selected','_ground_into_levitate_selected',
                   '_ability_block_reason','_ability_blocked_target_species',
                   '_ability_blocked_target_ability','_ally_ability_safe_spread',
                   '_ability_redirection_avoided','_direct_absorb_hard_block_avoided',
                   '_direct_absorb_immune_move_selected','_direct_absorb_block_reason',
                   '_direct_absorb_target_species','_direct_absorb_target_ability',
                   '_direct_absorb_only_legal_action','_known_ally_redirect_selected',
                   '_known_ally_redirect_reason','_known_ally_redirect_ally_species',
                   '_known_ally_redirect_ally_ability','_known_ally_redirect_move_id',
                   'partial_ability_immune_spread_selected','_pure_scoring_mode',
                   '_base_scores_cache',
                   '_priority_move_field_blocked','_priority_move_block_reason',
                   '_priority_move_block_avoided',
                   '_stale_target_selected','_stale_target_avoided',
                   'skill_scores','_team_preview_override','_forced_switch_safety_handled',
                   '_forced_switch_candidates','_force_switch_safety_applied',
                   '_forced_switch_safety_applied','_switch_candidate_safety_applied',
                   '_switch_candidate_ranking_applied','_revealed_switch_interception_active',
                   '_revealed_switch_interception_applied','_stat_drop_switch_diagnostics_data',
                   '_stat_drop_switch_scoring_active']:
            if not hasattr(p, m): setattr(p, m, {})
        return p

    def _make_battle(self, active_mon, opp_mon, tag="t"):
        b = MagicMock()
        b.active_pokemon = [active_mon, MockPokemon("ally")]
        b.opponent_active_pokemon = [opp_mon, None]
        b.fields = []; b.turn = 1; b.battle_tag = tag
        b.available_moves = [[], []]
        b.available_switches = [[]]
        b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}
        b.weather = None
        return b

    def test_get_expected_damage_full_belly_volt_absorb_zero(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.active_pokemon[0]._ability = None
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            self.assertEqual(player.get_expected_damage(move, attacker, target, b), 0.0)

    def test_get_expected_damage_hangry_volt_absorb_positive(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpekohangry")
        target = MockPokemon("thundurus"); target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.active_pokemon[0]._ability = None
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            self.assertGreater(player.get_expected_damage(move, attacker, target, b), 0.0)

    def test_score_action_raw_damage_full_belly_immune_ground(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpeko"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("garchomp", types=["DRAGON","GROUND"])
        b = self._make_battle(attacker, target)
        order = _make_order(move, 1)
        self.assertEqual(player.score_action_raw_damage(order, 0, b), 0.0)

    def test_score_action_raw_damage_hangry_into_ground_positive(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpekohangry"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("garchomp", types=["DRAGON","GROUND"])
        b = self._make_battle(attacker, target)
        order = _make_order(move, 1)
        self.assertGreater(player.score_action_raw_damage(order, 0, b), 0.0)

    def test_score_action_full_belly_volt_absorb_equals_block_score(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpeko"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("thundurus"); target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.available_moves = [[move], []]
        order = _make_order(move, 1)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            sc = player.score_action(order, 0, b, config=player.config, pure=True)
        self.assertEqual(sc, float(player.config.ability_hard_safety_block_score))

    def test_score_action_hangry_volt_absorb_above_block_score(self):
        player = self._make_player(absorb_on=True)
        move = _make_move("aurawheel","ELECTRIC"); attacker = MockPokemon("morpekohangry"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("thundurus"); target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.available_moves = [[move], []]
        order = _make_order(move, 1)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            sc = player.score_action(order, 0, b, config=player.config, pure=True)
        self.assertGreater(sc, float(player.config.ability_hard_safety_block_score))


# ====== _select_best_joint_order Production Tests ======
class TestSelectBestJointOrder(unittest.TestCase):
    def _make_player(self, absorb_on=True):
        from bot_doubles_damage_aware import DoublesDamageAwarePlayer
        p = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        p.config = DoublesDamageAwareConfig()
        if absorb_on:
            p._real_config.ability_hard_safety_avoid_absorb = True
        p._real_config.enable_speed_priority_awareness = False
        p._active_config_override = None
        p.meta_engine = None; p.random_set_engine = None; p.verbose = False
        p.is_spread_move = MagicMock(return_value=False)
        p.is_opponent_spread_move = MagicMock(return_value=False)
        p.get_boosted_stat = MagicMock(return_value=STRENGTH_NORMAL)
        p.get_type_effectiveness = MagicMock(return_value=1.0)
        p.get_accuracy = MagicMock(return_value=1.0)
        p.estimate_opponent_max_hp = MagicMock(return_value=300)
        p.get_type_multiplier = MagicMock(return_value=1.0)
        p.check_move_will_ko = MagicMock(return_value=False)
        p.has_legal_protect_like_action = MagicMock(return_value=False)
        p.estimate_speed_priority_threat = MagicMock(return_value={"only_conditional_priority": False})
        p.selected_target_will_be_koed_before_second_action = MagicMock(return_value=False)
        p.get_pokemon_identifier = MagicMock(return_value="p1a: Morpeko")
        p.is_trick_room_active = MagicMock(return_value=False)
        p.initial_order_scoring_tune = MagicMock(return_value=0.0)
        p.analyze_move_type_matchup = MagicMock(return_value=MagicMock())
        p.score_opponent_threat = MagicMock()
        p.is_defensive_mon = MagicMock()
        p.is_offensive_mon = MagicMock()
        p.score_ally_fragility = MagicMock()
        p.estimate_defensive_fragility = MagicMock()
        p.estimate_offensive_threat = MagicMock()
        p.is_support_mon = MagicMock()
        p.increment_metric = MagicMock()
        for m in ['partial_immune_spread_by_battle','partial_ability_immune_spread_by_battle',
                   'efficient_partial_spread_by_battle','inefficient_partial_spread_by_battle',
                   'immune_target_species_by_battle','damaged_target_species_by_battle',
                   'best_single_alternative_by_battle','_ability_hard_block_avoided',
                   '_ability_immune_move_selected','_ground_into_levitate_selected',
                   '_ability_block_reason','_ability_blocked_target_species',
                   '_ability_blocked_target_ability','_ally_ability_safe_spread',
                   '_ability_redirection_avoided','_direct_absorb_hard_block_avoided',
                   '_direct_absorb_immune_move_selected','_direct_absorb_block_reason',
                   '_direct_absorb_target_species','_direct_absorb_target_ability',
                   '_direct_absorb_only_legal_action','_known_ally_redirect_selected',
                   '_known_ally_redirect_reason','_known_ally_redirect_ally_species',
                   '_known_ally_redirect_ally_ability','_known_ally_redirect_move_id',
                   'partial_ability_immune_spread_selected','_pure_scoring_mode',
                   '_base_scores_cache',
                   '_priority_move_field_blocked','_priority_move_block_reason',
                   '_priority_move_block_avoided',
                   '_stale_target_selected','_stale_target_avoided',
                   'skill_scores','_team_preview_override','_forced_switch_safety_handled',
                   '_forced_switch_candidates','_force_switch_safety_applied',
                   '_forced_switch_safety_applied','_switch_candidate_safety_applied',
                   '_switch_candidate_ranking_applied','_revealed_switch_interception_active',
                   '_revealed_switch_interception_applied','_stat_drop_switch_diagnostics_data',
                   '_stat_drop_switch_scoring_active','_known_ally_redirect_streak',
                   '_ally_redirect_blocked','_ally_redirect_blocked_meta',
                   '_order_aware_overkill_penalty_applied','_neg_boost_dedup_keys',
                   'auto_scores','_delay_policy','_cache','_last_battle_tag',
                   '_ability_safety_forbidden','_ability_safety_forced']:
            if not hasattr(p, m): setattr(p, m, {})
        return p

    def _make_battle(self, active_mon, opp_mon, ally=None, tag="t"):
        b = MagicMock()
        b.active_pokemon = [active_mon, ally or MockPokemon("ally")]
        b.opponent_active_pokemon = [opp_mon, None]
        b.fields = []; b.turn = 1; b.battle_tag = tag
        b.available_moves = [[], []]
        b.available_switches = [[]]
        b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}
        b.weather = None
        return b

    def _make_joint(self, first_order, second_order):
        jo = MagicMock()
        jo.first_order = first_order
        jo.second_order = second_order
        return jo

    def test_full_belly_blocked_loses_to_safe_legal_order(self):
        player = self._make_player(absorb_on=True)
        aw_move = _make_move("aurawheel","ELECTRIC"); safe_move = _make_move("protect","NORMAL",bp=0)
        attacker = MockPokemon("morpeko"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("thundurus"); target.species = "thundurus"; target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.available_moves = [[aw_move, safe_move], []]
        aw_order = _make_order(aw_move, 1)
        safe_order = _make_order(safe_move, 0)
        ally_order = _make_order(safe_move, 0)

        blocked_joint = self._make_joint(aw_order, ally_order)
        safe_joint = self._make_joint(safe_order, ally_order)

        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                best = player._select_best_joint_order(
                    b, player.config,
                    [blocked_joint, safe_joint],
                    [[aw_order, safe_order], [ally_order]],
                    pure=True)[0]
                self.assertIs(best, safe_joint)

    def test_hangry_can_win_when_damage_score_highest(self):
        player = self._make_player(absorb_on=True)
        aw_move = _make_move("aurawheel","ELECTRIC",bp=80); safe_move = _make_move("protect","NORMAL",bp=0)
        attacker = MockPokemon("morpekohangry"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("thundurus"); target.species = "thundurus"; target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.available_moves = [[aw_move, safe_move], []]
        aw_order = _make_order(aw_move, 1)
        safe_order = _make_order(safe_move, 0)
        ally_order = _make_order(safe_move, 0)

        aw_joint = self._make_joint(aw_order, ally_order)
        safe_joint = self._make_joint(safe_order, ally_order)

        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"DARK",
                                      "source":"dynamic_form:morpekohangry","dynamic_applied":True,
                                      "observed_form":"morpekohangry"}):
                best = player._select_best_joint_order(
                    b, player.config,
                    [aw_joint, safe_joint],
                    [[aw_order, safe_order], [ally_order]],
                    pure=True)[0]
                self.assertIs(best, aw_joint)

    def test_reverse_to_full_belly_blocks_again(self):
        player = self._make_player(absorb_on=True)
        aw_move = _make_move("aurawheel","ELECTRIC",bp=80); safe_move = _make_move("protect","NORMAL",bp=0)
        attacker = MockPokemon("morpeko"); attacker._types = ["ELECTRIC","DARK"]
        target = MockPokemon("thundurus"); target.species = "thundurus"; target._types = ["ELECTRIC","FLYING"]
        b = self._make_battle(attacker, target)
        b.available_moves = [[aw_move, safe_move], []]
        aw_order = _make_order(aw_move, 1)
        safe_order = _make_order(safe_move, 0)
        ally_order = _make_order(safe_move, 0)

        blocked_joint = self._make_joint(aw_order, ally_order)
        safe_joint = self._make_joint(safe_order, ally_order)

        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                best = player._select_best_joint_order(
                    b, player.config,
                    [blocked_joint, safe_joint],
                    [[aw_order, safe_order], [ally_order]],
                    pure=True)[0]
                self.assertIs(best, safe_joint)


# ====== Logger / Analyzer / Inspector (real production call flow) ======
class TestLoggerAnalyzer(unittest.TestCase):
    def _make_joint(self, first_order, second_order):
        jo = MagicMock()
        jo.first_order = first_order
        jo.second_order = second_order
        return jo

    def _log_blocked_selected(self, logger, fp):
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "test"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        bw_order = _make_order(aw_move, 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(bw_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [bw_order], bw_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(bw_order): 100.0})
                logger.log_turn_decision(
                    battle_tag="test", turn=1, battle=b,
                    selected_joint_order="/choose move aurawheel|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["ELECTRIC", ""],
                    effective_move_type_source=["static", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[
                        absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[
                        absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[
                        absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[
                        absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[
                        absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[
                        absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[
                        absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[
                        absorb_result["blocked_candidate_score"], 0.0],
                    dynamic_type_absorb_candidate_available=[
                        absorb_result["dynamic_candidate_available"], False],
                    dynamic_type_absorb_candidate_move_id=[
                        absorb_result["dynamic_candidate_move_id"], ""],
                    dynamic_type_absorb_candidate_declared_type=[
                        absorb_result["dynamic_candidate_declared_type"], ""],
                    dynamic_type_absorb_candidate_effective_type=[
                        absorb_result["dynamic_candidate_effective_type"], ""],
                    dynamic_type_absorb_candidate_form=[
                        absorb_result["dynamic_candidate_form"], ""],
                    dynamic_type_absorb_candidate_source=[
                        absorb_result["dynamic_candidate_source"], ""],
                    dynamic_type_absorb_candidate_target_table=[
                        absorb_result["dynamic_candidate_target_table"], []],
                )
                logger.save_battle(battle_tag="test", winner="test", battle=b)

    def test_logger_writes_dynamic_fields_from_classification(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        self.assertEqual(s0["declared_move_type"], "ELECTRIC")
        self.assertEqual(s0["effective_move_type"], "ELECTRIC")
        self.assertEqual(s0["effective_move_type_source"], "static")
        self.assertTrue(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertTrue(s0["dynamic_type_absorb_selected"])
        self.assertFalse(s0["dynamic_type_absorb_avoided"])
        self.assertEqual(s0["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "thundurus")
        self.assertEqual(s0["dynamic_type_absorb_target_ability"], "voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_blocked_move_id"], "aurawheel")
        self.assertEqual(s0["dynamic_type_absorb_blocked_candidate_score"], 100.0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_logger_two_slot_isolation_only_blocked_slot_has_absorb_fields(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)

        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        ally = MockPokemon("b")
        b = MagicMock(); b.turn = 1; b.battle_tag = "test2"
        b.active_pokemon = [attacker, ally]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None

        aw_move = _make_move("aurawheel","ELECTRIC")
        safe_move = _make_move("thunderbolt","ELECTRIC")
        slot0_order = _make_order(aw_move, 1)
        slot1_order = _make_order(safe_move, 2)
        jo = self._make_joint(slot0_order, slot1_order)

        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [slot0_order], slot0_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(slot0_order): 100.0})

                logger.log_turn_decision(
                    battle_tag="test2", turn=1, battle=b,
                    selected_joint_order="/choose move aurawheel|move thunderbolt",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move thunderbolt"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", "ELECTRIC"],
                    effective_move_type=["ELECTRIC", "ELECTRIC"],
                    effective_move_type_source=["static", "static"],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[
                        absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[
                        absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[
                        absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[
                        absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[
                        absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[
                        absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[
                        absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[
                        absorb_result["blocked_candidate_score"], 0.0],
                )
                logger.save_battle(battle_tag="test2", winner="test", battle=b)

        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        s1 = r["audit_turns"][0]["slot_1"]
        self.assertTrue(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertTrue(s0["dynamic_type_absorb_selected"])
        self.assertEqual(s0["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertFalse(s1.get("dynamic_type_absorb_candidate_blocked", False))
        self.assertEqual(s1.get("dynamic_type_absorb_reason", ""), "")
        self.assertEqual(s1.get("dynamic_type_absorb_blocked_move_id", ""), "")
        self.assertEqual(s1.get("dynamic_type_absorb_blocked_candidate_score", 0.0), 0.0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_avoided_candidate_blocked_through_classification(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        pt_move = _make_move("protect","NORMAL",bp=0)
        aw_order = _make_order(aw_move, 1)
        pt_order = _make_order(pt_move, 0)
        ally_order = _make_order(pt_move, 0)
        jo = self._make_joint(pt_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [aw_order, pt_order], pt_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(aw_order): 100, id(pt_order): 80})
                logger.log_turn_decision(
                    battle_tag="t", turn=1, battle=b,
                    selected_joint_order="/choose move protect|move protect",
                    selected_score=80, scored_joint_orders=[(jo, 80, 40, 40)],
                    expected_damages=[0, 0], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move protect", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["ELECTRIC", ""],
                    effective_move_type_source=["static", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[
                        absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[
                        absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[
                        absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[
                        absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[
                        absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[
                        absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[
                        absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[
                        absorb_result["blocked_candidate_score"], 0.0],
                )
                logger.save_battle(battle_tag="t", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        self.assertTrue(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertFalse(s0["dynamic_type_absorb_selected"])
        self.assertTrue(s0["dynamic_type_absorb_avoided"])
        self.assertEqual(s0["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "thundurus")
        self.assertEqual(s0["dynamic_type_absorb_blocked_move_id"], "aurawheel")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_hangry_no_absorb_does_not_populate_absorb_fields(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        aw_order = _make_order(aw_move, 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(aw_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"DARK",
                                      "source":"dynamic_form:morpekohangry","dynamic_applied":True,
                                      "observed_form":"morpekohangry"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [aw_order], aw_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(aw_order): 100.0})
                logger.log_turn_decision(
                    battle_tag="t", turn=1, battle=b,
                    selected_joint_order="/choose move aurawheel|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["DARK", ""],
                    effective_move_type_source=["dynamic_form:morpekohangry", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpekohangry", ""],
                    dynamic_type_absorb_candidate_blocked=[
                        absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[
                        absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[
                        absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[
                        absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[
                        absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[
                        absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[
                        absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[
                        absorb_result["blocked_candidate_score"], 0.0],
                )
                logger.save_battle(battle_tag="t", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        self.assertTrue(s0["dynamic_move_type_applied"])
        self.assertEqual(s0["effective_move_type"], "DARK")
        self.assertFalse(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertFalse(s0["dynamic_type_absorb_selected"])
        self.assertFalse(s0["dynamic_type_absorb_avoided"])
        self.assertEqual(s0["dynamic_type_absorb_reason"], "")
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "")
        self.assertEqual(s0["dynamic_type_absorb_blocked_move_id"], "")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_accounting_invariant_blocked_equals_selected_plus_avoided(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)

        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None

        aw_move = _make_move("aurawheel","ELECTRIC"); pt_move = _make_move("protect","NORMAL",bp=0)
        aw_order = _make_order(aw_move, 1); pt_order = _make_order(pt_move, 0)
        ally_order = _make_order(pt_move, 0)

        cases = [
            ("selected_blocked", aw_order, True, True, False),
            ("avoided_blocked", pt_order, True, False, True),
        ]
        for tag, sel_ord, exp_blocked, exp_sel, exp_avoid in cases:
            fp2 = os.path.join(tmp, f"{tag}.jsonl")
            logger2 = DoublesDecisionAuditLogger(filepath=fp2, reset=True)
            jo = self._make_joint(sel_ord, ally_order)
            with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
                with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                           return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                          "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                    absorb_result = classify_dynamic_type_absorb_candidates(
                        [aw_order, pt_order], sel_ord, attacker,
                        [target, None], b, _absorb_config(),
                        {id(aw_order): 100, id(pt_order): 80})
                    logger2.log_turn_decision(
                        battle_tag=tag, turn=1, battle=b,
                        selected_joint_order="/choose move test|move protect",
                        selected_score=80, scored_joint_orders=[(jo, 80, 40, 40)],
                        expected_damages=[0, 0], expected_kos=[False, False],
                        target_hps=[1, 1],
                        overkill_triggered=False, focus_fire_triggered=False,
                        ally_hit_penalty_triggered=False,
                        spread_available=[False, False], best_spread_score=[0, 0],
                        best_ko_score=[0, 0],
                        low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                        slot_actions=["move test", "move protect"],
                        slot_action_types=[{}, {}],
                        target_species=["thundurus", ""],
                        declared_move_type=["ELECTRIC", ""],
                        effective_move_type=["ELECTRIC", ""],
                        effective_move_type_source=["static", ""],
                        dynamic_move_type_applied=[True, False],
                        dynamic_move_type_form=["morpeko", ""],
                        dynamic_type_absorb_candidate_blocked=[
                            absorb_result["candidate_blocked"], False],
                        dynamic_type_absorb_selected=[
                            absorb_result["selected"], False],
                        dynamic_type_absorb_avoided=[
                            absorb_result["avoided"], False],
                        dynamic_type_absorb_reason=[
                            absorb_result["reason"], ""],
                        dynamic_type_absorb_target_species=[
                            absorb_result["target_species"], ""],
                        dynamic_type_absorb_target_ability=[
                            absorb_result["target_ability"], ""],
                        dynamic_type_absorb_blocked_move_id=[
                            absorb_result["blocked_order_id"], ""],
                        dynamic_type_absorb_blocked_candidate_score=[
                            absorb_result["blocked_candidate_score"], 0.0],
                    )
                    logger2.save_battle(battle_tag=tag, winner="test", battle=b)
            with open(fp2) as f:
                r = json.loads(f.readline())
            s0 = r["audit_turns"][0]["slot_0"]
            self.assertEqual(s0["dynamic_type_absorb_candidate_blocked"], exp_blocked, tag)
            self.assertEqual(s0["dynamic_type_absorb_selected"], exp_sel, tag)
            self.assertEqual(s0["dynamic_type_absorb_avoided"], exp_avoid, tag)
            self.assertFalse(s0["dynamic_type_absorb_selected"] and s0["dynamic_type_absorb_avoided"], tag)
            if s0["dynamic_type_absorb_candidate_blocked"]:
                self.assertEqual(int(s0["dynamic_type_absorb_candidate_blocked"]),
                                 int(s0["dynamic_type_absorb_selected"]) + int(s0["dynamic_type_absorb_avoided"]),
                                 tag)
            os.remove(fp2)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_non_dynamic_static_move_not_in_report(self):
        move = _make_move("thunderbolt","ELECTRIC"); c = _make_order(move,1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":False,"observed_form":""}):
                r = classify_dynamic_type_absorb_candidates(
                    [c], c, MockPokemon("raichu"), [t, None],
                    MagicMock(battle_tag="t"), _absorb_config(), {id(c): 100})
        self.assertFalse(r["candidate_blocked"])
        self.assertFalse(r["selected"])
        self.assertFalse(r["avoided"])

    def test_slot1_does_not_inherit_slot0_metadata(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)

        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None

        aw_move = _make_move("aurawheel","ELECTRIC")
        slot0 = _make_order(aw_move, 1)
        slot1 = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(slot0, slot1)

        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [slot0], slot0, attacker,
                    [target, None], b, _absorb_config(),
                    {id(slot0): 100.0})
                logger.log_turn_decision(
                    battle_tag="t", turn=1, battle=b,
                    selected_joint_order="/choose move aurawheel|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["ELECTRIC", ""],
                    effective_move_type_source=["static", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[True, False],
                    dynamic_type_absorb_selected=[True, False],
                    dynamic_type_absorb_avoided=[False, False],
                    dynamic_type_absorb_reason=["electric_into_voltabsorb", ""],
                    dynamic_type_absorb_target_species=["thundurus", ""],
                    dynamic_type_absorb_target_ability=["voltabsorb", ""],
                    dynamic_type_absorb_blocked_move_id=["aurawheel", ""],
                    dynamic_type_absorb_blocked_candidate_score=[100.0, 0.0],
                )
                logger.save_battle(battle_tag="t", winner="test", battle=b)

        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        s1 = r["audit_turns"][0]["slot_1"]
        self.assertTrue(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "thundurus")
        self.assertFalse(s1.get("dynamic_type_absorb_candidate_blocked", False))
        self.assertEqual(s1.get("dynamic_type_absorb_target_species", ""), "")
        self.assertEqual(s1.get("dynamic_type_absorb_blocked_move_id", ""), "")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_analyzer_dynamic_report_heading(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("Dynamic Move Type Safety Report", out)

    def test_analyzer_reports_blocked_selected_avoided_counts(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("dynamic absorb candidates blocked", out)
        self.assertIn("dynamic absorb candidates selected", out)
        self.assertIn("dynamic absorb candidates avoided", out)
        self.assertIn("block reason split", out)
        self.assertIn("blocked move ID split", out)
        self.assertIn("target species split", out)
        self.assertIn("target ability split", out)
        self.assertIn("Sample cases", out)

    def test_analyzer_win_loss_aggregation(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "winbt"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_order = _make_order(_make_move("aurawheel","ELECTRIC"), 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(aw_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [aw_order], aw_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(aw_order): 100.0})
                logger.log_turn_decision(
                    battle_tag="winbt", turn=1, battle=b,
                    selected_joint_order="/choose move test|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move test", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["ELECTRIC", ""],
                    effective_move_type_source=["static", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[True, False],
                    dynamic_type_absorb_selected=[True, False],
                    dynamic_type_absorb_avoided=[False, False],
                    dynamic_type_absorb_reason=[absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[absorb_result["blocked_candidate_score"], 0.0],
                )
                logger.save_battle(battle_tag="winbt", winner="player", battle=b)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("selected wins / losses", out)

    def test_inspector_prints_declared_effective(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("Declared:", out); self.assertIn("Effective:", out)

    def test_inspector_candidate_blocked_filter(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp,"--candidate-blocked"]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("SELECTED", out)
        self.assertIn("candidate_blocked", out)

    def test_inspector_selected_filter(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp,"--selected"]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("SELECTED", out)

    def test_inspector_reason_filter(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp,"--reason","electric_into_voltabsorb"]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("electric_into_voltabsorb", out)

    def test_inspector_battle_filter(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp,"--battle","test"]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("test", out)

    def test_inspector_form_filter(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp,"--form","morpeko"]; im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("morpeko", out)

    def test_audit_exact_fields_from_real_classification(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 3; b.battle_tag = "exact-bt"
        b.active_pokemon = [attacker, MockPokemon("ally")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        aw_order = _make_order(aw_move, 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(aw_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [aw_order], aw_order, attacker,
                    [target, None], b, _absorb_config(),
                    {id(aw_order): 100.0})
                logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
                logger.log_turn_decision(
                    battle_tag="exact-bt", turn=3, battle=b,
                    selected_joint_order="/choose move aurawheel|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["ELECTRIC", ""],
                    effective_move_type_source=["static", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpeko", ""],
                    dynamic_type_absorb_candidate_blocked=[
                        absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[
                        absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[
                        absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[
                        absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[
                        absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[
                        absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[
                        absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[
                        absorb_result["blocked_candidate_score"], 0.0],
                )
                logger.save_battle(battle_tag="exact-bt", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        self.assertEqual(r["battle_tag"], "exact-bt")
        self.assertEqual(r["audit_turns"][0]["turn"], 3)
        self.assertIn("aurawheel", r["audit_turns"][0].get("selected_joint_order", ""))
        self.assertEqual(s0["declared_move_type"], "ELECTRIC")
        self.assertEqual(s0["effective_move_type"], "ELECTRIC")
        self.assertEqual(s0["effective_move_type_source"], "static")
        self.assertEqual(s0["dynamic_move_type_form"], "morpeko")
        self.assertTrue(s0["dynamic_move_type_applied"])
        self.assertTrue(s0["dynamic_type_absorb_candidate_blocked"])
        self.assertTrue(s0["dynamic_type_absorb_selected"])
        self.assertEqual(s0["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "thundurus")
        self.assertEqual(s0["dynamic_type_absorb_target_ability"], "voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_blocked_move_id"], "aurawheel")
        self.assertEqual(s0["dynamic_type_absorb_blocked_candidate_score"], 100.0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_declared_effective_excluded_from_split(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_order = _make_order(_make_move("aurawheel","ELECTRIC"), 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(aw_order, ally_order)
        logger.log_turn_decision(
            battle_tag="t", turn=1, battle=b,
            selected_joint_order="/choose move aurawheel|move protect",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move aurawheel", "move protect"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["", "ELECTRIC"],
            effective_move_type=["", ""],
            effective_move_type_source=["", "static"],
            dynamic_move_type_applied=[True, False],
            dynamic_move_type_form=["morpeko", ""],
            dynamic_type_absorb_candidate_blocked=[False, False],
            dynamic_type_absorb_selected=[False, False],
            dynamic_type_absorb_avoided=[False, False],
            dynamic_type_absorb_reason=["", ""],
            dynamic_type_absorb_target_species=["", ""],
            dynamic_type_absorb_target_ability=["", ""],
            dynamic_type_absorb_blocked_move_id=["", ""],
            dynamic_type_absorb_blocked_candidate_score=[0.0, 0.0],
        )
        logger.save_battle(battle_tag="t", winner="test", battle=b)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("declared -> effective type split       : {}", out)

    def test_non_dynamic_ordinary_slot_excluded_from_split(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        tb_order = _make_order(_make_move("thunderbolt","ELECTRIC"), 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(tb_order, ally_order)
        logger.log_turn_decision(
            battle_tag="t", turn=1, battle=b,
            selected_joint_order="/choose move thunderbolt|move protect",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move thunderbolt", "move protect"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", ""],
            effective_move_type=["ELECTRIC", ""],
            effective_move_type_source=["static", ""],
            dynamic_move_type_applied=[False, False],
            dynamic_move_type_form=["", ""],
            dynamic_type_absorb_candidate_blocked=[False, False],
            dynamic_type_absorb_selected=[False, False],
            dynamic_type_absorb_avoided=[False, False],
            dynamic_type_absorb_reason=["", ""],
            dynamic_type_absorb_target_species=["", ""],
            dynamic_type_absorb_target_ability=["", ""],
            dynamic_type_absorb_blocked_move_id=["", ""],
            dynamic_type_absorb_blocked_candidate_score=[0.0, 0.0],
        )
        logger.save_battle(battle_tag="t", winner="test", battle=b)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("declared -> effective type split       : {}", out)

    def test_analyzer_attacker_metadata_in_samples(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("attacker:", out)
        self.assertIn("morpeko", out)

    def test_analyzer_accounting_invariant_printed(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("accounting invariant:", out)
        self.assertIn("PASS", out)

    def test_analyzer_accounting_invariant_no_crash_on_legacy(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        bw_order = _make_order(aw_move, 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(bw_order, ally_order)
        logger.log_turn_decision(
            battle_tag="t", turn=1, battle=b,
            selected_joint_order="/choose move aurawheel|move protect",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move aurawheel", "move protect"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", ""],
            effective_move_type=["ELECTRIC", ""],
            effective_move_type_source=["static", ""],
            dynamic_move_type_applied=[True, False],
            dynamic_move_type_form=["morpeko", ""],
            dynamic_type_absorb_candidate_blocked=[True, False],
            dynamic_type_absorb_selected=[True, False],
            dynamic_type_absorb_avoided=[False, False],
            dynamic_type_absorb_reason=["electric_into_voltabsorb", ""],
            dynamic_type_absorb_target_species=["thundurus", ""],
            dynamic_type_absorb_target_ability=["voltabsorb", ""],
            dynamic_type_absorb_blocked_move_id=["aurawheel", ""],
            dynamic_type_absorb_blocked_candidate_score=[100.0, 0.0],
        )
        logger.save_battle(battle_tag="t", winner="test", battle=b)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp); out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("accounting invariant:", out)
        self.assertIn("PASS", out)

    def test_inspector_attacker_metadata_printed(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp]
            im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("Attacker:", out)
        self.assertIn("morpeko", out)

    def test_inspector_default_excludes_ordinary_static(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        tb_order = _make_order(_make_move("thunderbolt","ELECTRIC"), 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(tb_order, ally_order)
        logger.log_turn_decision(
            battle_tag="t", turn=1, battle=b,
            selected_joint_order="/choose move thunderbolt|move protect",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move thunderbolt", "move protect"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", ""],
            effective_move_type=["ELECTRIC", ""],
            effective_move_type_source=["static", ""],
            dynamic_move_type_applied=[False, False],
            dynamic_move_type_form=["", ""],
            dynamic_type_absorb_candidate_blocked=[False, False],
            dynamic_type_absorb_selected=[False, False],
            dynamic_type_absorb_avoided=[False, False],
            dynamic_type_absorb_reason=["", ""],
            dynamic_type_absorb_target_species=["", ""],
            dynamic_type_absorb_target_ability=["", ""],
            dynamic_type_absorb_blocked_move_id=["", ""],
            dynamic_type_absorb_blocked_candidate_score=[0.0, 0.0],
        )
        logger.save_battle(battle_tag="t", winner="test", battle=b)
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from inspect_dynamic_move_type_cases import main as im
            sys.argv = ["insp","--filepath",fp]
            im(); out = sys.stdout.getvalue()
        except SystemExit: out = sys.stdout.getvalue()
        finally: sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("No dynamic type cases found", out.strip() if out.strip() else out)

    def test_logger_candidate_available_fields_serialized(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        self.assertTrue(s0["dynamic_type_absorb_candidate_available"])
        self.assertEqual(s0["dynamic_type_absorb_candidate_move_id"], "aurawheel")
        self.assertEqual(s0["dynamic_type_absorb_candidate_declared_type"], "ELECTRIC")
        self.assertEqual(s0["dynamic_type_absorb_candidate_effective_type"], "ELECTRIC")
        self.assertEqual(s0["dynamic_type_absorb_candidate_form"], "morpeko")
        self.assertIn("static", s0["dynamic_type_absorb_candidate_source"])
        self.assertIsInstance(s0["dynamic_type_absorb_candidate_target_table"], list)
        self.assertGreater(len(s0["dynamic_type_absorb_candidate_target_table"]), 0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_target_table_full_belly_volt_absorb_blocked(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        table = s0["dynamic_type_absorb_candidate_target_table"]
        self.assertEqual(len(table), 1)
        row = table[0]
        self.assertEqual(row["move_id"], "aurawheel")
        self.assertEqual(row["declared_type"], "ELECTRIC")
        self.assertEqual(row["effective_type"], "ELECTRIC")
        self.assertEqual(row["form"], "morpeko")
        self.assertEqual(row["target_position"], 1)
        self.assertEqual(row["target_species"], "thundurus")
        self.assertEqual(row["target_known_ability"], "voltabsorb")
        self.assertTrue(row["ability_blocked"])
        self.assertTrue(row["selected"])
        self.assertEqual(row["block_reason"], "electric_into_voltabsorb")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_target_table_hangry_not_blocked(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        b = MagicMock(); b.turn = 1; b.battle_tag = "t"
        b.active_pokemon = [attacker, MockPokemon("b")]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel","ELECTRIC")
        aw_order = _make_order(aw_move, 1)
        ally_order = _make_order(_make_move("protect","NORMAL",bp=0), 0)
        jo = self._make_joint(aw_order, ally_order)
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"DARK",
                                      "source":"dynamic_form:morpekohangry","dynamic_applied":True,
                                      "observed_form":"morpekohangry"}):
                absorb_result = classify_dynamic_type_absorb_candidates(
                    [aw_order], aw_order, attacker,
                    [target, None], b, _absorb_config(), {id(aw_order): 100.0})
                logger.log_turn_decision(
                    battle_tag="t", turn=1, battle=b,
                    selected_joint_order="/choose move aurawheel|move protect",
                    selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
                    expected_damages=[50, 50], expected_kos=[False, False],
                    target_hps=[1, 1],
                    overkill_triggered=False, focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False], best_spread_score=[0, 0],
                    best_ko_score=[0, 0],
                    low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
                    slot_actions=["move aurawheel", "move protect"],
                    slot_action_types=[{}, {}],
                    target_species=["thundurus", ""],
                    declared_move_type=["ELECTRIC", ""],
                    effective_move_type=["DARK", ""],
                    effective_move_type_source=["dynamic_form:morpekohangry", ""],
                    dynamic_move_type_applied=[True, False],
                    dynamic_move_type_form=["morpekohangry", ""],
                    dynamic_type_absorb_candidate_blocked=[absorb_result["candidate_blocked"], False],
                    dynamic_type_absorb_selected=[absorb_result["selected"], False],
                    dynamic_type_absorb_avoided=[absorb_result["avoided"], False],
                    dynamic_type_absorb_reason=[absorb_result["reason"], ""],
                    dynamic_type_absorb_target_species=[absorb_result["target_species"], ""],
                    dynamic_type_absorb_target_ability=[absorb_result["target_ability"], ""],
                    dynamic_type_absorb_blocked_move_id=[absorb_result["blocked_order_id"], ""],
                    dynamic_type_absorb_blocked_candidate_score=[absorb_result["blocked_candidate_score"], 0.0],
                    dynamic_type_absorb_candidate_available=[absorb_result["dynamic_candidate_available"], False],
                    dynamic_type_absorb_candidate_move_id=[absorb_result["dynamic_candidate_move_id"], ""],
                    dynamic_type_absorb_candidate_declared_type=[absorb_result["dynamic_candidate_declared_type"], ""],
                    dynamic_type_absorb_candidate_effective_type=[absorb_result["dynamic_candidate_effective_type"], ""],
                    dynamic_type_absorb_candidate_form=[absorb_result["dynamic_candidate_form"], ""],
                    dynamic_type_absorb_candidate_source=[absorb_result["dynamic_candidate_source"], ""],
                    dynamic_type_absorb_candidate_target_table=[absorb_result["dynamic_candidate_target_table"], []],
                )
                logger.save_battle(battle_tag="t", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        table = s0["dynamic_type_absorb_candidate_target_table"]
        self.assertEqual(len(table), 1)
        row = table[0]
        self.assertEqual(row["move_id"], "aurawheel")
        self.assertEqual(row["effective_type"], "DARK")
        self.assertEqual(row["form"], "morpekohangry")
        self.assertEqual(row["target_known_ability"], "voltabsorb")
        self.assertFalse(row["ability_blocked"])
        self.assertTrue(row["selected"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_target_table_hangry_candidate_knock_off_selected(self):
        aw_move = _make_move("aurawheel","ELECTRIC")
        ko_move = _make_move("knockoff","DARK")
        aw_order = _make_order(aw_move, 1)
        ko_order = _make_order(ko_move, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        call_count = [0]
        def _dynamic_side_effect(move, attacker, battle):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"declared_type":"ELECTRIC","effective_type":"DARK",
                        "source":"dynamic_form:morpekohangry","dynamic_applied":True,
                        "observed_form":"morpekohangry"}
            return {"declared_type":"DARK","effective_type":"DARK",
                    "source":"static","dynamic_applied":False,"observed_form":""}
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       side_effect=_dynamic_side_effect):
                r = classify_dynamic_type_absorb_candidates(
                    [aw_order, ko_order], ko_order, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(aw_order): 80, id(ko_order): 100})
        self.assertTrue(r["dynamic_candidate_available"])
        table = r["dynamic_candidate_target_table"]
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["move_id"], "aurawheel")
        self.assertFalse(table[0]["selected"])
        self.assertFalse(table[0]["ability_blocked"])

    def test_target_table_two_targets_one_volt_absorb(self):
        aw = _make_move("aurawheel","ELECTRIC")
        bc1 = _make_order(aw, 1)
        bc2 = _make_order(aw, 2)
        t1 = MockPokemon("thundurus"); t1.species = "thundurus"
        t2 = MockPokemon("garchomp"); t2.species = "garchomp"
        def _ability_side_effect(target, battle):
            if target is t1:
                return "voltabsorb"
            return None
        with patch("bot_doubles_damage_aware.get_known_ability", side_effect=_ability_side_effect):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                r = classify_dynamic_type_absorb_candidates(
                    [bc1, bc2], bc1, MockPokemon("morpeko"),
                    [t1, t2], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc1): 50, id(bc2): 50})
        table = r["dynamic_candidate_target_table"]
        self.assertEqual(len(table), 2)
        pos1 = [r for r in table if r["target_position"] == 1][0]
        pos2 = [r for r in table if r["target_position"] == 2][0]
        self.assertEqual(pos1["target_known_ability"], "voltabsorb")
        self.assertTrue(pos1["ability_blocked"])
        self.assertEqual(pos2["target_known_ability"], "")
        self.assertFalse(pos2["ability_blocked"])
        shutil.rmtree("/tmp/_dt_test_noop", ignore_errors=True)

    def test_target_table_duplicate_orders_dedup(self):
        aw = _make_move("aurawheel","ELECTRIC")
        bc1 = _make_order(aw, 1)
        bc2 = _make_order(aw, 1)
        bc3 = _make_order(aw, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                r = classify_dynamic_type_absorb_candidates(
                    [bc1, bc2, bc3], bc1, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc1): 30, id(bc2): 40, id(bc3): 50})
        table = r["dynamic_candidate_target_table"]
        self.assertEqual(len(table), 1)

    def test_target_table_slot_isolation(self):
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        self._log_blocked_selected(logger, fp)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        s1 = r["audit_turns"][0]["slot_1"]
        self.assertGreater(len(s0.get("dynamic_type_absorb_candidate_target_table", [])), 0)
        self.assertEqual(len(s1.get("dynamic_type_absorb_candidate_target_table", [])), 0)
        shutil.rmtree(tmp, ignore_errors=True)

    def _make_slot_dict(self, **overrides):
        """Build a minimal battle + slot dict for log_turn_decision slot-1 guard tests."""
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        attacker = MockPokemon("morpeko")
        target = MockPokemon("thundurus"); target.species = "thundurus"
        ally = MockPokemon("b")
        b = MagicMock(); b.turn = 1; b.battle_tag = "guardbt"
        b.active_pokemon = [attacker, ally]
        b.opponent_active_pokemon = [target, None]; b.fields = []
        b.available_moves = [[], []]; b.available_switches = [[]]; b.force_switch = [False, False]
        b.side_conditions = {}; b.opponent_side_conditions = {}; b.weather = None
        aw_move = _make_move("aurawheel", "ELECTRIC")
        slot0 = _make_order(aw_move, 1)
        slot1 = _make_order(_make_move("thunderbolt", "ELECTRIC"), 2)
        jo = self._make_joint(slot0, slot1)
        return b, jo

    def _run_slot1_guard(self, **slot_kw):
        """Call log_turn_decision with caller-chosen dynamic_type_absorb_* kwargs
        and return the parsed slot_1 dict from the saved JSONL."""
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        b, jo = self._make_slot_dict()
        logger.log_turn_decision(
            battle_tag="guardbt", turn=1, battle=b,
            selected_joint_order="/choose move aurawheel|move thunderbolt",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move aurawheel", "move thunderbolt"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type_source=["static", "static"],
            dynamic_move_type_applied=[True, False],
            dynamic_move_type_form=["morpeko", ""],
            **slot_kw,
        )
        logger.save_battle(battle_tag="guardbt", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        shutil.rmtree(tmp, ignore_errors=True)
        return r["audit_turns"][0]["slot_1"]

    def _DT_FIELDS_BOOL(self):
        return [
            "dynamic_type_absorb_candidate_blocked",
            "dynamic_type_absorb_selected",
            "dynamic_type_absorb_avoided",
            "dynamic_type_absorb_candidate_available",
        ]

    def _DT_FIELDS_STR(self):
        return [
            "dynamic_type_absorb_reason",
            "dynamic_type_absorb_target_species",
            "dynamic_type_absorb_target_ability",
            "dynamic_type_absorb_blocked_move_id",
            "dynamic_type_absorb_candidate_move_id",
            "dynamic_type_absorb_candidate_declared_type",
            "dynamic_type_absorb_candidate_effective_type",
            "dynamic_type_absorb_candidate_form",
            "dynamic_type_absorb_candidate_source",
        ]

    def _DT_FIELDS_FLOAT(self):
        return ["dynamic_type_absorb_blocked_candidate_score"]

    def _DT_FIELDS_LIST(self):
        return ["dynamic_type_absorb_candidate_target_table"]

    def test_slot1_none_inputs_return_defaults(self):
        s1 = self._run_slot1_guard(
            dynamic_type_absorb_candidate_blocked=None,
            dynamic_type_absorb_selected=None,
            dynamic_type_absorb_avoided=None,
            dynamic_type_absorb_reason=None,
            dynamic_type_absorb_target_species=None,
            dynamic_type_absorb_target_ability=None,
            dynamic_type_absorb_blocked_move_id=None,
            dynamic_type_absorb_blocked_candidate_score=None,
            dynamic_type_absorb_candidate_available=None,
            dynamic_type_absorb_candidate_move_id=None,
            dynamic_type_absorb_candidate_declared_type=None,
            dynamic_type_absorb_candidate_effective_type=None,
            dynamic_type_absorb_candidate_form=None,
            dynamic_type_absorb_candidate_source=None,
            dynamic_type_absorb_candidate_target_table=None,
        )
        for f in self._DT_FIELDS_BOOL():
            self.assertFalse(s1[f], f)
        for f in self._DT_FIELDS_STR():
            self.assertEqual(s1[f], "", f)
        for f in self._DT_FIELDS_FLOAT():
            self.assertEqual(s1[f], 0.0, f)
        for f in self._DT_FIELDS_LIST():
            self.assertEqual(s1[f], [], f)

    def test_slot1_empty_lists_return_defaults(self):
        s1 = self._run_slot1_guard(
            dynamic_type_absorb_candidate_blocked=[],
            dynamic_type_absorb_selected=[],
            dynamic_type_absorb_avoided=[],
            dynamic_type_absorb_reason=[],
            dynamic_type_absorb_target_species=[],
            dynamic_type_absorb_target_ability=[],
            dynamic_type_absorb_blocked_move_id=[],
            dynamic_type_absorb_blocked_candidate_score=[],
            dynamic_type_absorb_candidate_available=[],
            dynamic_type_absorb_candidate_move_id=[],
            dynamic_type_absorb_candidate_declared_type=[],
            dynamic_type_absorb_candidate_effective_type=[],
            dynamic_type_absorb_candidate_form=[],
            dynamic_type_absorb_candidate_source=[],
            dynamic_type_absorb_candidate_target_table=[],
        )
        for f in self._DT_FIELDS_BOOL():
            self.assertFalse(s1[f], f)
        for f in self._DT_FIELDS_STR():
            self.assertEqual(s1[f], "", f)
        for f in self._DT_FIELDS_FLOAT():
            self.assertEqual(s1[f], 0.0, f)
        for f in self._DT_FIELDS_LIST():
            self.assertEqual(s1[f], [], f)

    def test_slot1_one_element_lists_return_defaults(self):
        s1 = self._run_slot1_guard(
            dynamic_type_absorb_candidate_blocked=[True],
            dynamic_type_absorb_selected=[True],
            dynamic_type_absorb_avoided=[True],
            dynamic_type_absorb_reason=["only_slot0"],
            dynamic_type_absorb_target_species=["thundurus"],
            dynamic_type_absorb_target_ability=["voltabsorb"],
            dynamic_type_absorb_blocked_move_id=["aurawheel"],
            dynamic_type_absorb_blocked_candidate_score=[42.0],
            dynamic_type_absorb_candidate_available=[True],
            dynamic_type_absorb_candidate_move_id=["aurawheel"],
            dynamic_type_absorb_candidate_declared_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_effective_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_form=["morpeko"],
            dynamic_type_absorb_candidate_source=["static"],
            dynamic_type_absorb_candidate_target_table=[{"move_id": "aurawheel"}],
        )
        for f in self._DT_FIELDS_BOOL():
            self.assertFalse(s1[f], f)
        for f in self._DT_FIELDS_STR():
            self.assertEqual(s1[f], "", f)
        for f in self._DT_FIELDS_FLOAT():
            self.assertEqual(s1[f], 0.0, f)
        for f in self._DT_FIELDS_LIST():
            self.assertEqual(s1[f], [], f)

    def test_slot1_two_element_lists_use_index_one(self):
        s1 = self._run_slot1_guard(
            dynamic_type_absorb_candidate_blocked=[False, True],
            dynamic_type_absorb_selected=[False, True],
            dynamic_type_absorb_avoided=[False, True],
            dynamic_type_absorb_reason=["", "electric_into_voltabsorb"],
            dynamic_type_absorb_target_species=["", "thundurus"],
            dynamic_type_absorb_target_ability=["", "voltabsorb"],
            dynamic_type_absorb_blocked_move_id=["", "aurawheel"],
            dynamic_type_absorb_blocked_candidate_score=[0.0, 77.5],
            dynamic_type_absorb_candidate_available=[False, True],
            dynamic_type_absorb_candidate_move_id=["", "aurawheel"],
            dynamic_type_absorb_candidate_declared_type=["", "ELECTRIC"],
            dynamic_type_absorb_candidate_effective_type=["", "ELECTRIC"],
            dynamic_type_absorb_candidate_form=["", "morpeko"],
            dynamic_type_absorb_candidate_source=["", "static"],
            dynamic_type_absorb_candidate_target_table=[[], [{"move_id": "aurawheel", "target_position": 2}]],
        )
        for f in self._DT_FIELDS_BOOL():
            self.assertTrue(s1[f], f)
        self.assertEqual(s1["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertEqual(s1["dynamic_type_absorb_target_species"], "thundurus")
        self.assertEqual(s1["dynamic_type_absorb_target_ability"], "voltabsorb")
        self.assertEqual(s1["dynamic_type_absorb_blocked_move_id"], "aurawheel")
        self.assertEqual(s1["dynamic_type_absorb_blocked_candidate_score"], 77.5)
        self.assertEqual(s1["dynamic_type_absorb_candidate_move_id"], "aurawheel")
        self.assertEqual(s1["dynamic_type_absorb_candidate_declared_type"], "ELECTRIC")
        self.assertEqual(s1["dynamic_type_absorb_candidate_effective_type"], "ELECTRIC")
        self.assertEqual(s1["dynamic_type_absorb_candidate_form"], "morpeko")
        self.assertEqual(s1["dynamic_type_absorb_candidate_source"], "static")
        self.assertEqual(len(s1["dynamic_type_absorb_candidate_target_table"]), 1)
        self.assertEqual(s1["dynamic_type_absorb_candidate_target_table"][0]["target_position"], 2)

    def test_slot0_one_element_lists_use_index_zero(self):
        """Slot 0 must still read [0] from a one-element list."""
        s1 = self._run_slot1_guard(
            dynamic_type_absorb_candidate_blocked=[True],
            dynamic_type_absorb_selected=[True],
            dynamic_type_absorb_avoided=[True],
            dynamic_type_absorb_reason=["electric_into_voltabsorb"],
            dynamic_type_absorb_target_species=["thundurus"],
            dynamic_type_absorb_target_ability=["voltabsorb"],
            dynamic_type_absorb_blocked_move_id=["aurawheel"],
            dynamic_type_absorb_blocked_candidate_score=[99.0],
            dynamic_type_absorb_candidate_available=[True],
            dynamic_type_absorb_candidate_move_id=["aurawheel"],
            dynamic_type_absorb_candidate_declared_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_effective_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_form=["morpeko"],
            dynamic_type_absorb_candidate_source=["static"],
            dynamic_type_absorb_candidate_target_table=[[{"move_id": "aurawheel", "target_position": 1}]],
        )
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "s0.jsonl")
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        b, jo = self._make_slot_dict()
        logger.log_turn_decision(
            battle_tag="s0bt", turn=1, battle=b,
            selected_joint_order="/choose move aurawheel|move thunderbolt",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move aurawheel", "move thunderbolt"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type_source=["static", "static"],
            dynamic_move_type_applied=[True, False],
            dynamic_move_type_form=["morpeko", ""],
            dynamic_type_absorb_candidate_blocked=[True],
            dynamic_type_absorb_selected=[True],
            dynamic_type_absorb_avoided=[True],
            dynamic_type_absorb_reason=["electric_into_voltabsorb"],
            dynamic_type_absorb_target_species=["thundurus"],
            dynamic_type_absorb_target_ability=["voltabsorb"],
            dynamic_type_absorb_blocked_move_id=["aurawheel"],
            dynamic_type_absorb_blocked_candidate_score=[99.0],
            dynamic_type_absorb_candidate_available=[True],
            dynamic_type_absorb_candidate_move_id=["aurawheel"],
            dynamic_type_absorb_candidate_declared_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_effective_type=["ELECTRIC"],
            dynamic_type_absorb_candidate_form=["morpeko"],
            dynamic_type_absorb_candidate_source=["static"],
            dynamic_type_absorb_candidate_target_table=[[{"move_id": "aurawheel", "target_position": 1}]],
        )
        logger.save_battle(battle_tag="s0bt", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        shutil.rmtree(tmp, ignore_errors=True)
        for f in self._DT_FIELDS_BOOL():
            self.assertTrue(s0[f], f)
        self.assertEqual(s0["dynamic_type_absorb_reason"], "electric_into_voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_target_species"], "thundurus")
        self.assertEqual(s0["dynamic_type_absorb_target_ability"], "voltabsorb")
        self.assertEqual(s0["dynamic_type_absorb_blocked_move_id"], "aurawheel")
        self.assertEqual(s0["dynamic_type_absorb_blocked_candidate_score"], 99.0)
        self.assertEqual(s0["dynamic_type_absorb_candidate_move_id"], "aurawheel")
        self.assertEqual(s0["dynamic_type_absorb_candidate_declared_type"], "ELECTRIC")
        self.assertEqual(s0["dynamic_type_absorb_candidate_effective_type"], "ELECTRIC")
        self.assertEqual(s0["dynamic_type_absorb_candidate_form"], "morpeko")
        self.assertEqual(s0["dynamic_type_absorb_candidate_source"], "static")
        self.assertEqual(len(s0["dynamic_type_absorb_candidate_target_table"]), 1)
        self.assertEqual(s0["dynamic_type_absorb_candidate_target_table"][0]["target_position"], 1)

    def test_target_table_slot_isolation_with_two_element_lists(self):
        """Slot 1's target_table must not leak from slot 0; slot 0 must not leak from slot 1."""
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "iso.jsonl")
        logger = DoublesDecisionAuditLogger(filepath=fp, reset=True)
        b, jo = self._make_slot_dict()
        slot0_row = {"move_id": "aurawheel", "target_position": 1, "form": "morpeko"}
        slot1_row = {"move_id": "aurawheel", "target_position": 2, "form": "morpekohangry"}
        logger.log_turn_decision(
            battle_tag="isobt", turn=1, battle=b,
            selected_joint_order="/choose move aurawheel|move thunderbolt",
            selected_score=100, scored_joint_orders=[(jo, 100, 50, 50)],
            expected_damages=[50, 50], expected_kos=[False, False],
            target_hps=[1, 1],
            overkill_triggered=False, focus_fire_triggered=False,
            ally_hit_penalty_triggered=False,
            spread_available=[False, False], best_spread_score=[0, 0],
            best_ko_score=[0, 0],
            low_hp_opponent_existed=False, low_hp_opponent_targeted=False,
            slot_actions=["move aurawheel", "move thunderbolt"],
            slot_action_types=[{}, {}],
            target_species=["thundurus", ""],
            declared_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type=["ELECTRIC", "ELECTRIC"],
            effective_move_type_source=["static", "static"],
            dynamic_move_type_applied=[True, True],
            dynamic_move_type_form=["morpeko", "morpekohangry"],
            dynamic_type_absorb_candidate_blocked=[False, False],
            dynamic_type_absorb_selected=[False, False],
            dynamic_type_absorb_avoided=[False, False],
            dynamic_type_absorb_reason=["", ""],
            dynamic_type_absorb_target_species=["", ""],
            dynamic_type_absorb_target_ability=["", ""],
            dynamic_type_absorb_blocked_move_id=["", ""],
            dynamic_type_absorb_blocked_candidate_score=[0.0, 0.0],
            dynamic_type_absorb_candidate_available=[True, True],
            dynamic_type_absorb_candidate_move_id=["aurawheel", "aurawheel"],
            dynamic_type_absorb_candidate_declared_type=["ELECTRIC", "ELECTRIC"],
            dynamic_type_absorb_candidate_effective_type=["ELECTRIC", "DARK"],
            dynamic_type_absorb_candidate_form=["morpeko", "morpekohangry"],
            dynamic_type_absorb_candidate_source=["static", "dynamic_form:morpekohangry"],
            dynamic_type_absorb_candidate_target_table=[[slot0_row], [slot1_row]],
        )
        logger.save_battle(battle_tag="isobt", winner="test", battle=b)
        with open(fp) as f:
            r = json.loads(f.readline())
        s0 = r["audit_turns"][0]["slot_0"]
        s1 = r["audit_turns"][0]["slot_1"]
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(s0["dynamic_type_absorb_candidate_target_table"]), 1)
        self.assertEqual(len(s1["dynamic_type_absorb_candidate_target_table"]), 1)
        self.assertEqual(s0["dynamic_type_absorb_candidate_target_table"][0]["form"], "morpeko")
        self.assertEqual(s0["dynamic_type_absorb_candidate_target_table"][0]["target_position"], 1)
        self.assertEqual(s1["dynamic_type_absorb_candidate_target_table"][0]["form"], "morpekohangry")
        self.assertEqual(s1["dynamic_type_absorb_candidate_target_table"][0]["target_position"], 2)
        self.assertEqual(s0["dynamic_type_absorb_candidate_form"], "morpeko")
        self.assertEqual(s1["dynamic_type_absorb_candidate_form"], "morpekohangry")
        self.assertNotIn(slot1_row, s0["dynamic_type_absorb_candidate_target_table"])
        self.assertNotIn(slot0_row, s1["dynamic_type_absorb_candidate_target_table"])

    def _setup_arm(self, arm_id, tmp, **slot_kw):
        rec = {
            "battle_tag": f"{arm_id}bt",
            "won": True,
            "benchmark_arm": arm_id,
            "audit_turns": [{"slot_0": dict(slot_kw)}],
        }
        return rec

    def _write_jsonl(self, fp, records):
        with open(fp, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_jsonl_validation_valid_passes(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{"battle_tag": "bt1", "won": True, "benchmark_arm": "A", "audit_turns": []}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertEqual(errors, [])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_wrong_arm(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{"battle_tag": "bt1", "won": True, "benchmark_arm": "B", "audit_turns": []}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("benchmark_arm=B expected=A" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_missing_arm(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{"battle_tag": "bt1", "won": True, "audit_turns": []}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("missing benchmark_arm" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_wrong_record_count(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{"battle_tag": "bt1", "won": True, "benchmark_arm": "A", "audit_turns": []}])
        errors = validate_jsonl(fp, 5, "A")
        self.assertTrue(any("expected 5" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_duplicate_tags(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [
            {"battle_tag": "bt1", "won": True, "benchmark_arm": "A", "audit_turns": []},
            {"battle_tag": "bt1", "won": False, "benchmark_arm": "A", "audit_turns": []}])
        errors = validate_jsonl(fp, 2, "A")
        self.assertTrue(any("duplicate" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_non_bool_outcome(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{"battle_tag": "bt1", "won": 1, "benchmark_arm": "A", "audit_turns": []}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("not bool" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_malformed(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write("{bad json\n")
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("malformed" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_accounting_failure(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_blocked": True,
                "dynamic_type_absorb_candidate_target_table": [],
                "dynamic_type_absorb_selected": False,
                "dynamic_type_absorb_avoided": False}}]}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("accounting failed" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jsonl_validation_mutual_exclusion(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_jsonl
        import tempfile, os, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        self._write_jsonl(fp, [{
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_target_table": [],
                "dynamic_type_absorb_selected": True,
                "dynamic_type_absorb_avoided": True}}]}])
        errors = validate_jsonl(fp, 1, "A")
        self.assertTrue(any("both selected and avoided" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_valid_passes(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"100","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertEqual(errors, [])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_status_error(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"error","planned":"100","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("status='error'" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_non_integer_planned(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"abc","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("non-integer" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_planned_mismatch(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"200","finished":"200","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("planned=200" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_missing_arm(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"100","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100, "B": 50})
        self.assertTrue(any("missing expected arm" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_unknown_arm(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"X","status":"ok","planned":"100","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("not in expected arms" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_duplicate_arm(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"100","finished":"100","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"50","finished":"50","accounting_invariant_pass":"True","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("duplicate arm" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_csv_validation_invariant_false(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import validate_csv
        import tempfile, os, csv, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.csv")
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["benchmark_arm","status","planned","finished","accounting_invariant_pass","accounting_mutual_exclusion_pass"])
            w.writeheader()
            w.writerow({"benchmark_arm":"A","status":"ok","planned":"100","finished":"100","accounting_invariant_pass":"False","accounting_mutual_exclusion_pass":"True"})
        errors = validate_csv(fp, {"A": 100})
        self.assertTrue(any("accounting_invariant_pass='False'" in e for e in errors))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_two_target_rows_one_opportunity(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {"dynamic_type_absorb_candidate_target_table": [
                {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1},
                {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":2},
            ]}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["dynamic_candidate_opportunity_turns"], 1)
        self.assertEqual(m["full_belly_candidate_opportunities"], 1)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_two_targets_one_volt_absorb(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_blocked": True,
                "dynamic_type_absorb_selected": False,
                "dynamic_type_absorb_avoided": False,
                "dynamic_type_absorb_candidate_target_table": [
                    {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"voltabsorb","ability_blocked":True,"selected":False,"target_position":1},
                    {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":2},
                ]}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["full_belly_known_volt_absorb_opportunities"], 1)
        self.assertEqual(m["full_belly_known_volt_absorb_blocked"], 1)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_hangry_known_volt_absorb(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {"dynamic_type_absorb_candidate_target_table": [
                {"move_id":"aurawheel","form":"morpekohangry","effective_type":"DARK","target_known_ability":"voltabsorb","ability_blocked":False,"selected":True,"target_position":1},
            ]}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["hangry_candidate_opportunities"], 1)
        self.assertEqual(m["hangry_known_volt_absorb_opportunities"], 1)
        self.assertEqual(m["blocked_total"], 0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_hangry_selected_legal(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {"dynamic_type_absorb_candidate_target_table": [
                {"move_id":"aurawheel","form":"morpekohangry","effective_type":"DARK","target_known_ability":"voltabsorb","ability_blocked":False,"selected":True,"target_position":1},
            ]}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["hangry_aurawheel_selected"], 1)
        self.assertEqual(m["hangry_known_volt_absorb_selected_legal"], 1)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_duplicate_variants_one_opportunity(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {"dynamic_type_absorb_candidate_target_table": [
                {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1},
            ]}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["dynamic_candidate_opportunity_turns"], 1)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_two_slots_two_opportunities(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{
                "slot_0": {"dynamic_type_absorb_candidate_target_table": [
                    {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1}]},
                "slot_1": {"dynamic_type_absorb_candidate_target_table": [
                    {"move_id":"aurawheel","form":"morpekohangry","effective_type":"DARK","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1}]},
            }]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["dynamic_candidate_opportunity_turns"], 2)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_two_turns_two_opportunities(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [
                {"turn": 1, "slot_0": {"dynamic_type_absorb_candidate_target_table": [
                    {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1}]}},
                {"turn": 2, "slot_0": {"dynamic_type_absorb_candidate_target_table": [
                    {"move_id":"aurawheel","form":"morpeko","effective_type":"ELECTRIC","target_known_ability":"","ability_blocked":False,"selected":False,"target_position":1}]}},
            ]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["dynamic_candidate_opportunity_turns"], 2)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_ordinary_spread_no_dynamic_table(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_target_table": [],
                "action_types": {"spread": True}}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertEqual(m["spread_count"], 1)
        self.assertEqual(m["dynamic_candidate_opportunity_turns"], 0)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_broken_accounting_fail(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_blocked": True,
                "dynamic_type_absorb_candidate_target_table": [],
                "dynamic_type_absorb_selected": False,
                "dynamic_type_absorb_avoided": False}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertFalse(m["accounting_invariant_pass"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_metric_selected_and_avoided_mutual_exclusion_fail(self):
        from bot_doubles_dynamic_move_type_safety_benchmark import _count_dynamic_metrics
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {
            "battle_tag": "bt1", "won": True, "benchmark_arm": "A",
            "audit_turns": [{"slot_0": {
                "dynamic_type_absorb_candidate_target_table": [],
                "dynamic_type_absorb_selected": True,
                "dynamic_type_absorb_avoided": True}}]}
        with open(fp, "w") as f: f.write(json.dumps(rec) + "\n")
        m = _count_dynamic_metrics(fp)
        self.assertFalse(m["accounting_mutual_exclusion_pass"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_artifact_tag_exits_nonzero(self):
        import subprocess
        result = subprocess.run(
            ["./venv/bin/python", "bot_doubles_dynamic_move_type_safety_benchmark.py"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__) or ".")
        self.assertNotEqual(result.returncode, 0)

    def test_existing_artifacts_without_overwrite_exits_nonzero(self):
        import subprocess
        result = subprocess.run(
            ["./venv/bin/python", "bot_doubles_dynamic_move_type_safety_benchmark.py",
             "--artifact-tag", "phase637m_dynamic_aurawheel_smoke"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__) or ".")
        self.assertNotEqual(result.returncode, 0)

    def test_duplicate_orders_second_selected_merges_correctly(self):
        aw = _make_move("aurawheel","ELECTRIC")
        bc1 = _make_order(aw, 1)
        bc2 = _make_order(aw, 1)
        t = MockPokemon("thundurus"); t.species = "thundurus"
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_effective_move_type",
                       return_value={"declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                                      "source":"static","dynamic_applied":True,"observed_form":"morpeko"}):
                r = classify_dynamic_type_absorb_candidates(
                    [bc1, bc2], bc2, MockPokemon("morpeko"),
                    [t, None], MagicMock(battle_tag="t"), _absorb_config(),
                    {id(bc1): 30, id(bc2): 80})
        table = r["dynamic_candidate_target_table"]
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["selected"])
        self.assertEqual(table[0]["candidate_score"], 80)


class TestConfig(unittest.TestCase):
    def test_awareness_disabled(self):
        self.assertFalse(DoublesDamageAwareConfig().enable_ability_awareness)
    def test_no_hidden_inference(self):
        import inspect; s = inspect.getsource(get_effective_move_type)
        self.assertNotIn("possible_abilities", s)
    def test_default_scoring_unchanged(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.enable_ability_hard_safety_only)


class TestRegressionSafety(unittest.TestCase):
    def test_full_belly_blocked_unknown_ability_no_block(self):
        with patch("bot_doubles_damage_aware.get_known_ability", return_value=None):
            self.assertFalse(ability_hard_blocks_move(_make_move("aurawheel","ELECTRIC"),MockPokemon("morpeko"),MockPokemon("t"))[0])
    def test_grass_sapsipper_still_works(self):
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="sapsipper"):
            self.assertTrue(ability_hard_blocks_move(_make_move("leafblade","GRASS"),MockPokemon("s"),MockPokemon("a"))[0])
    def test_fire_wellbakedbody_still_works(self):
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="wellbakedbody"):
            self.assertTrue(ability_hard_blocks_move(_make_move("fireblast","FIRE"),MockPokemon("c"),MockPokemon("d"))[0])
    def test_replay_scan_malformed_events_ignored(self):
        from poke_env.battle.double_battle import DoubleBattle
        from poke_env.battle.pokemon import Pokemon
        from poke_env.battle.pokemon_type import PokemonType
        b = DoubleBattle.__new__(DoubleBattle)
        for a in ('_battle_tag','_format','_replay_data','_fields','_weather','_side_conditions','_opponent_side_conditions','_player_role','_opponent_role','_username','_opponent_username','_trick_room','_available_moves','_available_switches','_force_switch','_active_pokemon','_opponent_active_pokemon'):
            setattr(b, a, None)
        b._battle_tag='re'; b._format='gen9randomdoublesbattle'; b._replay_data=[[]]; b._fields={}
        b._available_moves=[[],[]]; b._available_switches=[[],[]]; b._force_switch=[False,False]
        clear_observed_form_state("re")
        _scan_replay_for_form_changes(b)
        clear_observed_form_state("re")
    def test_cleanup_removes_form_state(self):
        clear_observed_form_state("cleanme")
        record_observed_form_change("cleanme","p1a: X","morpekohangry",pokemon=MockPokemon("x"))
        clear_observed_form_state("cleanme")
        b = MagicMock(battle_tag="cleanme")
        self.assertIsNone(get_observed_form(b, MockPokemon("x")))
    def test_no_stale_form_across_battles(self):
        clear_observed_form_state("b1"); clear_observed_form_state("b2")
        p = MockPokemon("morpeko", base_species="morpeko")
        record_observed_form_change("b1","p1a: Morpeko","morpekohangry",pokemon=p)
        b2 = MagicMock(battle_tag="b2")
        self.assertIsNone(get_observed_form(b2, p))
        clear_observed_form_state("b1"); clear_observed_form_state("b2")


if __name__ == "__main__":
    unittest.main()
