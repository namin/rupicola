# LLM-assisted Rupicola: product design

Status: proposed product architecture v1.  The companion experimental protocol
is in [`LLM_EVAL.md`](LLM_EVAL.md).

Implementation status: the read-only Phase 1 diagnostic and an executable
Phase 2 slice are in [`tools/rupicola_llm`](tools/rupicola_llm/README.md).  The
sidecar captures and classifies live residual goals, ranks local evidence,
offers a provider-neutral typed action protocol, runs a bounded repair
controller, and validates every candidate in isolation.  A deterministic
scripted provider exercises rejection followed by repair without calling a
model.  A concrete LLM provider adapter, separate fast checker, clean
second-workspace replay, `verify`, and explicit `apply` remain.

## 1. Product decision

Build the LLM integration as an external sidecar named `rupicola-llm`, not as
code executed inside Rupicola's trusted proof tactics.

The sidecar observes the residual goals left by Rupicola, retrieves relevant
repository examples, proposes a small Gallina augmentation, and checks that
augmentation in an isolated workspace.  The user receives a reviewable patch
and validation report.  Nothing enters the project until the user explicitly
applies it, and nothing is considered correct unless Rocq accepts it.

```text
Rupicola compile
      |
      v
residual proof goals -----> deterministic classifier and repository retrieval
                                      |
                                      v
                              untrusted LLM agent
                                      |
                                      v
                            isolated candidate patch
                                      |
                                      v
                       Rocq check + policy validation
                                      |
                         verified proposal for review
```

This keeps three concerns separate:

- Rupicola remains a deterministic, replayable relational compiler.
- The LLM performs fallible search and code generation outside the trusted
  computing base.
- Rocq and the existing Bedrock2 specifications remain the acceptance authority.

## 2. Problem

Rupicola's `compile` tactic already performs substantial proof search.  When it
stops, however, the remaining goal often requires repository knowledge that is
not encoded in the tactic:

- a missing expression compiler rule;
- a semantic invariant connecting an implementation combinator to a separate
  specification;
- a representation or arithmetic side condition;
- an explicit control-flow or locals transition;
- a separation-logic frame or mutation invariant;
- a narrow cleanup, import, or hint-registration change.

Today the author must recognize the residual class, find a nearby example,
adapt its proof, discover the correct hint database, and iterate manually with
Rocq.  The product automates that search-and-check loop while preserving the
same proof boundary.

The three development cases demonstrate the intended range:

- byte OR adds a `DEXPR` rule to `expr_compiler`;
- count byte adds a generalized fold theorem to
  `compiler_side_conditions`;
- find byte adds a proved early-exit locals transition and invokes it through a
  narrow custom compilation step.

## 3. Goals and non-goals

### Goals

1. Explain why a Rupicola derivation stopped in terms meaningful to a proof
   author.
2. Find the most relevant compiler rules, tactics, invariants, and examples in
   the pinned repository.
3. Produce the smallest proof-local or project-local augmentation that closes
   the residuals.
4. Iterate against real Rocq feedback without exposing the source tree to
   uncontrolled writes or commands.
5. Return a transparent patch, proof-state history, and validation report.
6. Make verified extensions discoverable and reusable in later derivations.
7. Keep model choice, network access, and source disclosure configurable.

### Non-goals

- accepting an LLM's explanation as evidence of correctness;
- changing the semantic program or specification to make a proof easier;
- introducing axioms, admitted obligations, unchecked casts, or trusted model
  output;
- automatically merging or committing generated code;
- replacing ordinary `compile` for derivations it already solves;
- synthesizing an initial specification from an informal request in v1;
- proving the C printer or downstream C toolchain correct.

## 4. User experience

The product has four explicit workflows.

### Diagnose

`diagnose` is read-only.  It runs the existing compiler to saturation at a
selected proof location, classifies every remaining goal, and shows the local
repository evidence behind the classification.

```console
$ rupicola-llm diagnose src/Rupicola/Examples/Search.v --theorem search_ok

3 residuals after compile_step saturation
  1  representation_or_bounds   byte values must fit the target word
  2  control_flow_or_locals      break branch does not realize the next locals
  3  semantic_invariant          ranged loop differs from recursive search

Closest checked patterns
  Rupicola.Examples.LLMFindByteProof.compile_break_transition
  Rupicola.Lib.Loops.compile_ranged_for_fresh
  Rupicola.Lib.ExprCompiler.expr_compile_byte_xor
```

The explanation must distinguish facts observed from Rocq from an LLM
interpretation.  Each retrieved item includes a source path and declaration
name.

