# Pokémon Showdown AI Bot

This project sets up a local Pokémon Showdown server and runs simple AI bots that challenge each other or listen for battles using the `poke-env` library.

## Repository Layout

```
showdown_ai/                   # Production code (bots, helpers, core modules)
tests/                         # All tests
scripts/                       # Helper scripts (analyze, inspect, eval, etc.)
archive/                       # Old bot experiments (60 files)
docs/                          # Historical docs (phase plans, commit boundaries)
data/                          # Data files (teams, stats)
```

## Navigation

- `walkthrough.md` — Canonical development history
  (CONTROL-PRIORITY, PLANNER-ANTI-TR, WEATHER-TERRAIN, V2k qualification, etc.).
- `CURRENT_STATE.md` — Current project state and configuration.
- `docs/ROOT_INDEX.md` — Categorized index of the 81 `.py` files that were
  at root before the cleanup. Now historical reference.
- `docs/SCRIPTS_ORGANIZATION.md` — Migration history and rationale for
  `tests/`, `scripts/`, `showdown_ai/`, and `archive/`.
- `scripts/README.md` — What's in `scripts/<sub>/` (analyze, inspect, eval,
  dryrun, check, diagnose, fix, build, export).
- `archive/README.md` — Old `bot_*.py` experiment files kept for reference.
- `AGENTS.md` — Operating rules for coding agents (system reminder).

## Test runner

Tests are in `tests/`. Use `python -m unittest` from project root:

```bash
# Run a specific test
python -m unittest tests.test_anti_tr_target_debug

# Run tests with a keyword filter
python -m unittest discover -s tests -t . -k Magic

# Run all tests
python -m unittest discover -s tests -t .

# Or use the test runner script (in scripts/check/)
python scripts/check/run_tests.py test_anti_tr_target_debug
```

The runner handles the tests/ subfolder structure. Production modules are
importable via `import ability_rules`, `import bot_doubles_damage_aware`,
etc. (resolved through `showdown_ai/` in sys.path, set up by `tests/__init__.py`).

---

## 1. Setup and Run Local Pokémon Showdown Server

Open a new terminal window, navigate to the `pokemon-showdown` directory, and run the following commands:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown
npm install
cp -n config/config-example.js config/config.js
./pokemon-showdown start --no-security
```

> **Note**: The `--no-security` flag is required so that bots can log in and challenge each other locally without requiring real Pokémon Showdown account registration and authentication. Do not expose this server to the public internet or use port forwarding when running in this mode.

The server will be available at `http://localhost:8000`.

Known-good helper from this repo:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
./scripts/start_local_showdown.sh
```

Expected server output:

```text
Worker 1 now listening on 0.0.0.0:8000
Test your server at http://localhost:8000
```

Health check from another terminal:

```bash
python3 - <<'PY'
from urllib.request import urlopen
with urlopen("http://localhost:8000", timeout=3) as r:
    print("HTTP", r.status)
PY
```

Expected result: `HTTP 200`.

Do **not** use `node pokemon-showdown start --no-security`; on this checkout the
working command is the executable wrapper `./pokemon-showdown start --no-security`.
For Codex/OpenCode tool sessions, keep it as a long-running foreground session
rather than trying to detach it with `nohup`.

---

## 2. Python Virtual Environment Setup

Navigate to the `pokemon-showdown-ai` directory and set up the virtual environment:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Running the Bots

### A. Run a Random Bot (Listening Mode)
This bot will connect, log in as `RandomAgent_1`, and wait for a challenge from another player (e.g. you or another bot):

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_random
```

### B. Run Bot vs. Bot Self-Play (Milestone Verification)
This script initializes two bots (`SelfplayBot_1` and `SelfplayBot_2`), makes the first bot challenge the second bot to a Gen 9 Random Battle, and plays the match automatically to completion:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_battle_selfplay
```

### C. Run the Rule-Based Bot (Listening Mode)
This bot will connect, log in as `RuleBasedBot_1`, and wait for a challenge. It implements custom heuristic scoring based on base power, STAB, type effectiveness, and accuracy:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_rule_based
```

### D. Run Rule-Based Bot vs. Random Bot Matchup
This script runs a 10-battle matchup between our `RuleBasedPlayer` and a `RandomPlayer`, printing turn-by-turn logs and final win rates:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_rule_vs_random
```

### E. Run the Damage-Aware Bot (Listening Mode)
This bot will connect, log in as `DamageAwareBot_1`, and wait for a challenge. It implements advanced expected value damage calculations, priority-KO checks, and speed-aware setup checks:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_damage_aware
```

### F. Run Damage-Aware Bot vs. Rule-Based Bot Matchup
This script runs a 100-battle concurrent benchmark between `DamageAwarePlayer` and `RuleBasedPlayer`:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_damage_vs_rule
```

### G. Run Logged Matchup Benchmark
This script runs a 100-battle concurrent benchmark and records decision logs to `logs/battle_results.jsonl`:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.bot_damage_vs_rule_logged
```

### H. Analyze Battle Logs
This script parses the written JSONL logs offline to report performance statistics and identify potential losing patterns:

```bash
# Ensure virtual environment is active
source venv/bin/activate
python -m showdown_ai.analyze_logs
```

> **Note**: For listening-mode bots (A, C, E), the `-m showdown_ai.X` invocation
> runs the script as a module. If the script does not have an `if __name__ == "__main__":`
> guard that calls `player.play()`, you may need to invoke it directly. The
> `bot_doubles_damage_aware.py` main module is invoked via:
>
> ```bash
> python -m showdown_ai.bot_doubles_damage_aware
> ```

---

## 4. Troubleshooting

### Node.js version too old
*   **Symptom**: Starting the server fails with syntax or unsupported package errors.
*   **Solution**: Pokémon Showdown requires a modern version of Node.js (Node.js 18+ is recommended). Update your Node.js using Node Version Manager (nvm) or your system package manager:
    ```bash
    # Ubuntu/Linux Mint NodeSource installation
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
    ```

### Port 8000 already used
*   **Symptom**: Starting the server fails with `EADDRINUSE: address already in use :::8000`.
*   **Solution**: Another process is running on port 8000. Find the process ID and terminate it, or change the port in `config/config.js`:
    ```bash
    # Find process ID using port 8000
    lsof -i :8000
    # Kill the process
    kill -9 <PID>
    ```

### poke-env connection error
*   **Symptom**: `websockets.exceptions.InvalidMessage: ...` or connection refused.
*   **Solution**: Ensure the local Pokémon Showdown server is running *before* starting the Python bot. Also ensure the server was started with `--no-security` as required by `poke-env` for local unauthenticated login.

### Python virtual environment not activated
*   **Symptom**: `ModuleNotFoundError: No module named 'poke_env'` when running python files.
*   **Solution**: Activate the venv before executing python scripts:
    ```bash
    source venv/bin/activate
    ```

### Module not found: `ability_rules`, `bot_doubles_damage_aware`, etc.
*   **Symptom**: `ModuleNotFoundError: No module named 'ability_rules'` when running tests or scripts.
*   **Solution**: Production modules are at `showdown_ai/`. The `tests/__init__.py`
    adds `showdown_ai/` to sys.path so imports like `import ability_rules` work
    when running tests. For direct script invocation, prepend the project root:
    ```bash
    PYTHONPATH=/home/phurin/Program/Showdown_AI/pokemon-showdown-ai python -m showdown_ai.bot_damage_aware
    ```
    Or run as a module:
    ```bash
    python -m showdown_ai.bot_damage_aware
    ```
