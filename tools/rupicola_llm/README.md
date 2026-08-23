# `rupicola-llm` diagnostic and checked-solve prototype

This directory implements Phase 1 and the checker-first slice of Phase 2 from
[`LLM_DESIGN.md`](../../LLM_DESIGN.md).  It can replay an incomplete Rupicola
derivation, classify the residual goals left by the stock compiler, and check
an externally supplied candidate patch in an isolated source copy.

It does not call an LLM or apply a proposal to the user's source tree yet.

## Requirements

- Python 3.10 or newer;
- Git, for pinned repository identity and unchanged-worktree validation;
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

## Checked candidate workflow

`solve --candidate-patch` is the model-independent boundary used to develop
the Phase 2 controller.  It accepts a unified diff, never applies it to the
source tree, and runs it through the same gates a future model proposal will
use:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --candidate-patch tools/tests/fixtures/byte_or_candidate.patch \
    --scope project

Run 20260823-001234-baseline-byte-or-scalar-br2fn-ok-0123abcd
  status:    verified
  residuals: 1 -> 0
  proposal:  .../.rupicola/llm/runs/.../proposal.patch
  source tree unchanged; proposal is ready for review
```

`local` scope permits only the selected target source.  `project` scope also
permits `.v` files below `src/Rupicola/Generated`.  Both scopes reject path
traversal, protected paths, new assumptions and proof escape hatches, unsafe
loading or filesystem commands, and broad exported hint registrations.

For a valid candidate, the checker:

1. captures the initial residuals and opening theorem obligation;
2. applies the patch in a disposable copy of the target Rocq load root;
3. verifies that the elaborated opening obligation is unchanged;
4. compiles every changed module and replays the target proof;
5. requires all focused and auxiliary goals to close;
6. runs `rocq check` and an empty-allowlist `Print Assumptions` probe;
7. verifies that tracked and non-ignored untracked source files are unchanged.

Run artifacts are stored below `.rupicola/llm/runs/<run-id>/` and include the
initial and final obligations, append-only attempt record, exact proposal,
checker logs, validation report, and summary.  Review one with:

```console
$ tools/rupicola-llm show <run-id>
```

A rejected candidate exits with status `4` and retains the same evidence;
project/source and environment failures retain statuses `2` and `3`.

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
find-byte gaps, stable fingerprints across fresh proof sessions, and a Byte OR
candidate that passes the isolated compile, kernel, assumptions, and unchanged
source-tree gates.

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
- Candidate compilation currently orders project-support modules
  alphabetically before the target rather than constructing a complete import
  graph.
- Checked solve currently selects the first compile phrase in the candidate;
  explicit `--line` cursors remain diagnose-only.
- Patch application currently accepts text modifications and new files, but
  rejects deletion, rename, binary, and missing-final-newline patches.
- Checker processes have process-group timeouts; memory and operating-system
  filesystem limits remain to be added before accepting arbitrary remote-model
  output.
- Run metadata pins repository and submodule commits, but does not yet hash the
  complete compiled dependency closure.
- Model calls, bounded repair, clean second-workspace replay, `verify`, and
  explicit `apply` remain later Phase 2 work.