### Solve

`solve` starts from the diagnostic snapshot, first tries already verified local
extensions, then starts the LLM loop if deterministic reuse does not close the
goals.

```console
$ rupicola-llm solve src/Rupicola/Examples/Search.v \
    --theorem search_ok --scope project

Run 20260822-184210-search_ok
  candidate: src/Rupicola/Generated/SearchSupport.v
  attempts: 7
  residuals: 3 -> 0
  assumptions: none
  targeted build: passed
  proposal is ready for review; the source tree is unchanged
```

The default scope is `local`.  The agent must justify escalation from a local
proof to a reusable project module.  Changes to Rupicola core libraries are
never part of an ordinary solve run.

### Review and apply

`show` presents the patch, new public declarations, goal-by-goal progress, all
checker commands, assumptions, and warnings.  `apply` is a separate user action
that verifies the current repository still matches the run's base before
applying the patch.

```console
$ rupicola-llm show 20260822-184210-search_ok
$ rupicola-llm apply 20260822-184210-search_ok
```

The product does not stage, commit, or push.  If the worktree changed after the
run, `apply` reports a conflict and leaves both the proposal and user files
untouched.

### Promote

A verified project extension can be prepared for broader reuse:

```console
$ rupicola-llm promote 20260822-184210-search_ok --dry-run
```

Promotion adds stricter linting, reuse checks, documentation, and the broader
test target required for a library contribution.  It produces another patch
for maintainer review; it never moves generated code into
`src/Rupicola/Lib` automatically.

## 5. Architecture

`rupicola-llm` is a local orchestrator with seven components.

| Component | Responsibility |
|---|---|
| Project adapter | Resolves Rocq load paths, imports, build targets, root commit, and submodules |
| Proof-state driver | Replays a proof to a cursor, saturates `compile_step`, and returns structured residuals |
| Classifier | Assigns deterministic residual classes and chooses retrieval/repair strategies |
| Retriever | Finds declarations, hints, tactics, and examples relevant to constants and goal shapes |
| Agent controller | Gives a bounded context and typed actions to the configured model |
| Candidate workspace | Applies proposals in an isolated overlay or disposable worktree |
| Validator and registry | Checks proposals, records artifacts, and indexes accepted extensions |

The components communicate through versioned data structures rather than
human-formatted terminal text.  Model-provider APIs and Rocq interaction
backends are adapters, so neither is coupled to the rest of the product.

### Project adapter

The project adapter reads `_CoqProject`, the build system, and a small optional
`.rupicola-llm.toml`.  For this repository it understands the recursive
Bedrock2/coqutil submodules and the `-R src/Rupicola Rupicola` logical mapping.
It records dependency SHAs before a run and supplies two checks:

- a fast target that compiles only the candidate and affected theorem;
- a final dependency-aware target, normally the relevant `.vo` goals.

It never rewrites generated makefiles as part of a proposal.

### Proof-state driver

The driver opens the selected theorem through a Rocq interactive protocol and
replays the existing proof prefix to the selected location.  From an initial
Rupicola derivation goal it runs the equivalent of:

```coq
compile_setup; repeat repeat compile_step.
```

If the prefix has already performed `compile_setup`, the driver preserves that
state and only saturates `compile_step`.  It does not run setup twice or discard
useful tactics the author placed before the selected cursor.

It returns every remaining goal with its local context, elaborated type,
source location, and deterministic fingerprint.  A small Rupicola probe module
may expose this tactic sequence, but it has no authority to close a theorem.

The driver interface is:

```text
open(file, theorem-or-position) -> ProofHandle
saturate(handle)                -> ProofSnapshot
check(handle, patch, mode)      -> CheckResult
assumptions(module, theorem)    -> AssumptionSet
```

The implementation may use the interactive backend supported by the pinned
Rocq toolchain.  Parsing human-oriented compiler errors is a fallback, not the
only source of proof state.

### Residual classifier

Classification begins with deterministic goal shapes:

| Signal | Class | Preferred augmentation |
|---|---|---|
| `DEXPR` | Expression compilation | semantic morphism, `DEXPR` lemma, patterned `expr_compiler` hint |
| `WP_nlet` or `WP_nlet_eq` | Binding compilation | checked compilation lemma and `compiler` hint |
| Pure equality over a fold or loop | Semantic invariant | generalized theorem in `compiler_side_conditions` |
| Word range or representation proposition | Representation/bounds | reusable range lemma or targeted side-condition hint |
| `sep`, array ownership, or memory relation | Mutation/frame | representation, frame, or loop invariant lemma |
| Exit token or nontrivial map equality | Control flow/locals | explicit transition lemma and narrow custom dispatcher |
| Rewrite/import residue | Cleanup/integration | local rewrite, unfold hint, or missing import |

