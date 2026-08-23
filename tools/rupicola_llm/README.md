# `rupicola-llm` diagnostic and checked-solve prototype

This directory implements Phase 1 and a controller-first slice of Phase 2 from
[`LLM_DESIGN.md`](../../LLM_DESIGN.md).  It can replay an incomplete Rupicola
derivation, classify the residual goals left by the stock compiler, run a
provider-neutral bounded repair loop, and check every candidate patch in an
isolated source copy.  Its concrete AWS Bedrock Converse adapter can drive that
loop through an authenticated AWS CLI profile without adding an SDK dependency.

The deterministic scripted provider remains the controller acceptance harness.
Neither provider applies a proposal to the user's source tree.

For a newcomer-friendly walkthrough that assumes no Rupicola or Rocq
experience, start with [`LLM_TUTORIAL.md`](../../LLM_TUTORIAL.md).  This README
is the command and implementation reference.

## Requirements

- Python 3.10 or newer;
- Git, for pinned repository identity and unchanged-worktree validation;
- the project's pinned `rocq` executable;
- `coqidetop` from the matching Rocq installation;
- coherent `.vo` artifacts for the selected source and its dependencies.

Remote Bedrock runs additionally require:

- AWS CLI v2 with an authenticated profile and configured region;
- access to the selected model or inference profile;
- IAM permission for `bedrock:InvokeModel` through the Converse API.

The implementation uses only Python's standard library.  The Rocq interaction
is isolated behind `CoqIdeDriver`, so it can later be replaced by a Rocq LSP or
SerAPI adapter.  Bedrock credentials remain in the normal AWS credential chain;
the sidecar never reads or serializes them.

## Quick start

Run these commands from the repository root.  Start by inspecting a real
residual without invoking a model or editing source:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMFindByteBaseline.v \
    --theorem baseline_find_byte_br2fn_ok
```

Then exercise the complete bounded controller and isolated checker with the
deterministic Byte OR script:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --agent-script tools/tests/fixtures/byte_or_agent.json \
    --scope project \
    --max-actions 8 \
    --max-checks 2
```

