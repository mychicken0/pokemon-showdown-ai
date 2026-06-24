#!/bin/bash
# RL-DATA-REFRESH-PREP-LONGRUN: shell wrapper for stable per-battle execution.
# Each battle is a separate Python process to avoid poke_env loop conflicts.

set -euo pipefail

MODE="${1:-enhanced_wt_support}"
MAX_BATTLES="${2:-1200}"
TARGET_ROWS="${3:-10000}"
OUTPUT="${4:-logs/rl_data_refresh_latest_policy_enhanced.jsonl}"
SUMMARY="${5:-logs/rl_data_refresh_latest_policy_enhanced_summary.json}"
BATCH_SIZE="${6:-5}"
DELAY="${7:-3}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
mkdir -p logs
source venv/bin/activate

echo "=== RL-DATA-REFRESH-PREP-LONGRUN (shell wrapper) ==="
echo "Mode: $MODE, Max battles: $MAX_BATTLES, Target rows: $TARGET_ROWS"
echo "Output: $OUTPUT, Batch size: $BATCH_SIZE, Delay: ${DELAY}s"

TOTAL_TURNS=0
TOTAL_FINISHED=0
BATCH=1
RESULTS_JSONL="$OUTPUT"
RESULTS_JSONL="${RESULTS_JSONL%.jsonl}_results.jsonl"

for ((b=1; b<=MAX_BATTLES; b+=BATCH_SIZE)); do
    end=$((b + BATCH_SIZE - 1))
    if ((end > MAX_BATTLES)); then end=$MAX_BATTLES; fi
    count=$((end - b + 1))

    echo ""
    echo "=== Batch $BATCH: battles $b-$end ==="

    for i in $(seq "$b" "$end"); do
        suffix="b${i}_$(date +%s)"
        echo "  Battle $i/$MAX_BATTLES suffix=$suffix"
        out_file="$OUTPUT"
        out_file="${out_file%.jsonl}_${suffix}.jsonl"

        # Run one battle in a clean subprocess
        timeout --foreground --signal=TERM --kill-after=30s 180s \
          ./venv/bin/python -u showdown_ai/rl_data_refresh_prep_longrun_local.py \
            --mode "$MODE" \
            --max-battles 1 \
            --no-server-check \
            --output "$out_file" \
            --summary "${SUMMARY%.json}_${suffix}.json" \
            2>&1 | grep -E '^fin=|^Summary:|= BATCH |= complete' || true

        # Extract turns from the summary
        if [ -f "${SUMMARY%.json}_${suffix}.json" ]; then
            nf=$(python3 -c "import json; d=json.load(open('${SUMMARY%.json}_${suffix}.json')); print(int(d.get('n_finished',0)))")
            turns=$(python3 -c "import json; d=json.load(open('${SUMMARY%.json}_${suffix}.json')); print(d.get('total_turns',0))")
            TOTAL_TURNS=$((TOTAL_TURNS + turns))
            TOTAL_FINISHED=$((TOTAL_FINISHED + nf))
            echo "{\"battle\":$i,\"suffix\":\"$suffix\",\"turns\":$turns,\"finished\":$nf}" >> "$RESULTS_JSONL"
        fi

        echo "    turns=$turns finished=$nf total_turns=$TOTAL_TURNS"

        if ((TOTAL_TURNS >= TARGET_ROWS)); then
            echo "  Target rows $TARGET_ROWS reached at battle $i"
            break 2
        fi

        sleep "$DELAY"
    done

    echo "  [BATCH $BATCH] total_finished=$TOTAL_FINISHED total_turns=$TOTAL_TURNS"
    BATCH=$((BATCH + 1))
done

echo ""
echo "========================================"
echo "RL-DATA-REFRESH-PREP-LONGRUN complete"
echo "========================================"
echo "Total battles finished: $TOTAL_FINISHED"
echo "Total turns: $TOTAL_TURNS"
echo "Results: $RESULTS_JSONL"
echo "Output: $OUTPUT"
