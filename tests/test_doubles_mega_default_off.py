"""Phase BI-3A: Mega Evolution legal-order generation, default OFF.

These tests prove that:
- ``DoublesDamageAwareConfig.enable_mega_evolution`` defaults to False.
- When the flag is OFF, ``_augment_valid_orders_with_mega`` returns
  the input list byte-for-byte identical.
- When the flag is ON, parallel Mega variants are appended per slot
  for slots whose ``battle.can_mega_evolve[slot_idx]`` is True.
- The Mega variant has ``mega=True`` and the same move id and target
  as the plain order.
- The plain order is still present when a Mega variant is generated.
- V4a action keys distinguish plain (mechanic="") from Mega
  (mechanic="mega") orders.
- V2l.1 keys remain 3-tuples (no mechanic flag) for backward
  compatibility.
- Runtime parity for default OFF remains unchanged.
- No production import of ``poke_env_test_cleanup``.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _MockMove:
    """Minimal Move stand-in with the attribute names
    touched by the helpers.
    """

    def __init__(self, move_id="tackle"):
        self.id = move_id


class _MockBattle:
    """Minimal Battle stand-in for Mega availability."""

    def __init__(
        self,
        can_mega_evolve_0=False,
        can_mega_evolve_1=False,
        species_0="charizard",
        species_1="charizard",
    ):
        # Phase BI-3G: include species for the Mega-capable
        # allowlist guard. Default to "charizard" so existing
        # tests still exercise the Mega-positive path.
        self.can_mega_evolve = [can_mega_evolve_0, can_mega_evolve_1]
        self.active_pokemon = [
            _MockPokemon(species_0),
            _MockPokemon(species_1),
        ]


class _MockPokemon:
    """Minimal Pokemon stand-in for species lookup."""

    def __init__(self, species="pikachu"):
        self.species = species


def _plain(move_id="tackle", move_target=0):
    from poke_env.battle.double_battle import SingleBattleOrder
    return SingleBattleOrder(
        _MockMove(move_id), move_target=move_target
    )


class TestConfigFlag(unittest.TestCase):
    def test_default_is_false(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_mega_evolution)
        self.assertIsInstance(cfg.enable_mega_evolution, bool)


class TestCanGenerateMegaOrder(unittest.TestCase):
    def test_returns_true_when_can_mega_and_plain_move(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain()
        self.assertTrue(
            _can_generate_mega_order_for_slot(battle, 0, plain)
        )

    def test_returns_false_when_cannot_mega(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=False)
        plain = _plain()
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, plain)
        )

    def test_returns_false_for_switch_order(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        from poke_env.battle.double_battle import SingleBattleOrder

        battle = _MockBattle(can_mega_evolve_0=True)

        class _MockPokemon:
            species = "pikachu"

        switch_order = SingleBattleOrder(_MockPokemon())
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, switch_order)
        )

    def test_returns_false_when_order_already_mega(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        from poke_env.battle.double_battle import SingleBattleOrder
        battle = _MockBattle(can_mega_evolve_0=True)
        mega = SingleBattleOrder(
            _MockMove(), move_target=0, mega=True
        )
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, mega)
        )

    def test_returns_false_when_order_is_z_move(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        from poke_env.battle.double_battle import SingleBattleOrder
        battle = _MockBattle(can_mega_evolve_0=True)
        z_move = SingleBattleOrder(
            _MockMove(), move_target=0, z_move=True
        )
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, z_move)
        )

    def test_returns_false_when_order_is_dynamax(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        from poke_env.battle.double_battle import SingleBattleOrder
        battle = _MockBattle(can_mega_evolve_0=True)
        dynamax = SingleBattleOrder(
            _MockMove(), move_target=0, dynamax=True
        )
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, dynamax)
        )

    def test_returns_false_when_order_is_terastallize(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        from poke_env.battle.double_battle import SingleBattleOrder
        battle = _MockBattle(can_mega_evolve_0=True)
        tera = SingleBattleOrder(
            _MockMove(), move_target=0, terastallize=True
        )
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, tera)
        )

    def test_returns_false_for_none_order(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 0, None)
        )

    def test_returns_false_for_slot_out_of_range(self):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain()
        self.assertFalse(
            _can_generate_mega_order_for_slot(battle, 5, plain)
        )


class TestBuildMegaLegalOrdersForSlot(unittest.TestCase):
    def test_appends_mega_variant_when_eligible(self):
        from doubles_engine.action_keys import (
            _build_mega_legal_orders_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain()
        out = _build_mega_legal_orders_for_slot(battle, 0, [plain])
        self.assertEqual(len(out), 2)
        # Plain order first.
        self.assertFalse(out[0].mega)
        self.assertEqual(out[0].order.id, "tackle")
        # Mega variant immediately after.
        self.assertTrue(out[1].mega)
        self.assertEqual(out[1].order.id, "tackle")
        self.assertEqual(out[1].move_target, 0)

    def test_no_mega_variant_when_not_eligible(self):
        from doubles_engine.action_keys import (
            _build_mega_legal_orders_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=False)
        plain = _plain()
        out = _build_mega_legal_orders_for_slot(battle, 0, [plain])
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].mega)

    def test_preserves_ordering(self):
        """Plain order first, Mega variant adjacent."""
        from doubles_engine.action_keys import (
            _build_mega_legal_orders_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain1 = _plain("move1")
        plain2 = _plain("move2")
        out = _build_mega_legal_orders_for_slot(
            battle, 0, [plain1, plain2]
        )
        self.assertEqual(len(out), 4)
        self.assertFalse(out[0].mega)
        self.assertEqual(out[0].order.id, "move1")
        self.assertTrue(out[1].mega)
        self.assertEqual(out[1].order.id, "move1")
        self.assertFalse(out[2].mega)
        self.assertEqual(out[2].order.id, "move2")
        self.assertTrue(out[3].mega)
        self.assertEqual(out[3].order.id, "move2")

    def test_target_preserved_on_mega_variant(self):
        from doubles_engine.action_keys import (
            _build_mega_legal_orders_for_slot,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain(move_target=2)
        out = _build_mega_legal_orders_for_slot(battle, 0, [plain])
        self.assertEqual(out[1].move_target, 2)


class TestAugmentValidOrders(unittest.TestCase):
    def test_flag_off_returns_input_unchanged(self):
        """Default OFF: content preserved (BI-3G filter may
        strip Mega variants for non-Mega-capable species,
        but the mock input has no Mega variants, so the
        filtered output equals the input content).
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        battle = _MockBattle(
            can_mega_evolve_0=True, can_mega_evolve_1=True
        )
        plain0 = _plain()
        plain1 = _plain()
        valid_orders = [[plain0], [plain1]]

        class _Cfg:
            enable_mega_evolution = False

        out = _augment_valid_orders_with_mega(
            battle, valid_orders, _Cfg()
        )
        # Content equality (BI-3G always filters Mega
        # variants; the mock input has none).
        self.assertEqual(out[0], [plain0])
        self.assertEqual(out[1], [plain1])

    def test_flag_on_augments_slot_0_only(self):
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        battle = _MockBattle(
            can_mega_evolve_0=True, can_mega_evolve_1=False
        )
        plain0 = _plain()
        plain1 = _plain()
        valid_orders = [[plain0], [plain1]]

        class _Cfg:
            enable_mega_evolution = True

        out = _augment_valid_orders_with_mega(
            battle, valid_orders, _Cfg()
        )
        self.assertEqual(len(out[0]), 2)
        self.assertEqual(len(out[1]), 1)
        self.assertTrue(out[0][1].mega)
        self.assertFalse(out[1][0].mega)

    def test_flag_off_preserves_valid_orders_identity(self):
        """When flag is OFF, no Mega variants are added. 
        The BI-3G filter may strip Mega variants but the
        content of valid_orders (when no Mega variants are
        present) is preserved.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain()
        valid_orders = [[plain]]

        class _Cfg:
            enable_mega_evolution = False

        out = _augment_valid_orders_with_mega(
            battle, valid_orders, _Cfg()
        )
        self.assertIs(out[0][0], plain)
        self.assertIs(out[0][0].order, plain.order)

    def test_flag_off_with_none_config(self):
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        battle = _MockBattle(can_mega_evolve_0=True)
        plain = _plain()
        valid_orders = [[plain]]
        out = _augment_valid_orders_with_mega(battle, valid_orders, None)
        # BI-3G: content equality (not identity, since the
        # filter always copies).
        self.assertEqual(out[0], [plain])


class TestV4aKeyDistinguishes(unittest.TestCase):
    def test_v4a_key_differs_for_plain_vs_mega(self):
        from doubles_engine.action_keys import (
            _order_action_key_with_mechanic,
            _order_mechanic_label,
        )
        plain = _plain()
        from poke_env.battle.double_battle import SingleBattleOrder
        mega = SingleBattleOrder(
            _MockMove(), move_target=0, mega=True
        )
        plain_key = _order_action_key_with_mechanic(plain)
        mega_key = _order_action_key_with_mechanic(mega)
        self.assertEqual(plain_key[3], "")
        self.assertEqual(mega_key[3], "mega")
        self.assertEqual(plain_key[:3], mega_key[:3])
        self.assertEqual(_order_mechanic_label(plain), "")
        self.assertEqual(_order_mechanic_label(mega), "mega")


class TestV2l1BackwardCompatibility(unittest.TestCase):
    def test_v2l1_key_unchanged_for_plain_and_mega(self):
        """V2l.1 keys are 3-tuples (no mechanic flag).
        Plain and Mega orders collapse to the same V2l.1
        key — this is the documented backward-compatible
        behavior. V4a is the distinguishing layer.
        """
        from doubles_engine.action_keys import (
            _order_action_key,
        )
        plain = _plain()
        from poke_env.battle.double_battle import SingleBattleOrder
        mega = SingleBattleOrder(
            _MockMove(), move_target=0, mega=True
        )
        self.assertEqual(
            _order_action_key(plain),
            _order_action_key(mega),
        )


class TestMegaSpeciesGuard(unittest.TestCase):
    """Phase BI-3G: species allowlist guard.

    poke-env's ``battle.can_mega_evolve`` flag can be
    permissive in some formats. To prevent the bot from
    generating Mega variants for non-Mega-capable species
    (BI-3F-2 finding: pair 19 with Dragonite lead got a
    Mega selection), the helper checks the active Pokemon's
    base species against a conservative allowlist.
    """

    def _helper(self, battle, slot_idx, order):
        from doubles_engine.action_keys import (
            _can_generate_mega_order_for_slot,
        )
        return _can_generate_mega_order_for_slot(
            battle, slot_idx, order
        )

    def test_charizard_can_generate_mega_when_protocol_true(self):
        """Charizard is Mega-capable. With can_mega=True,
        the helper returns True.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        self.assertTrue(self._helper(battle, 0, _plain()))

    def test_dragonite_cannot_generate_mega_even_when_protocol_true(self):
        """Dragonite is NOT Mega-capable. Even with
        can_mega=True (BI-3F-2 finding), the helper returns
        False because dragonite is not in the allowlist.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="dragonite",
        )
        self.assertFalse(self._helper(battle, 0, _plain()))

    def test_incineroar_cannot_generate_mega_even_when_protocol_true(self):
        """Incineroar is NOT Mega-capable. Even with
        can_mega=True, the helper returns False.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="incineroar",
        )
        self.assertFalse(self._helper(battle, 0, _plain()))

    def test_protocol_flag_false_still_blocks_charizard(self):
        """Even with charizard (Mega-capable), the helper
        returns False when can_mega_evolve=False.
        """
        battle = _MockBattle(
            can_mega_evolve_0=False,
            species_0="charizard",
        )
        self.assertFalse(self._helper(battle, 0, _plain()))

    def test_charizard_mega_x_form_normalizes_to_base(self):
        """Species strings like 'Charizard-Mega-X' should
        normalize to 'charizard' and pass the guard.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="Charizard-Mega-X",
        )
        self.assertTrue(self._helper(battle, 0, _plain()))

    def test_charizard_concatenated_form_normalizes(self):
        """Species strings like 'charizardmegax' should
        normalize to 'charizard' and pass the guard.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizardmegax",
        )
        self.assertTrue(self._helper(battle, 0, _plain()))

    def test_garchomp_blocked_by_default(self):
        """Garchomp is not in the conservative allowlist
        (BI-3G explicitly excluded Mega Garchomp from the
        initial set). The helper returns False even with
        can_mega=True.
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="garchomp",
        )
        self.assertFalse(self._helper(battle, 0, _plain()))

    def test_aerodactyl_can_generate_mega(self):
        """Aerodactyl is Mega-capable (gen 1 Mega).
        """
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="aerodactyl",
        )
        self.assertTrue(self._helper(battle, 0, _plain()))

    def test_allowlist_size_and_basic_species(self):
        """Sanity check on the allowlist. Must include the
        common Mega starters and exclude the explicit
        non-Mega species (dragonite, incineroar).
        """
        from doubles_engine.action_keys import (
            MEGA_CAPABLE_SPECIES,
        )
        # At least 30 species (we ship ~44).
        self.assertGreaterEqual(len(MEGA_CAPABLE_SPECIES), 30)
        # Required Mega-capable species.
        for s in (
            "charizard", "venusaur", "blastoise", "gengar",
            "aerodactyl", "kangaskhan", "gyarados", "gardevoir",
            "scizor", "tyranitar", "blaziken", "swampert",
            "sceptile", "metagross", "salamence", "lucario",
            "rayquaza", "latias", "latios", "mewtwo",
        ):
            self.assertIn(s, MEGA_CAPABLE_SPECIES)
        # Required non-Mega species must NOT be in the allowlist.
        for s in ("dragonite", "incineroar"):
            self.assertNotIn(s, MEGA_CAPABLE_SPECIES)

    def test_normalize_handles_edge_cases(self):
        """Normalizer must handle None, empty, and form suffixes.
        """
        from doubles_engine.action_keys import (
            _normalize_species_for_mega,
        )
        self.assertEqual(
            _normalize_species_for_mega(None), ""
        )
        self.assertEqual(
            _normalize_species_for_mega(""), ""
        )
        self.assertEqual(
            _normalize_species_for_mega("Charizard-Mega-X"),
            "charizard",
        )
        self.assertEqual(
            _normalize_species_for_mega("charizardmegax"),
            "charizard",
        )
        # Non-Mega species stays as-is.
        self.assertEqual(
            _normalize_species_for_mega("dragonite"), "dragonite"
        )

    def test_v4a_key_behavior_unchanged_for_valid_mega_order(self):
        """When the helper says True (charizard + protocol
        True), the resulting V4a key has mechanic='mega'.
        """
        from doubles_engine.action_keys import (
            _order_action_key_with_mechanic,
        )
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        order = _plain()
        self.assertTrue(self._helper(battle, 0, order))
        # Build the Mega variant.
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        mega_order = SingleBattleOrder(
            order.order, move_target=order.move_target, mega=True
        )
        # V4a key distinguishes plain vs Mega via mechanic field.
        plain_key = _order_action_key_with_mechanic(order)
        mega_key = _order_action_key_with_mechanic(mega_order)
        self.assertEqual(plain_key[3], "")
        self.assertEqual(mega_key[3], "mega")

    def test_filter_strips_mega_for_non_mega_capable(self):
        """Phase BI-3G: poke-env's ``battle.valid_orders``
        may include Mega variants for non-Mega-capable species.
        The filter strips them.
        """
        from doubles_engine.action_keys import (
            _filter_non_mega_capable_orders,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "dragonpulse"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        # Dragonite with a Mega variant in valid_orders.
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="dragonite",
        )
        orders = [plain, mega]
        filtered = _filter_non_mega_capable_orders(battle, 0, orders)
        # Only plain remains; Mega was stripped.
        self.assertEqual(len(filtered), 1)
        self.assertFalse(filtered[0].mega)

    def test_filter_keeps_mega_for_mega_capable(self):
        """Charizard is Mega-capable. Filter is a no-op."""
        from doubles_engine.action_keys import (
            _filter_non_mega_capable_orders,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "heatwave"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        orders = [plain, mega]
        filtered = _filter_non_mega_capable_orders(battle, 0, orders)
        # Both remain.
        self.assertEqual(len(filtered), 2)
        self.assertFalse(filtered[0].mega)
        self.assertTrue(filtered[1].mega)


class TestAllowlistIntegrity(unittest.TestCase):
    """Phase BI-3I allowlist integrity audit.

    Explicit assertions that the named non-Mega species
    are NOT in the allowlist and that the normalizer
    maps them to themselves (not to a Mega-capable
    species). These are the species named in the BI-3I
    investigation as suspect; the allowlist must explicitly
    reject them so the BI-3G guard works at runtime.
    """

    def test_explicit_non_mega_species_not_in_allowlist(self):
        from doubles_engine.action_keys import (
            MEGA_CAPABLE_SPECIES,
        )
        non_mega = [
            "scovillain",
            "farigiraf",
            "pelipper",
            "floetteeternal",
            "dragonite",
            "incineroar",
            "garchomp",
        ]
        for s in non_mega:
            self.assertNotIn(
                s,
                MEGA_CAPABLE_SPECIES,
                f"{s} should NOT be in MEGA_CAPABLE_SPECIES",
            )

    def test_normalizer_preserves_non_mega_species(self):
        from doubles_engine.action_keys import (
            _normalize_species_for_mega,
        )
        non_mega = [
            "scovillain",
            "farigiraf",
            "pelipper",
            "floetteeternal",
            "dragonite",
            "incineroar",
            "garchomp",
        ]
        for s in non_mega:
            normalized = _normalize_species_for_mega(s)
            self.assertEqual(
                normalized,
                s,
                f"{s} should normalize to itself, got {normalized!r}",
            )

    def test_augment_produces_no_mega_variants_for_non_mega(self):
        """When the bot has enable_mega_evolution=True and 
        the active species is non-Mega-capable, no Mega 
        variants should be appended.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "dragonpulse"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        for species in ("dragonite", "incineroar", "garchomp"):
            battle = _MockBattle(
                can_mega_evolve_0=True,
                species_0=species,
            )
            orders = [[plain]]

            class _Cfg:
                enable_mega_evolution = True

            augmented = _augment_valid_orders_with_mega(
                battle, orders, _Cfg()
            )
            # Mega variants should be filtered out.
            for o in augmented[0]:
                self.assertFalse(
                    o.mega,
                    f"{species}: Mega variant unexpectedly present",
                )

    def test_charizard_still_produces_mega_variants(self):
        """Regression guard: charizard with can_mega=True 
        and flag ON still produces Mega variants.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "heatwave"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        orders = [[plain]]

        class _Cfg:
            enable_mega_evolution = True

        augmented = _augment_valid_orders_with_mega(
            battle, orders, _Cfg()
        )
        # Should have plain + Mega.
        self.assertEqual(len(augmented[0]), 2)
        self.assertFalse(augmented[0][0].mega)
        self.assertTrue(augmented[0][1].mega)


class TestOffBaselineMegaStripping(unittest.TestCase):
    """Phase BI-3K.1 regression tests.

    These tests prove that ``_augment_valid_orders_with_mega``
    strips ALL pre-existing Mega variants (including those
    for allowlisted species such as Charizard) when
    ``enable_mega_evolution=False``. This is required for a
    valid ON-vs-OFF qualification baseline.
    """

    def test_flag_off_strips_preexisting_mega_for_charizard(self):
        """Charizard is allowlisted. With flag OFF, pre-existing
        Charizard Mega variants must still be stripped.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "heatwave"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        # Input: poke-env pre-augmented valid_orders with
        # both plain and Mega Charizard orders.
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        orders = [[plain, mega]]

        class _Cfg:
            enable_mega_evolution = False

        out = _augment_valid_orders_with_mega(
            battle, orders, _Cfg()
        )
        # Result must contain only plain (no Mega).
        self.assertEqual(len(out[0]), 1)
        self.assertFalse(out[0][0].mega)
        # Count mega orders in result: must be 0.
        mega_count = sum(
            1 for o in out[0] if getattr(o, "mega", False)
        )
        self.assertEqual(mega_count, 0)

    def test_flag_off_strips_preexisting_mega_for_non_allowlisted_species(self):
        """Dragonite / incineroar are not allowlisted. Flag OFF
        must strip pre-existing Mega variants for them too.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "dragonpulse"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        for species in ("dragonite", "incineroar"):
            battle = _MockBattle(
                can_mega_evolve_0=True,
                species_0=species,
            )
            orders = [[plain, mega]]

            class _Cfg:
                enable_mega_evolution = False

            out = _augment_valid_orders_with_mega(
                battle, orders, _Cfg()
            )
            # Result must contain only plain (no Mega).
            self.assertEqual(len(out[0]), 1)
            self.assertFalse(out[0][0].mega)
            # No Mega orders.
            mega_count = sum(
                1 for o in out[0] if getattr(o, "mega", False)
            )
            self.assertEqual(mega_count, 0)

    def test_flag_on_keeps_or_generates_mega_for_allowlisted_species(self):
        """Charizard + protocol true + flag ON must produce
        at least one Mega order (regression guard: the fix
        must not break flag ON).
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "heatwave"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="charizard",
        )
        orders = [[plain]]

        class _Cfg:
            enable_mega_evolution = True

        out = _augment_valid_orders_with_mega(
            battle, orders, _Cfg()
        )
        # At least one Mega order.
        mega_count = sum(
            1 for o in out[0] if getattr(o, "mega", False)
        )
        self.assertGreaterEqual(mega_count, 1)

    def test_flag_on_strips_preexisting_mega_for_non_allowlisted_species(self):
        """Dragonite + protocol true + flag ON. Pre-existing
        Mega variants must be stripped (BI-3G guard) and no
        new Mega variants added.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "dragonpulse"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        battle = _MockBattle(
            can_mega_evolve_0=True,
            species_0="dragonite",
        )
        orders = [[plain, mega]]

        class _Cfg:
            enable_mega_evolution = True

        out = _augment_valid_orders_with_mega(
            battle, orders, _Cfg()
        )
        # No Mega orders for non-allowlisted species.
        mega_count = sum(
            1 for o in out[0] if getattr(o, "mega", False)
        )
        self.assertEqual(mega_count, 0)

    def test_filter_all_mega_orders_keeps_non_mega_order_content(self):
        """`_filter_all_mega_orders` keeps the content of
        non-Mega orders unchanged. The helper is importable
        from ``doubles_engine.action_keys``.
        """
        from doubles_engine.action_keys import (
            _filter_all_mega_orders,
        )
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class MockMove:
            id = "tackle"
        plain = SingleBattleOrder(MockMove(), move_target=0)
        mega = SingleBattleOrder(
            MockMove(), move_target=0, mega=True
        )
        orders = [plain, mega, plain]
        out = _filter_all_mega_orders(orders)
        # Two plain orders remain.
        self.assertEqual(len(out), 2)
        for o in out:
            self.assertFalse(getattr(o, "mega", False))
        # Content preserved (same objects).
        self.assertIs(out[0], plain)
        self.assertIs(out[1], plain)


class TestNoProductionCleanupImport(unittest.TestCase):
    def test_bot_does_not_import_cleanup(self):
        import bot_doubles_damage_aware as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)

    def test_action_keys_does_not_import_cleanup(self):
        import doubles_engine.action_keys as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)


if __name__ == "__main__":
    unittest.main()