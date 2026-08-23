# LLM augmentation for Rupicola: evaluation protocol

Status: proposed protocol v1.  The protocol must be committed and tagged before
the held-out tasks are instantiated or any scored run begins.

This protocol evaluates the product architecture in
[`LLM_DESIGN.md`](LLM_DESIGN.md); it does not replace that design.

The newcomer-oriented [`LLM_TUTORIAL.md`](LLM_TUTORIAL.md) exercises visible
development calibration cases only.  Its local and live walkthroughs are
useful product checks, but they are not scored evidence under this protocol.

## 1. Decision

The LLM is an external, untrusted augmentation layer for Rupicola.  It may read
the repository, inspect failed compilation obligations, write Gallina proofs,
add compiler rules, and use Rocq feedback.  It does not become part of the
trusted computing base:

```text
frozen task -> stock Rupicola residuals -> LLM-authored augmentation
                                         -> Rocq kernel checks
                                         -> fresh-build scorer
```

Only artifacts accepted by the existing Rocq kernel and the evaluation scorer
count as successful.  The intended claim is therefore not that an LLM can be
trusted to prove programs, but that it can propose useful proof-engine
extensions whose correctness is decided by the existing proof checker.

## 2. Questions and scope

The evaluation asks four questions:

1. **Completion:** how often can a repository-aware LLM close a known Rupicola
   compilation gap within a fixed budget?
2. **Soundness boundary:** do the accepted solutions preserve frozen semantics
   and close without new assumptions or unchecked escape hatches?
3. **Reuse:** does an augmentation solve a separately prepared transfer case,
   or only the primary example visible to the agent?
4. **Cost and failure mode:** how much time, model usage, and checker feedback
   does a solution require, and where do unsuccessful runs stop?

The evaluation covers proof discovery and integration through a generated
Bedrock2 function theorem.  It does not establish correctness of the C printer,
a C compiler, or generated machine code.  Printed C is diagnostic output only.

This is an evaluation of one fixed agent configuration, not a general claim
about all LLMs.  Comparisons among models or against human experts require a
separately preregistered extension of this protocol.

## 3. Calibration cases

The three completed studies are the development set.  They established the
task format and exposed the main kinds of gaps, but they are not scored data:

| Case | Commit | Gap exercised | Main lesson |
|---|---|---|---|
| Byte OR | `cb18c1d` | Missing expression compiler rule | A local analogue can become a reusable, proved hint |
| Count byte | `0bd360f` | Fold-to-recursion semantic invariant | Generalizing the initial accumulator exposes the invariant |
| Find byte | `9d6338f` | Early-exit semantics and locals transition | A break requires both a semantic suffix theorem and a runtime state update |

These cases were selected and refined interactively, and their solutions remain
visible in the repository as examples available to the agent.  Reporting them
alongside the evaluation is useful qualitative evidence, but including them in
a success rate would bias the result.

### Development acceptance observation

On 2026-08-22, after implementing the AWS Bedrock adapter, one deliberately
unscored live run used `us.openai.gpt-5.6-sol` through the default profile in
`us-east-1` on the visible Byte OR calibration case.  It reached a verified
proposal in 19 typed actions, 8 retrievals, 3 checker executions, 12 model
invocations, and 67.3 controller seconds.  Bedrock reported 96,901 total tokens,
including 79,617 cache-read and 11,835 cache-write input tokens.

The trajectory was checker-driven rather than one-shot: one candidate failed
patch application, a second imported an inconsistent precompiled example and
failed frozen-target validation, and the third adapted the checked byte-OR
lemmas into a proof-local compiler rule.  That candidate changed only the
target module, reduced actionable residuals from one to zero, compiled, passed
`rocq check`, was closed under `Print Assumptions`, and left the source tree
unchanged.  The successful run used non-strict provider schemas with the local
typed parser still authoritative; a subsequent one-invocation smoke run
confirmed the adapter's required-but-nullable strict-schema encoding on the
same model profile.

This observation is not part of the primary results.  The calibration solution
was visible, prompts and controller limits were changed after earlier failed
runs, the model was selected after provider compatibility checks, and no fresh
trial protocol had been frozen.  Its purpose is to establish that the product
can execute a real remote propose/check/repair loop, not to estimate success
probability.

## 4. Evaluation units

A **task** is one frozen Rupicola derivation gap.  A **trial** is one fresh agent
session attempting that task from the same pinned repository state.  The task,
not an individual theorem or checker invocation, is the unit used for suite
coverage.

Each task bundle contains:

- `<Task>Spec.v`: the semantic program and independent specification;
- `<Task>Baseline.v`: an executable negative control that recognizes the stock
  compiler's expected residual classes and intentionally declares no theorem;
