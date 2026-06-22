#!/usr/bin/env python3
"""Test runner for the project.

Usage:
    python run_tests.py              # discover all tests
    python run_tests.py test_anti    # run tests matching pattern
    python run_tests.py tests.test_anti  # explicit tests. prefix
    python run_tests.py -k Magic     # filter with -k
    python run_tests.py --list       # list all test modules

The runner handles the tests/ subfolder structure by:
- Using `python -m unittest discover -s tests -t .` for full discovery
- Checking if the test is at root or in tests/ for specific runs
- Using the `-t .` flag so root-relative imports work from tests/
"""
import subprocess
import sys
from pathlib import Path

cmd = [sys.executable, "-m", "unittest"]
args = sys.argv[1:]

# Handle --list
if "--list" in args or "-L" in args:
    args = [a for a in args if a not in ("--list", "-L")]
    result = subprocess.run(
        ["find", "tests", "-name", "test_*.py"],
        capture_output=True, text=True
    )
    print("Available test modules in tests/:")
    for f in sorted(result.stdout.strip().split("\n")):
        if f:
            print(f"  {f.replace('.py', '')}")
    result = subprocess.run(
        ["ls", "test_*.py"],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        print("\nTest modules at root (cross-imports, not moved):")
        for f in sorted(result.stdout.strip().split("\n")):
            if f:
                print(f"  {f.replace('.py', '')}")
    sys.exit(0)

# Check if -k is present
if "-k" in args:
    k_idx = args.index("-k")
    k_val = args[k_idx + 1] if k_idx + 1 < len(args) else ""
    cmd += ["discover", "-s", "tests", "-t", ".", "-k", k_val]
elif not args or "-h" in args or "--help" in args:
    # Run all tests in tests/
    cmd += ["discover", "-s", "tests", "-t", "."]
else:
    # Run specific test(s)
    for arg in args:
        if arg.startswith("-"):
            cmd.append(arg)
        else:
            name = arg.replace(".py", "")
            # Check if file is at root or in tests/
            root_path = Path(f"{name}.py")
            tests_path = Path(f"tests/{name}.py")
            if root_path.exists() and not tests_path.exists():
                # Use root path (no tests. prefix)
                cmd.append(name)
            elif tests_path.exists():
                # Use tests/ path
                if not name.startswith("tests."):
                    cmd.append(f"tests.{name.replace('tests.', '')}")
                else:
                    cmd.append(name)
            else:
                # File not found - try anyway
                cmd.append(name)

result = subprocess.run(cmd)
sys.exit(result.returncode)
