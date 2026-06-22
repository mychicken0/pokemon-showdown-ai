"""Project-wide conftest.

Adds src/ to sys.path so production modules moved to src/
can still be imported with `import module_name` (backward compatible).

Also adds scripts/ sub-folders to sys.path so script modules
moved to sub-folders can be imported with `import module_name`.

This file is pytest-compatible. For unittest, it has no effect
(the runner uses -t . to set top-level).

For tests that use root-relative imports after modules moved to src/,
add `import sys; sys.path.insert(0, 'src')` at the top of the test.
"""
# This is a documentation-only file. The actual path setup is done in
# run_tests.py and individual test files as needed.