- `<Task>Benchmark.v`: the frozen public target, theorem type, and any required
  export contract, using an intentional `Abort` where a proof would otherwise
  be needed;
- `task.json`: frozen paths, hashes, public module interface, theorem names,
  build targets, budgets, and validation rules;
- a sealed reference solution, unavailable to the agent and scorer worktree;
- a sealed transfer case that imports the declared public module.

The specification, baseline, benchmark, task manifest, scorer, and build
configuration are read-only during a trial.  The manifest explicitly lists the
solution and integration paths the agent may create or edit.  The final theorem
is declared in one of those paths with the type fixed by the benchmark.  A patch
outside those paths invalidates the trial.

The reference solution is a feasibility check, not an answer key.  It must pass
the same soundness and clean-build gates before the task is admitted to the
suite, then remain sealed until all scored trials finish.

## 5. Held-out suite

The first suite contains eight tasks, two in each stratum:

| Stratum | Targeted gap | Easier member | Harder member |
|---|---|---|---|
| Expression compilation | Missing reusable `DEXPR` or scalar compiler rule | Close local repository analogue | Compose a semantic lemma with representation side conditions |
| Fold invariant | Compiler-shaped fold versus independent recursion | Accumulator invariant | Accumulator plus index or suffix relation |
| Control flow | `break`, `continue`, or early return | One early-exit transition | Semantic and locals-state obligations combined |
| Mutation and framing | Array update with separation-logic state | One in-place buffer | Conditional or two-buffer update with a nontrivial frame |

The descriptions above define task families, not the concrete held-out
programs.  Concrete tasks are chosen only after this protocol is frozen.  This
prevents the evaluation agent from rehearsing the actual solutions while the
benchmark is being designed.

Every admitted task must satisfy all of the following:

1. The stock compiler reaches the intended residual class and the negative
   control recognizes it exactly.
2. The task is semantically meaningful and is not a textual renaming of a
   calibration case.
3. The independent specification does not merely unfold to the implementation.
4. A sealed reference solution passes all strict validation gates.
5. The task can be solved without modifying Rupicola's trusted base or frozen
   files.
6. Repository and submodule commits, source hashes, and expected residuals are
   recorded before scoring.

Within each stratum, the first task should have a close structural analogue in
the repository and the second should require composition of at least two proof
ideas.  Once the suite manifest is signed, tasks may not be dropped or replaced
because an agent performs poorly on them.

## 6. Required configurations

The primary comparison has two configurations:

- **Stock:** deterministic Rupicola with no task-specific augmentation.  Its
  outcome is certified by `<Task>Baseline.v`; it is run once per task.
- **Agent:** the fixed LLM agent with local repository access and interactive
  Rocq feedback.  It is run in three fresh trials per task.

Thus the first evaluation has 8 stock checks and 24 agent trials.  Three trials
are enough to expose obvious instability, but not enough for fine-grained model
rankings.  Results are reported descriptively.

Potential later ablations include removing repository search, removing
interactive checker feedback, comparing model snapshots, and measuring a human
expert baseline.  They are not silently added to the primary experiment: each
changes the treatment and must use the same frozen tasks and its own declared
budget.

## 7. Fixed agent protocol

Each scored trial uses:

- a fresh conversation with no transcript or patch from another trial;
- a fresh disposable worktree at the pinned root and recursive submodule SHAs;
- the same committed system prompt, task prompt template, tools, and permission
  policy;
- the same model snapshot and reasoning configuration, recorded by the runner;
- read access to the pinned repository, including the three calibration cases;
- write access only to manifest-listed solution and integration paths;
- local shell, search, editor, build, and Rocq checker access;
- no internet, hidden solution, human hint, or communication with another agent.

The agent is allowed to use failed Rocq checks as feedback; that interaction is
the treatment being evaluated.  It may inspect repository history provided no
held-out solution has ever appeared in that history.

The v1 budget for one trial is:

- 60 minutes elapsed wall time;
- 120,000 total model input and output tokens;
- 60 agent-initiated checker executions.

The first limit reached stops the trial.  Checker executions performed later by
the scorer do not consume the agent's budget.  Queueing or runner outages are
recorded separately; ordinary compilation time is part of elapsed time.  If the
execution platform cannot enforce or report a token limit, that limitation must
be declared before the suite is run, and the wall-time and checker limits remain
binding.

The task-specific portion of the prompt is fixed to this shape:

```text
Augment Rupicola to complete the task described by <task.json>.
Preserve every frozen file and modify only the listed solution paths.
You may inspect the pinned repository and use local Rocq feedback.
The required theorem must pass the manifest's clean-build, assumption,
integrity, and generated-program checks within the declared budget.
Do not use unchecked assumptions or request human assistance.
```