The deterministic tag selects a strategy and retrieval query.  The LLM may
refine the explanation, but it cannot hide or replace the raw goal.

### Repository retriever

The retriever builds a local index of:

- declaration names and types;
- constants occurring in theorem statements and proof goals;
- imports and dependency edges;
- registrations in `compiler`, `expr_compiler`,
  `compiler_side_conditions`, and cleanup databases;
- uses of `compile_custom`, `compile_step`, loop compilers, array compilers,
  and separation-logic tactics;
- accepted generated extensions and their applicability metadata.

Retrieval is shape-aware.  For a `DEXPR` goal involving a byte operator it
prefers neighboring `expr_compile_byte_*` declarations and their morphism
lemmas.  For a fold equality it prefers generalized accumulator theorems.  For
a locals map equality it searches map-update and control-flow transitions.

Each model context packet contains the current residuals, relevant local
hypotheses, direct dependencies, and a bounded set of cited snippets.  The
whole repository is searchable through typed tools but is not copied into every
model request.

### Agent controller

The model receives no unrestricted shell.  It can request these typed actions:

```text
search(query, filters)
read(path, declaration-or-lines)
inspect_obligation(id, printing_mode)
propose_patch(unified_diff, rationale)
check(mode = fast | final)
revert_candidate()
finish(summary)
```

The controller validates paths and arguments, applies patches only inside the
candidate workspace, and records every action.  Checker commands are assembled
by the project adapter rather than supplied as model-authored shell strings.

The current prototype implements these calls as strict, versioned JSON-schema
tools behind an `AgentProvider` protocol.  Its deterministic scripted adapter
is an acceptance harness for controller behavior, not a simulated measure of
model quality.  Until the separate fast checker exists, both requested check
modes execute the stricter final validation pipeline and report that effective
mode in the transcript.

The repair loop is:

1. Run stock compilation to a fixed point.
2. Try matching verified extensions from the local registry.
3. Classify residuals and retrieve analogues.
4. Ask for one minimal candidate patch.
5. Run the fast checker and compute the residual delta.
6. Keep a progressing candidate or revert a regression.
7. Repeat within the configured budget.
8. Run final validation when no residual remains.

Temporary increases in subgoals can be legitimate, so “regression” is not just
a larger goal count.  A candidate is reverted automatically only for a scope or
policy violation, checker crash, frozen-file change, or a return to a previously
failed source digest.  Other proof-search decisions remain visible to the agent.

## 6. Augmentation scopes

The sidecar prefers the narrowest artifact that solves the task.

### Proof-local

A lemma, hint, or tactic invocation lives beside the target proof and affects
only that module.  This is the default and has the smallest proof-search blast
radius.

### Project extension

A new module under the configured extension root exports reusable lemmas or
hints.  For this repository the proposed default is
`src/Rupicola/Generated/`; downstream projects configure their own logical
root.  Target modules import the extension explicitly, so global hint effects
are scoped by the Rocq module graph.

### Core candidate

A rule intended for `src/Rupicola/Lib` is a promotion artifact, not ordinary
agent output.  It requires maintainer review, a close analogue or new API
rationale, regression tests, proof-search timing checks, and a full library
build.

Generated hint registrations must name their database, use a specific head
pattern where possible, and document their priority.  Broad pattern-free
`#[export] Hint Extern` registrations are rejected outside proof-local scope
unless a maintainer explicitly overrides the policy.  This limits accidental
backtracking and performance regressions.

## 7. Session lifecycle and artifacts

A run moves through these states:

```text
created -> diagnosed -> searching -> checking -> verified -> reviewed -> applied
                         |              |
                         +-> exhausted  +-> rejected
```

`verified` means the candidate passed automated checks in isolation.  It does
not mean a human accepted its maintainability.  `applied` is reached only by an
explicit user command.

Runs are stored outside tracked source files by default:

```text
.rupicola/llm/runs/<run-id>/
  run.json
  obligations.initial.json
  attempts.jsonl
  proposal.patch
  validation.json
  summary.md
  logs/
```

`run.json` pins the repository and submodule SHAs, target, proof cursor, model
configuration, prompt version, permissions, limits, and dependency digests.
`attempts.jsonl` is append-only and records candidate hashes, actions, checker
results, and residual deltas.  Logs and transcripts may contain source code and
therefore follow the project's retention policy.

