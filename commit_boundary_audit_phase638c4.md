# Phase 6.3.8c.4 Commit Boundary Audit

This report supersedes the rejected Phase 6.3.8c.3 commit plan.

## Manifest Fix

New paired qualification runs no longer create an aggregate
`*_audit.jsonl` placeholder. Each battle already records two real
per-player audit paths, which are the source of truth.

The historical zero-byte
`logs/support_target_paired_phase638c_v2_audit.jsonl` remains untouched
for artifact immutability and is classified as
`legacy_empty_creation_defect`, not as an expected current artifact.

## Ordered Commit Groups

1. **Checkout-local test and analyzer paths**: 21 files. Removes
   hard-coded project paths and makes subprocess tests create their own
   temporary collision fixtures. Clean verification: 569 tests,
   exit 0, 54.49s.
2. **Canonical mechanics/runtime/support-target stack**: 30 files.
   Includes shared mechanics, VGC runtime parity, support-target audit,
   analyzers, inspectors, and regression tests. Depends on group 1.
   Clean verification: 624 tests, exit 0, 128.87s.
3. **Paired support-target lineage**: qualifier, analyzer, and test
   module. It depends on group 2's player/logger schema. Clean
   verification: 93 tests, exit 0, 2.01s, zero skips.
4. **Documentation and this audit**: `CURRENT_STATE.md`,
   `walkthrough.md`, and the c.4 JSON/Markdown reports. This must be
   last because the documents cover all implementation groups.

Exact file lists are in `commit_boundary_audit_phase638c4.json`.

## Clean Checkout Proof

The simulation used `git archive HEAD` in a new `/tmp` directory.
Files were copied only when their ordered group was applied. The
dependency environment was reused through a `venv` symlink; project
source was not.

- Group 1: 569 tests, exit 0.
- Groups 1-2 focused: 624 tests, exit 0.
- Groups 1-3 paired: 93 tests, exit 0, zero skips.
- Final clean discovery: 1,837 tests, exit 0, 180.19s, zero skips.
- Production worktree discovery: 1,837 tests, exit 0, 186.06s.
- All runs promoted `ResourceWarning` to errors.

Hard-coded `sys.path`/subprocess working directories and tests that
required ignored `logs/` fixtures were corrected. The final clean run
does not import modules from the dirty worktree.

## Status

The source tree is ready for the four ordered commits above, but no
commit or push has been performed. Generated `logs/` artifacts remain
ignored and must not be staged.

`enable_support_move_target_hard_safety` remains `False`; adoption and
Phase V3 remain blocked.