Task semantics, paths, and theorem names come only from the manifest.  Prompt
changes made after observing a scored outcome create a new protocol version.

## 8. Trial procedure

The runner performs the following steps for every trial:

1. Materialize a clean worktree and recursively verify pinned submodule SHAs.
2. Hash every frozen file and run the stock negative control.
3. Start an append-only command, checker, token, and wall-clock log.
4. Give the fixed prompt and task manifest to a fresh agent session.
5. Stop when the agent declares completion or a budget is exhausted.
6. Save the transcript, event log, source patch, and their SHA-256 digests.
7. Apply only that patch to a second clean worktree at the same baseline.
8. Run the deterministic public scorer, then the sealed transfer scorer.
9. Emit one canonical `result.json` and classify any failure.

Rebuilding in a second worktree prevents generated `.vo` files, stale caches,
or unrecorded local state from making a trial appear successful.

An infrastructure failure may be rerun only when the runner failed before the
agent received useful task feedback.  Model errors, malformed tool calls,
timeouts, and checker failures are trial outcomes, not infrastructure reruns.

## 9. Strict validation gates

`core_success` is true only when all of these gates pass:

1. **Budget and scope:** the agent stopped within budget and changed only
   manifest-listed paths.
2. **Integrity:** all frozen SHA-256 values, repository commits, and recursive
   submodule SHAs match.
3. **Negative control:** stock compilation still reaches exactly the registered
   residual classes.
4. **Fresh compilation:** every submitted source compiles from the clean
   scorer worktree.
5. **Kernel check:** `rocq check -silent` accepts all submitted modules.
6. **Closed theorem:** `Print Assumptions` for every required theorem matches
   the task's frozen allowlist, which is empty by default.
7. **No escape hatch:** the patch introduces no `Admitted`, `admit`, `Axiom`,
   `Conjecture`, unapproved `Parameter`, unsafe plugin, unchecked cast, or
   equivalent bypass.  Text scanning is defense in depth; the assumptions and
   clean kernel checks are authoritative.
8. **Semantic target:** the required theorem connects the generated Bedrock2
   function to the frozen semantic program and independent specification.
9. **Generated-program shape:** manifest assertions find the required loads,
   stores, operations, branches, or loop-state transitions in the Bedrock2 AST.
10. **Dependency-aware build:** the manifest's targeted `make` goals pass from
    clean sources.

A repository-wide build is recorded as a secondary diagnostic because a pinned
revision may contain an unrelated failure.  Any such expected failure must be
registered before trials; it cannot be invented after seeing a result.

`transfer_success` is reported separately.  After the agent patch is frozen,
the sealed transfer case imports the manifest-declared public module and must
compile without edits to that augmentation.  The import contract may name
required identifiers or require behavior through Rupicola's registered hint
databases, but it may not depend on an interface invented after seeing the
patch.  A task can therefore achieve core success without transfer success.
Keeping the endpoints separate distinguishes proof completion from reusable
proof-engine improvement.

## 10. Measurements

The runner records, rather than reconstructs, the following values.

### Identity and environment

- task ID, stratum, difficulty member, and trial ID;
- root commit, recursive submodule SHAs, manifest hash, and scorer hash;
- model identifier or snapshot, reasoning configuration, prompt hash, tool
  versions, operating system, architecture, and hardware class;
- start and end timestamps.

### Outcome

- `core_success` and `transfer_success`;
- each validation gate's status and captured output digest;
- initial and final residual classes;
- exact assumptions reported for required theorems;
- failure stage and one primary failure class.

### Cost and interaction

- elapsed seconds and time to the first patch that passes the public scorer;
- input, output, cached, and total tokens when exposed by the platform;
- agent turns, tool calls, shell commands, and checker executions;
- checker-rejected edit states before the accepted state;
- added, deleted, and proof-source lines.

### Reuse artifact

- number and kind of exported lemmas, compiler rules, and hints;
- whether the sealed transfer case imported them unchanged;
- transfer checker time and residuals.

A checker-rejected edit state is a distinct source-tree digest followed by a
failing `rocq`, `coqc`, `make`, or public-scorer execution.  Repeating a check
without changing sources remains visible in the command log but does not count
as a new rejected edit state.

## 11. Failure taxonomy

Every unsuccessful valid trial receives one primary category based on its final
useful state:

- `representation_or_bounds`
- `semantic_invariant`
- `expression_compiler`
- `control_flow_or_locals`
- `separation_logic_or_frame`
- `integration_or_build`
- `assumption_or_escape_hatch`
- `frozen_artifact_modified`
- `budget_exhausted`
- `agent_or_tool_error`

