#!/usr/bin/env python3
"""Phase TARGET-1 — Read-only target selection audit.

Scans existing audit artifacts for wasteful
target selection patterns:

1. **overkill**: bot deals much more damage
   than needed to KO (low efficiency)
2. **missed_low_hp**: low-HP opp existed but
   wasn't targeted
3. **no_focus_fire**: both slots targeted
   different opps when one is significantly
   weaker (should focus)
4. **spread_over_single**: spread move used
   when single-target would KO

NOT scoring. NOT running battles. NOT
changing source.
"""
import json
import sys
import glob
from collections import Counter, defaultdict
from pathlib import Path


def normalize_turn(t):
    """Extract key fields from a turn audit dict."""
    return {
        'selected_score': t.get('selected_score'),
        'top_5_scores': t.get('top_5_scores', []),
        'score_gap': t.get('score_gap_selected_best_alt'),
        'both_slots_same_opp': t.get(
            'both_slots_targeted_same_opp'
        ),
        'overkill': t.get('overkill_penalty_triggered'),
        'overkill_applied': t.get(
            'order_aware_overkill_penalty_applied'
        ),
        'focus_fire': t.get('focus_fire_triggered'),
        'low_hp_existed': t.get('low_hp_opponent_existed'),
        'low_hp_targeted': t.get('low_hp_opponent_targeted'),
        'stale_target': t.get('stale_target_selected'),
        'stale_target_reason': t.get('stale_target_reason'),
        'state': t.get('state_snapshot', {}),
        'joint': t.get('selected_joint_order', ''),
    }


def analyze_artifact(fp):
    """Analyze a single audit artifact for target
    selection issues."""
    cases = {
        'overkill': [],
        'missed_low_hp': [],
        'no_focus_fire_when_should': [],
        'total_turns': 0,
    }
    seen = set()
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            bt = r.get('battle_tag', '?')
            if bt in seen:
                continue
            seen.add(bt)
            for t in r.get('audit_turns', []):
                cases['total_turns'] += 1
                d = normalize_turn(t)
                turn = t.get('turn', '?')

                # Case 1: overkill (damage much
                # more than needed)
                if d['overkill']:
                    cases['overkill'].append({
                        'bt': bt, 'turn': turn,
                        'selected_score': d['selected_score'],
                        'top_5': d['top_5_scores'],
                        'gap': d['score_gap'],
                    })

                # Case 2: low-HP opp existed but
                # wasn't targeted
                if (d['low_hp_existed']
                        and not d['low_hp_targeted']):
                    cases['missed_low_hp'].append({
                        'bt': bt, 'turn': turn,
                        'low_hp_existed': True,
                        'low_hp_targeted': False,
                        'joint': d['joint'],
                    })

                # Case 3: no focus fire (both slots
                # on different opps) — only flag
                # if there's a clear focus target
                # (we'll check via low_hp_targeted
                # in slot 0 but not slot 1, or
                # both_slots_targeted_same_opp=False
                # with one opp at very low HP)
                if (d['both_slots_same_opp'] is False
                        and d['low_hp_existed']
                        and d['low_hp_targeted']):
                    # Both slots targeted different
                    # opps even though low-HP existed
                    # and was targeted by slot 0
                    # (slot 1 went to full-HP)
                    cases['no_focus_fire_when_should'].append({
                        'bt': bt, 'turn': turn,
                        'joint': d['joint'],
                    })

    return cases


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_target1_audit.py <audit.jsonl> ...")
        sys.exit(1)
    artifacts = sys.argv[1:]
    print(f"Scanning {len(artifacts)} audit files...")

    all_cases = {
        'overkill': [],
        'missed_low_hp': [],
        'no_focus_fire_when_should': [],
        'total_turns': 0,
    }
    for fp in artifacts:
        c = analyze_artifact(fp)
        for k in ('overkill', 'missed_low_hp',
                  'no_focus_fire_when_should'):
            all_cases[k].extend(c[k])
        all_cases['total_turns'] += c['total_turns']

    print(f"\nTotal turns analyzed: {all_cases['total_turns']}")
    print()
    print("=== Target selection issues ===")
    print(f"  Overkill: {len(all_cases['overkill'])} cases")
    print(f"  Missed low-HP opp: "
          f"{len(all_cases['missed_low_hp'])} cases")
    print(f"  No focus-fire when should: "
          f"{len(all_cases['no_focus_fire_when_should'])} cases")

    print()
    print("=== Overkill sample (10) ===")
    for c in all_cases['overkill'][:10]:
        print(f"  {c}")

    print()
    print("=== Missed low-HP sample (10) ===")
    for c in all_cases['missed_low_hp'][:10]:
        print(f"  {c}")

    print()
    print("=== No-focus-fire sample (10) ===")
    for c in all_cases['no_focus_fire_when_should'][:10]:
        print(f"  {c}")

    # Save
    out_path = Path("/tmp/phaseTARGET1_audit.json")
    with open(out_path, 'w') as f:
        json.dump({
            'n_total_turns': all_cases['total_turns'],
            'n_overkill': len(all_cases['overkill']),
            'n_missed_low_hp': len(all_cases['missed_low_hp']),
            'n_no_focus_fire': len(
                all_cases['no_focus_fire_when_should']
            ),
            'sample_overkill': all_cases['overkill'][:10],
            'sample_missed_low_hp': (
                all_cases['missed_low_hp'][:10]
            ),
            'sample_no_focus_fire': (
                all_cases['no_focus_fire_when_should'][:10]
            ),
        }, f, indent=2, default=str)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