The source patch is the portable product artifact.  Replaying an accepted patch
requires Rocq and the pinned source dependencies, not the original LLM or its
transcript.

## 8. Extension registry and reuse

Before calling a model, the product tries existing verified extensions.  The
registry is an index, not a second proof system.  Every entry points to checked
Gallina source and records:

- module and declaration names;
- extension scope and validation commit;
- target hint database and priority;
- normalized goal-head and constant signatures;
- required imports, typeclass contexts, word widths, and memory models;
- proofs or derivations on which the extension has already been replayed.

An exact or high-confidence match is tested by importing the module in the
candidate workspace.  It is never auto-imported into the user's source tree.
Successful reuse becomes the proposed patch; failed reuse becomes additional
diagnostic evidence for the agent.

Registry states are:

- `candidate`: verified for one run;
- `project`: applied and checked in the current project;
- `core`: merged into Rupicola's maintained compiler library;
- `stale`: dependency digests changed and replay is required;
- `quarantined`: caused a validation or proof-search regression.

## 9. Trust, security, and privacy

### Logical trust boundary

Trusted for theorem acceptance:

- the project's chosen Rocq kernel and accepted plugins;
- Rupicola, Bedrock2, coqutil, and their pinned dependencies;
- the theorem statement and semantic specifications reviewed by the project.

Untrusted:

- the LLM and model provider;
- retrieval ranking and residual classification;
- the orchestrator, reports, C printer output, and explanatory prose;
- generated proof scripts until the kernel accepts them.

The validator improves workflow safety but is not a replacement for kernel
checking.  The final theorem's `Print Assumptions` output is compared with an
explicit project allowlist, empty by default.

### Workspace and command safety

- The model can modify only an isolated candidate overlay through patches.
- Frozen specifications and theorem types are hash-checked before every final
  validation.
- Checker processes have wall-time, memory, output, and process limits.
- The model cannot write `.git`, submodules, build tools, validator code, or
  configuration during a run.
- The product exposes predefined checker actions instead of arbitrary shell.
- Applying, promoting, committing, publishing, or deleting files always remains
  a user action.

The source policy rejects new `Admitted`, `admit`, `Axiom`, `Conjecture`,
unapproved `Parameter`, unsafe plugin loading, unchecked casts, and equivalent
bypasses.  Text scanning is defense in depth; fresh compilation, `rocq check`,
and the assumptions report are decisive.

### Source disclosure

A remote model necessarily receives some project source.  Before the first
remote run, the product shows the configured provider, data-retention mode, and
which paths may be retrieved.  It supports:

- local-only model providers;
- path deny lists and generated-file exclusions;
- secret scanning and redaction before context leaves the machine;
- a dry-run context manifest;
- local transcript storage with configurable retention;
- a provider gateway as the only network-capable component.

Repository search tools available to the model have no independent internet
access.

## 10. Validation pipeline

Fast validation runs after candidate edits:

1. verify writable paths and frozen hashes;
2. compile the candidate module and selected target;
3. capture all remaining goals and their fingerprints;
4. reject policy violations and return actionable checker output.

Final validation runs from a clean workspace containing only the saved patch:

1. recheck repository and recursive submodule SHAs;
2. compile all added or changed `.v` files;
3. run `rocq check -silent` on their modules;
4. compare `Print Assumptions` with the configured allowlist;
5. verify the required generated Bedrock2 function theorem;
6. run configured AST-shape assertions when the task generates code;
7. run dependency-aware make targets;
8. lint exported hints for specificity and priority;
9. replay affected project extensions and record timing changes.

The full repository build is required for a core promotion.  It is optional for
a local proposal when the project has declared unrelated failures, but those
failures are shown in the report.

Validation results use `passed`, `failed`, `skipped`, or `unavailable`; the
product never renders a skipped check as success.

## 11. Configuration and interfaces

The CLI is the v1 interface.  Editor integration calls the same local service
later rather than embedding a second implementation.

Commands:

```text
rupicola-llm init
rupicola-llm diagnose <file> --theorem <name>
rupicola-llm solve <file> --theorem <name> [--scope local|project]
rupicola-llm show <run-id>
rupicola-llm verify <run-id>
rupicola-llm apply <run-id>
rupicola-llm promote <run-id> --dry-run
rupicola-llm runs
```

The project configuration declares:

```toml
version = 1

[project]
rocq_project = "_CoqProject"
extension_root = "src/Rupicola/Generated"

[build]
fast = ["rocq", "compile", "-q"]
final_targets = []

[policy]
default_scope = "local"
assumptions = []
remote_context_allow = ["src/Rupicola"]
remote_context_deny = []

[limits]
wall_seconds = 3600
checker_seconds = 120
attempts = 60
```

This is illustrative configuration, not permission for the model to alter
commands.  `init` derives safe defaults and asks the user to review them.  Model
credentials live outside the repository configuration.

The internal service exposes versioned interfaces for `ProofSnapshot`,
`CandidatePatch`, `CheckResult`, `ValidationReport`, and `RegistryEntry`.
Keeping these stable permits a CLI, editor, or CI client to share the same proof
and policy engine.

## 12. Failure and recovery behavior

The product returns the best verified state it has; it does not disguise an
incomplete proof as a solution.

| Failure | Product behavior |
|---|---|
| No supported proof state at the selected location | Explain the required cursor or theorem shape without editing files |
| Unknown residual | Preserve the raw goal, retrieve generic analogues, and label the interpretation uncertain |
| Candidate does not compile | Keep checker output and let the bounded repair loop continue |
| Candidate violates scope or proof policy | Reject and revert it immediately |
| Repeated source digest or no progress | Stop the loop early and report the residuals |
| Checker timeout or resource exhaustion | Kill the isolated process and quarantine the attempt |
| Final clean replay differs from the interactive run | Mark the run rejected and retain both logs |
| Worktree changed before `apply` | Refuse to overwrite and offer a patch file for manual resolution |
| Registry entry no longer replays | Mark it stale; do not offer it as verified reuse |
| Model/provider unavailable | Preserve the diagnosis so another configured provider or a human can continue |

A user can resume an exhausted run from its last policy-valid candidate.  The
resume creates a child run with its own model and budget record; histories are
never silently combined.

## 13. Observability

Every run reports:

- residuals before and after each accepted candidate;
- source declarations retrieved and why they were selected;
- model/tool/checker activity and elapsed time;
- assumptions, policy checks, build results, and output digests;
- the public interface and scope of new lemmas or hints;
- whether an existing extension was reused;
- proof-search timing before and after exported hints.

Telemetry is local by default.  Aggregate product telemetry is opt-in and must
exclude source, proof goals, patches, and transcripts unless the user explicitly
chooses to share them.

Product health is measured by verified proposal rate, user acceptance rate,
accepted patches that still replay, time to a verified proposal, reuse rate,
and post-generation edits.  The controlled research methodology for measuring
agent capability is defined separately in `LLM_EVAL.md`.

## 14. Delivery plan

### Phase 1: diagnostic sidecar

- project discovery and pinned environment manifest;
- proof-state capture after `compile_step` saturation;
- deterministic residual classifier;
- repository symbol/hint index;
- read-only `diagnose` command.

This phase is useful without a model and validates the hardest integration
boundary: obtaining stable Rupicola residuals.

### Phase 2: checked solve loop

- model-provider adapter and typed tool protocol;
- isolated candidate workspaces;
- patch generation, fast checks, and bounded repair;
- final clean replay, assumptions check, and validation report;
- `solve`, `show`, `verify`, and explicit `apply` commands.

The three existing LLM case studies are acceptance fixtures for this phase.

### Phase 3: reusable extensions

- generated project-extension modules;
- registry matching and deterministic reuse before model invocation;
- hint specificity/performance linting;
- `promote --dry-run` workflow and transfer checks.

### Phase 4: editor and CI clients

- editor code action on an incomplete `compile` proof;
- streaming residual and checker status;
- CI diagnosis and optional patch artifact generation;
- no automatic merge, commit, or core promotion.

## 15. MVP acceptance criteria

The first usable product is complete when it can:

1. Open a named Rupicola derivation and capture the residual goals left by the
   stock compiler without editing the source.
2. Correctly classify the residual classes in the byte-OR, count-byte, and
   find-byte development cases.
3. Retrieve the relevant local compiler rules and examples with source
   citations.
4. Run an LLM-authored candidate through an isolated edit/check loop using only
   typed tools.
5. Produce a patch that replays in a second clean workspace and passes the
   configured assumptions, kernel, build, and scope checks.
6. Leave the user's worktree unchanged until an explicit `apply` command.
7. Reuse an applied byte-OR-style compiler extension on another importing
   derivation before calling the model.
8. Return an auditable diagnosis and best residual state when it cannot solve a
   task.

These criteria establish a real proof-engine augmentation workflow.  The
larger held-out experiment in `LLM_EVAL.md` then measures how often the product's
agent succeeds, rather than standing in for the product design itself.