`infrastructure_invalid` is not an agent failure and is used only under the
rerun rule in Section 8.  The event log retains secondary residual classes; the
single primary category is for compact reporting, not a claim that proof
failures always have one cause.

## 12. Result record

The runner writes one canonical JSON record per trial.  A separate JSON Schema
should be committed with the harness; the v1 logical shape is:

```json
{
  "schema_version": "1.0",
  "task": {
    "id": "control-01",
    "stratum": "control_flow",
    "manifest_sha256": "...",
    "root_commit": "...",
    "submodules": {"bedrock2": "..."}
  },
  "trial": {
    "id": 1,
    "configuration": "agent",
    "prompt_sha256": "...",
    "started_at": "...",
    "finished_at": "..."
  },
  "agent": {
    "model": "...",
    "snapshot": "...",
    "reasoning": "...",
    "tools_sha256": "..."
  },
  "budget": {
    "wall_seconds": 3600,
    "total_tokens": 120000,
    "checker_executions": 60
  },
  "usage": {
    "wall_seconds": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cached_tokens": 0,
    "checker_executions": 0,
    "rejected_edit_states": 0
  },
  "integrity": {
    "passed": false,
    "frozen_files": []
  },
  "validation": {
    "negative_control": false,
    "fresh_compile": false,
    "rocq_check": false,
    "assumptions": {"allowed": [], "actual": [], "passed": false},
    "generated_program": false,
    "targeted_build": false,
    "transfer": null
  },
  "residuals": {
    "initial": [],
    "final": []
  },
  "outcome": {
    "core_success": false,
    "transfer_success": null,
    "failure_stage": null,
    "failure_class": null
  },
  "diff": {
    "lines_added": 0,
    "lines_deleted": 0,
    "proof_lines": 0
  },
  "artifacts": {
    "patch_sha256": "...",
    "transcript_sha256": "...",
    "events_sha256": "..."
  }
}
```

The append-only event log is JSON Lines and contains timestamps, source-tree
digests, command classifications, exit statuses, and output digests.  Raw
transcripts and checker outputs are retained so aggregate results remain
auditable.

## 13. Analysis and reporting

The primary results are:

- successful agent trials out of 24;
- tasks solved in at least one trial out of 8;
- tasks solved in all three trials out of 8;
- transfer successes among core-successful trials;
- success counts by the four strata.

For successful trials, report median and range for wall time, tokens, checker
executions, rejected edit states, and proof lines.  Also show failures at their
budget cap rather than silently omitting them from cost plots.  With only eight
tasks and three trials per task, avoid null-hypothesis significance claims and
fine-grained model rankings; show every task-level result and exact numerators
and denominators.

Qualitative reporting includes the final residual, the failure category, the
augmentation's reusable interface, and a short account of checker-driven
refinement.  Any manual failure adjudication is done from the recorded artifacts
under a written rubric and does not alter automated success gates.

## 14. Validity risks and mitigations

- **Task-selection bias:** freeze all eight tasks and feasibility certificates
  before scoring, then report every admitted task.
- **Calibration leakage:** treat the three existing studies as visible training
  examples and exclude them from measured outcomes.
- **Held-out leakage:** never place reference solutions in reachable branches,
  worktrees, prompts, caches, or repository history.
- **Model drift:** pin a model snapshot when possible.  Otherwise record the
  service version and date and run the complete batch in a short declared
  window.
- **Trial dependence:** use fresh sessions and worktrees.  Do not describe trials
  as statistically independent if the service does not expose sampling seeds.
- **Stale build state:** score the saved patch in a second clean worktree.
- **Unsound shortcuts:** enforce frozen hashes, an assumption allowlist,
  forbidden-construct scanning, `rocq check`, and clean builds.
- **Benchmark overfitting:** score a sealed transfer case separately from the
  visible primary derivation.
- **Tooling confound:** pin prompts, tools, permissions, budgets, and the scorer;
  record any deviation as a new protocol version.
- **End-to-end overclaim:** distinguish a proved Bedrock2 function from merely
  inspected C output and from downstream compiled code.

## 15. Implementation order

1. Commit and tag this protocol.
2. Implement the runner, event logger, public scorer, and `result.schema.json`.
3. Prepare and feasibility-check two sealed tasks per stratum.
4. Commit and publish the digest of the suite manifest containing every task
   and artifact digest.
5. Run the 8 stock controls and 24 agent trials without protocol adaptation.
6. Publish all result records, patches, transcripts, scorer outputs, and the
   aggregate report.

No held-out outcome should be interpreted until steps 1 through 4 are complete.
That boundary turns the existing demonstrations into a reproducible evaluation
instead of a sequence of selectively reported case studies.