The command prints a run ID.  Inspect the result with
`tools/rupicola-llm show <run-id>` or read its artifacts below
`.rupicola/llm/runs/<run-id>/`.  The proposal remains unapplied.  Continue to
the [AWS Bedrock workflow](#aws-bedrock-workflow) only when remote source
disclosure and provider charges are acceptable.

## Diagnose workflow

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
source tree, and runs it through the same gates used for remote-model
proposals:

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

## Bounded agent workflow

`solve --agent-script` runs typed provider actions through the bounded
controller.  The included Byte OR fixture searches and reads a relevant local
compiler analogue, inspects the live obligation, proposes an unsafe axiom as a
negative control, observes its policy rejection, and repairs it with the
verified project extension:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --agent-script tools/tests/fixtures/byte_or_agent.json \
    --scope project \
    --max-actions 8 \
    --max-checks 2

Run 20260823-001234-baseline-byte-or-scalar-br2fn-ok-0123abcd
  status:    verified
  residuals: 1 -> 0
  proposal:  .../.rupicola/llm/runs/.../proposal.patch
  source tree unchanged; proposal is ready for review
```

The provider interface exposes only seven typed actions: `search`, `read`,
`inspect_obligation`, `propose_patch`, `check`, `revert_candidate`, and
`finish`.  Repository reads are restricted to disclosed Rocq source roots,
patches are parsed and scope-checked before checking, and checker commands are
never provider-authored.  Exact checker-failed patch digests are not checked
twice.  The action, check, and wall-time budgets are configurable and recorded.

The scripted provider consumes a versioned JSON `actions` array.  Its
`patch_file` shorthand is resolved only below the script directory and expanded
to the same `unified_diff` argument returned by the Bedrock adapter.  It is a
deterministic development adapter, not an LLM substitute.

Each controller run retains `context.initial.json`, `tools.json`,
patch-redacted `events.jsonl`, append-only `attempts.jsonl`, every exact
proposal, nested checker runs and logs, the selected `proposal.patch`,
`validation.json`, and a human-readable summary.  Proposal bodies stay out of
the action transcript but remain available as separately hashed artifacts.  A
provider failure exits with status `5`; an exhausted, rejected, or unsolved run
exits with status `4`.

Both `fast` and `final` are accepted protocol modes in this slice, but `fast`
currently executes and reports the stricter final pipeline.  This preserves
the trust boundary while a genuinely incremental checker is still pending.

### Inspecting or recovering an exhausted run

Exit status `4` does not necessarily mean that the provider failed to produce a
patch.  An exhausted run retains every proposal and, when one was staged, puts
the last selected proposal in `proposal.patch`.  That file is untrusted and may
not have consumed a checker attempt; do not treat it as verified unless
`validation.json` and `show` report `verified`.

The current prototype has no automated `resume` command.  To check a saved
proposal without another provider invocation, submit it through the
model-independent boundary in a new run:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --candidate-patch .rupicola/llm/runs/<run-id>/proposal.patch \
    --scope project
```

If more model interaction is required, start a fresh `solve --provider
bedrock` run with newly chosen budgets.  Automatic child-run resume remains
later Phase 2 work.

## AWS Bedrock workflow

`solve --provider bedrock` sends the initial proof context and subsequently
requested Rocq source through the Bedrock Converse API.  Remote disclosure is
never implicit: the command stops before reading the target unless
`--allow-remote-source` is present.

Confirm the intended AWS identity and configured region before the first paid
run:

```console
$ aws sts get-caller-identity --profile default
$ aws configure get region --profile default
```

The following is a deliberately small smoke run on the visible Byte OR
calibration case:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --provider bedrock \
    --model-id us.openai.gpt-5.6-sol \
    --aws-profile default \
    --aws-region us-east-1 \
    --allow-remote-source \
    --scope project \
    --max-actions 8 \
    --max-retrievals 3 \
    --max-checks 2 \
    --wall-seconds 120 \
    --provider-timeout 60 \
    --bedrock-max-tokens 2048
```

Replace the model, profile, and region with values available to the intended
AWS account; omit `--aws-region` to use the configured default.

Model and inference-profile availability is account- and region-specific.  The
region defaults to `AWS_REGION`, `AWS_DEFAULT_REGION`, or the selected profile's
configured region, in that order.  Temperature is omitted by default because
not every Converse model accepts it; pass `--bedrock-temperature` only for a
model that does.  Strict Bedrock tool schemas are enabled by default.  Optional
controller fields are represented as required-but-nullable at that boundary
and normalized back to local defaults.  `--bedrock-no-strict-tools` is a
compatibility escape hatch, but the local protocol parser still rejects unknown
tools, unexpected fields, wrong types, unsafe paths, and out-of-range values.

`--bedrock-max-tokens` is a per-response output limit, not a whole-run token or
cost ceiling.  Action, check, retrieval, provider-timeout, and wall-time limits
bound other dimensions of a run, but the current adapter cannot enforce an
aggregate provider token or currency budget.  Inspect the recorded usage in
`run.json` and use the AWS account's normal billing controls.

The transport writes each request to a mode-restricted temporary file, invokes
the AWS CLI with a fixed argument vector and no shell, enforces a process-group
timeout, bounds diagnostic output, and removes the request file.  The model has
no shell or filesystem handle.  It can only request the seven controller tools;
the controller executes them within its own path, action, retrieval, check, and
wall-time limits.  Parallel model calls are not executed: at most four
independent read-only calls from one response are serialized, and any batch
containing a patch, check, revert, or finish action is rejected.

Every remote run writes `disclosure.json` with the provider, model, profile,
region, context hash and size, initial evidence paths, readable roots, and
secret-scan status.  The remote copy removes known absolute project, load-path,
and local executable fields while the full diagnostic stays local; the manifest
lists each removed JSON path.  A high-confidence credential scan runs before
every request and blocks likely private keys, cloud access keys, API tokens,
and assigned secrets without echoing their values.  This is defense in depth,
not a complete data-loss-prevention system.  The client does not inspect the
AWS account's model-invocation logging configuration; review that account
setting before sending confidential source.  AWS documents both its
[Bedrock data-protection model](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html)
and the optional
[model-invocation logging feature](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html).

Provider audit data is attached to `events.jsonl`: invocation number, model,
region, stop reason, requested tool names, token usage, service latency, and
request ID when the CLI exposes it.  `run.json` also records the system-prompt
hash and aggregate invocation, token, and model-latency totals.  These records
never decide whether a patch passes; only the local policy and Rocq validation
pipeline can do that.

### Unscored live calibration

On 2026-08-22, a development run using the default AWS profile in `us-east-1`
and `us.openai.gpt-5.6-sol` verified the Byte OR calibration gap.  The run used
19 typed actions, all 8 allowed retrievals, 3 isolated checks, and 12 model
invocations over 67.3 controller seconds.  Bedrock reported 96,901 total tokens:
1,452 uncached input, 79,617 cache-read input, 11,835 cache-write input, and
3,997 output tokens.

The first checked patch did not apply.  The second imported a stale compiled
example and failed the frozen-target gate.  The third adapted the checked lemmas
into a proof-local rule; it closed the residual from 1 to 0 and passed source
policy, target integrity, compilation, `rocq check`, an empty `Print
Assumptions` result, and unchanged-source verification.  A subsequent bounded
smoke run confirmed that the OpenAI profile accepts the adapter's portable
strict schema.

This is qualitative development evidence, not an efficacy measurement: the
solution was visible as a calibration analogue, adapter prompts and limits had
already been tuned on failed runs, and the model configuration was selected
after compatibility testing.  The preregistered methodology for scored trials
remains [`LLM_EVAL.md`](../../LLM_EVAL.md).

## Stale build artifacts

If Rocq reports inconsistent compiled assumptions, the command resolves both
logical library names through `_CoqProject` and reports their concrete `.vo`
paths and timestamps.  It stops instead of presenting the build failure as a
proof residual.

The command never rebuilds automatically.  Rebuild the reported library and
its dependents with the project's normal build system, then rerun the failed
command.  A full rebuild from the repository root is the safest option:

```console
$ make -j
```

For a named Rupicola module already present in `_CoqProject`, the generated
makefile uses an absolute `.vo` target.  Rebuild only that module by passing the
absolute path reported by the diagnostic; for example:

```console
$ make -f Makefile.coq \
    "$(pwd)/src/Rupicola/Examples/LLMByteOrCompiler.vo"
```

Do not rely on a relative `make src/...vo` invocation: the top-level wrapper can
match a different target without rebuilding the generated makefile's absolute
module target.  If rebuilding one module reveals another inconsistent
dependency, use the full build instead.

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
find-byte gaps, stable fingerprints across fresh proof sessions, a Byte OR
candidate that passes the isolated compile, kernel, assumptions, and unchanged
source-tree gates, and a live two-attempt agent run that rejects an axiom before
verifying its repaired patch.

The default and calibration suites mock the Bedrock transport and never make a
paid network call.  Remote acceptance is an explicit manual run so CI cannot
silently disclose source or incur model charges.

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
- The Bedrock gateway currently uses AWS CLI subprocesses rather than an SDK;
  it has bounded timeouts but no streaming, service retry policy, or aggregate
  token/cost ceiling beyond the action and wall-time budgets.
- The disclosure scan intentionally targets high-confidence credential shapes.
  It does not perform semantic redaction, enforce repository-specific deny
  lists, or inspect the account's optional Bedrock invocation-logging setting.
- Model families differ in supported Converse inference parameters.  The
  adapter omits temperature by default and offers strict/automatic tool-choice
  compatibility flags, but does not yet maintain a capability registry.
- Each attempt starts from a fresh isolated source copy, but the additional
  final replay in a distinct second workspace remains to be implemented.
- Exhausted runs retain their last staged proposal, but automated child-run
  resume remains later Phase 2 work.
- `verify` and explicit `apply` remain later Phase 2 work.
