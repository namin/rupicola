# `rupicola-llm` diagnostic prototype

This directory implements Phase 1 of the product architecture in
[`LLM_DESIGN.md`](../../LLM_DESIGN.md): a read-only command that replays an
incomplete Rupicola derivation and classifies the residual goals left by the
stock compiler.

It does not call an LLM or edit proofs yet.

## Requirements

- Python 3.9 or newer;
- the project's pinned `rocq` executable;
- `coqidetop` from the matching Rocq installation;
- coherent `.vo` artifacts for the selected source and its dependencies.

The implementation uses only Python's standard library.  The Rocq interaction
is isolated behind `CoqIdeDriver`, so it can later be replaced by a Rocq LSP or
SerAPI adapter.

## Usage

From the repository root:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMFindByteBaseline.v \
    --theorem baseline_find_byte_br2fn_ok

Rupicola diagnosis: src/Rupicola/Examples/LLMFindByteBaseline.v::baseline_find_byte_br2fn_ok
3 residuals after compile_step saturation
  1  representation_or_bounds   focused    ...
  2  control_flow_or_locals      focused    ...
  3  semantic_invariant         focused    ...
```

By default the source planner replays through the first phrase containing
`compile`, `compile_setup`, or `compile_step` in the named proof.  Use `--line`
to select another complete proof phrase:

```console
$ tools/rupicola-llm diagnose Example.v --theorem example_ok --line 120
```

Use `--json` for the versioned machine-readable record:

```console
$ tools/rupicola-llm diagnose Example.v --theorem example_ok --json
```

The record includes:

- repository, recursive submodule, Rocq, target, and source identities;
- the replay boundary and exact source hash;
- focused, background, shelved, and given-up goals;
- stable goal and snapshot fingerprints;
- deterministic classification and actionable/auxiliary counts;
- ranked local source evidence with declaration names and paths;
- structured environment or source diagnostics.

Exit status is `0` for a valid snapshot, including a fully compiled proof; `2`
for project, source, or usage errors; and `3` for Rocq environment or protocol
errors.

## Stale build artifacts

If Rocq reports inconsistent compiled assumptions, the command resolves both
logical library names through `_CoqProject` and reports their concrete `.vo`
paths and timestamps.  It stops instead of presenting the build failure as a
proof residual.

The command never rebuilds automatically.  Rebuild the reported library and
its dependents with the project's normal build system, then rerun `diagnose`.

## Tests

Run unit tests and the small live `coqidetop` protocol test with:

```console
$ tools/test-rupicola-llm -v
```

Include the three repository calibration cases with:

```console
$ RUPICOLA_LLM_CALIBRATION=1 tools/test-rupicola-llm -v
```

The calibration assertions require one byte-OR gap, two count-byte gaps, three
find-byte gaps, and stable fingerprints across fresh proof sessions.

## Current limitations

- The source boundary scanner handles nested comments, strings, qualified
  identifiers, and Ltac `..`, but is not a replacement for Rocq's parser.
  Rocq remains authoritative and source spans are reported on rejection.
- Automatic theorem selection currently recognizes ordinary theorem commands
  and `Derive ... as <name>` declarations.
- Classification is deterministic and intentionally small; unknown goals are
  preserved verbatim.
- Retrieval currently indexes checked-in declarations and ranks them with
  deterministic goal-shape, semantic-bridge, and same-case signals.  It does
  not yet parse elaborated declaration types or import graphs.
- Model calls, candidate workspaces, validation, and extension reuse belong to
  later phases.
