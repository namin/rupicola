# LLM-assisted proof repair in Rupicola: a hands-on tutorial

This tutorial introduces Rupicola and its experimental `rupicola-llm` sidecar
from first principles.  It assumes basic command-line and Git familiarity, but
does **not** assume knowledge of Rupicola, Rocq/Coq, Gallina, Bedrock2, proof
tactics, or relational compilation.

Plan on 20–30 minutes for the local tutorial.  The final AWS Bedrock section is
optional, sends explicitly disclosed source context to a remote model, and may
incur provider charges.

By the end, you will be able to:

- explain what Rupicola compiles and what a residual proof goal means;
- diagnose a one-goal compiler gap without invoking a model;
- run a deterministic propose/reject/repair/check loop;
- inspect the resulting patch, proof obligations, audit trail, and validation
  gates;
- understand why the model is outside the trusted computing base;
- optionally run the same bounded controller through AWS Bedrock; and
- recover a saved proposal after budget exhaustion or stale build artifacts.

## Safety and cost at a glance

The first two parts are local and deterministic:

- `diagnose` is read-only;
- the scripted agent does not call an LLM or network service;
- candidate patches are applied only inside disposable source copies;
- run evidence is written below the Git-ignored `.rupicola/llm/runs/`; and
- this prototype has no `apply` command, so the tutorial never installs a
  proposal into the tracked source tree.

The optional Bedrock part is different:

- `--allow-remote-source` authorizes sending the initial proof context and
  subsequently requested Rocq source to the configured Bedrock model;
- the provider may charge for uncached, cached, and output tokens;
- `--bedrock-max-tokens` limits each response, not the aggregate run; and
- the built-in secret scan is defense in depth, not a complete data-loss
  prevention system.

Use only the included public calibration case until you understand those
boundaries.

## 1. Rupicola in five minutes

### Rocq and checked proofs

Rocq, formerly called Coq, is a proof assistant.
Rocq source files use the `.v` extension and contain definitions, programs,
theorem statements, and proof scripts.  Its small kernel checks the completed
proof term.  A tactic, automation framework, or LLM may help construct a proof,
but none can make an invalid proof pass the kernel.

The functional language used for definitions is commonly called Gallina.  You
do not need to learn Gallina syntax for this tutorial; you only need to
recognize that the definitions in the example are the source program and its
mathematical specification.

### Bedrock2 and Rupicola

Bedrock2 is a mechanized low-level imperative language.  It has commands,
locals, memory operations, functions, and a formal operational semantics.

Rupicola is a **relational compiler** built in Rocq.  Rather than trusting a
standalone compiler executable, Rupicola uses proved compiler rules and tactics
to synthesize both:

1. a Bedrock2 function; and
2. a theorem that the generated function implements the source program's
   specification.

The simplified flow is:

```text
functional definition + specification
                 |
                 v
        Rupicola compiler tactics
          /                  \
         v                    v
Bedrock2 function       correctness theorem
                               |
                               v
                         Rocq kernel check
```

Rupicola's compiler is extensible.  Its rules know how to compile common
expressions, loops, memory operations, and control flow.  When no applicable
rule exists—or when a loop needs a semantic invariant—the tactics stop with a
**residual proof goal**.  The part already compiled remains useful; the
residual precisely describes the missing fact or compiler extension.

### Where the LLM fits

`rupicola-llm` is an external sidecar around that failure point:

```text
Rupicola residual
       |
       v
classify and retrieve local examples
       |
       v
untrusted scripted or LLM provider proposes a patch
       |
       v
scope and proof-safety policy
       |
       v
isolated compilation, replay, assumptions probe, and kernel check
```

The provider does not receive a shell or a general filesystem handle.  It can
request seven typed operations: `search`, `read`, `inspect_obligation`,
`propose_patch`, `check`, `revert_candidate`, and `finish`.  The controller—not
the provider—chooses checker commands and enforces path and budget limits.

The central trust claim is modest: an LLM proposal is treated like any other
untrusted patch.  Only a patch accepted by the local policy, build, replay,
assumptions probe, and Rocq kernel is reported as verified.

## 2. The Byte OR calibration case

The tutorial uses a deliberately small, visible development case.  It is a
**calibration case**, not held-out evaluation data.  The answer and neighboring
analogue are already present in the repository so that the diagnostic and
controller behavior can be tested reproducibly.

The source operation is byte-sized bitwise OR:

```coq
Definition byte_or (x y : byte) : byte :=
  byte.of_Z (Z.lor (byte.unsigned x) (byte.unsigned y)).

Definition byte_or_scalar (x y : byte) :=
  let/n r := byte_or x y in
  r.
```

At a high level, `byte.unsigned` views each byte as an integer, `Z.lor`
computes integer bitwise OR, and `byte.of_Z` wraps the result back into a byte.

The accompanying function specification says that the two machine-word inputs
encode bytes `x` and `y`; execution leaves the trace and memory unchanged; and
the returned word encodes `byte_or_scalar x y`.  The baseline's `Derive`
command asks Rupicola to synthesize a Bedrock2 function (named with the local
`br2fn` convention) and prove that it implements this specification.

The relevant files are:

| File | Role |
|---|---|
| `src/Rupicola/Examples/LLMByteOrSpec.v` | Functional program used by both baseline and solution |
| `src/Rupicola/Examples/LLMByteOrBaseline.v` | Executable negative control that stops at the intended compiler gap |
| `src/Rupicola/Examples/LLMByteOrCompiler.v` | Visible, checked development analogue for the missing compiler rule |
| `tools/tests/fixtures/byte_or_agent.json` | Deterministic sequence of provider actions |
| `tools/tests/fixtures/unsafe_candidate.patch` | Deliberately forbidden negative-control patch |
| `tools/tests/fixtures/byte_or_candidate.patch` | Checked project-scoped repair used by the scripted provider |

The baseline intentionally does **not** import the Byte OR compiler extension.
Its proof runs the stock compiler, checks that the expected residual appears,
and ends with `Abort`.  That `Abort` is not a hidden failure: it makes the file
an executable negative control without exporting an unfinished theorem.

## 3. Preflight

Run every command from the repository root.  Confirm the location, branch, and
tool version:

```console
$ pwd
/path/to/rupicola

$ git status --short --branch
## llm-case-studies...my/llm-case-studies

$ tools/rupicola-llm --version
rupicola-llm 0.4.0
```

Your branch name may differ.  Existing worktree changes are allowed, but note
them now so you can confirm later that the sidecar did not change them.

The prototype expects Python 3.10 or newer, Git, the project's pinned `rocq`
and `coqidetop` executables, and coherent compiled `.vo` dependencies.  If the
repository has not been built, build it using its normal setup:

```console
$ make -j
```

Run the fast sidecar suite:

```console
$ tools/test-rupicola-llm
...................sssss....................................
----------------------------------------------------------------------
Ran 60 tests in ...s

OK (skipped=5)
```

The five skipped tests are the repository calibration checks.  To include
them, use:

```console
$ RUPICOLA_LLM_CALIBRATION=1 tools/test-rupicola-llm -v
```

Both test commands mock the Bedrock transport.  They do not disclose source to
a remote model or incur a paid model call.

## 4. Part one: diagnose the compiler gap

Run the read-only diagnostic:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok
```

The important part of the output looks like this:

```text
Rupicola diagnosis: src/Rupicola/Examples/LLMByteOrBaseline.v::baseline_byte_or_scalar_br2fn_ok
1 residual after compile_step saturation
2 total goals captured (1 auxiliary witness)
  1  expression_compilation     focused    02286ebdede7
     DEXPR mem0 (map.of_list [("y", word_of_byte y); ("x", word_of_byte x)]) ?e (word_of_byte (byte_or x y))
     evidence: expr_compile_byte_or (src/Rupicola/Examples/LLMByteOrCompiler.v:31)
     evidence: byte_or (src/Rupicola/Examples/LLMByteOrSpec.v:7)
  2  internal_synthesis_witness shelved    ...
     expr
```

Read this from the outside in:

- `1 residual` means stock compilation left one actionable obligation.
- `expression_compilation` is the deterministic classifier's category.
- `focused` means it is the current proof goal.
- The hexadecimal prefix is a stable fingerprint used to compare goals across
  attempts.
- The `shelved` `expr` goal is an auxiliary synthesis witness, not a second
  actionable compiler gap.
- The evidence lines are repository declarations ranked as likely analogues.

Operationally, read

```coq
DEXPR mem0 locals ?e (word_of_byte (byte_or x y))
```

as: “construct a Bedrock2 expression `?e` that, in this memory and local
environment, computes the machine-word representation of `byte_or x y`.”
Rupicola already knows the runtime values of `x` and `y`; it lacks the rule
connecting semantic byte OR to a Bedrock2 word-level OR expression.

The diagnostic has already found the likely missing rule,
`expr_compile_byte_or`, in the visible development analogue.  Retrieval is
evidence, not acceptance: the declaration still has to be used in a patch that
passes all validation gates.

To inspect the baseline proof directly:

```console
$ sed -n '1,90p' src/Rupicola/Examples/LLMByteOrBaseline.v
```

Near the end:

- `compile_setup` initializes the relational compilation proof;
- repeated `compile_step` calls apply stock compiler rules;
- `lazymatch` asserts that compilation stopped at the intended `DEXPR` shape;
  and
- `Abort` deliberately avoids declaring the incomplete theorem.

For the complete versioned diagnostic record, use JSON:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --json | python3 -m json.tool
```

That record includes repository and submodule identities, source hashes, Rocq
version, replay boundary, all focused and auxiliary goals, fingerprints,
classifications, and ranked evidence.

## 5. Part two: run the deterministic repair loop

Now exercise the agent controller without an LLM:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --agent-script tools/tests/fixtures/byte_or_agent.json \
    --scope project \
    --max-actions 8 \
    --max-checks 2
```

This typically takes several seconds because the final gate invokes `rocq
check`.  Expected output has this shape:

```text
Run 20260823-...-baseline-byte-or-scalar-br2fn-ok-...
  status:    verified
  residuals: 1 -> 0
  proposal:  .../.rupicola/llm/runs/<run-id>/proposal.patch
  source tree unchanged; proposal is ready for review
```

Despite the name “agent,” this run is completely deterministic.  The JSON
fixture supplies seven typed actions:

1. search for `expr_compile_byte_or`;
2. read the visible compiler analogue;
3. inspect the live obligation;
4. propose a file containing `Axiom escape : True`;
5. ask the checker to reject that unsafe proposal;
6. propose a project-scoped generated compiler extension; and
7. ask the final checker to validate the repaired patch.

The unsafe proposal is a negative control.  A new axiom could assert a fact
without proof, so accepting one would invalidate the trust story.  Policy
rejects it before candidate compilation.  The second proposal instead proves
the byte-to-word semantic bridge, proves the `DEXPR` compiler rule, registers a
narrow compiler hint, imports that support module, and completes the original
derivation.

### Inspect the run

Copy the actual run ID from your output into a shell variable.  Do not include
angle brackets:

```console
$ run_id=PASTE_RUN_ID_HERE
$ tools/rupicola-llm show "$run_id"
```

The summary should report `verified`, `1 -> 0`, and a list of passed checks.
The run directory contains:

| Artifact | Meaning |
|---|---|
| `summary.md` | Concise human-readable result |
| `run.json` | Versioned run identity, limits, provider metadata, and totals |
| `context.initial.json` | Initial local proof context |
| `obligations.initial.json` | Initial focused and auxiliary obligations |
| `events.jsonl` | Append-only typed action and observation transcript |
| `attempts.jsonl` | One record per checker attempt |
| `proposals/` | Every exact proposed patch |
| `proposal.patch` | Selected final proposal, still unapplied |
| `validation.json` | Machine-readable validation gates and residual delta |
| `checks/` | Nested isolated checker runs and their logs |

Read the most useful artifacts with standard tools:

```console
$ sed -n '1,240p' ".rupicola/llm/runs/$run_id/summary.md"
$ sed -n '1,240p' ".rupicola/llm/runs/$run_id/attempts.jsonl"
$ sed -n '1,260p' ".rupicola/llm/runs/$run_id/proposal.patch"
$ python3 -m json.tool ".rupicola/llm/runs/$run_id/validation.json"
```

The two lines in `attempts.jsonl` should show a rejected unsafe patch followed
by a verified repair.  The final proposal changes two paths only:

- the selected baseline proof; and
- `src/Rupicola/Generated/LLMByteOrSupport.v`, the allowed project-extension
  area.

### Understand the validation gates

The final patch is called verified only if all of these pass:

| Gate | What it protects |
|---|---|
| `initial_diagnosis` | Establishes the original residuals before editing |
| `scope_policy` | Restricts changed paths to the selected source and allowed extension area |
| `patch_application` | Applies the diff only inside a disposable source copy |
| `source_policy` | Rejects new assumptions, proof escape hatches, unsafe commands, and broad hints |
| `frozen_target` | Confirms the elaborated theorem obligation did not change |
| `candidate_compile` | Compiles every changed Rocq module |
| `residual_closure` | Requires all focused and auxiliary goals to close |
| `kernel_check` | Runs `rocq check` on every changed module |
| `assumptions` | Requires the target theorem to be closed under the configured global context |
| `source_tree_unchanged` | Confirms the user's source state matches its pre-run fingerprint |

In the current prototype, a requested `fast` check executes the stricter final
pipeline.  A genuinely incremental checker remains future work.

### Confirm that the source was not changed

Compare Git state with the preflight result:

```console
$ git status --short --branch
```

Any changes that existed before the run should still be present, and the
proposal itself should not appear as a worktree edit.  The `.rupicola/`
directory is ignored by Git.

### Recheck the saved proposal without a provider

You can submit the selected patch through the model-independent checker.  This
creates a new audited run but invokes neither the scripted provider nor
Bedrock:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --candidate-patch ".rupicola/llm/runs/$run_id/proposal.patch" \
    --scope project
```

This boundary is also how to validate the last staged proposal from an
exhausted live run.

## 6. Part three: optional AWS Bedrock run

Stop here if you only wanted to understand and test the local trust boundary.
Everything above exercised diagnosis, retrieval, proposal policy, isolated
checking, residual closure, assumptions checking, and kernel acceptance.

Continue only if all of the following are true:

- AWS CLI v2 is installed and authenticated;
- the selected account and region can invoke the chosen Bedrock model or
  inference profile;
- sending the included calibration source to that provider is acceptable; and
- provider charges are acceptable.

### Confirm AWS identity and region

```console
$ aws sts get-caller-identity --profile default
$ aws configure get region --profile default
us-east-1
```

Inspect the returned account and ARN.  Replace `default`, `us-east-1`, and the
model ID below when your authorized profile differs.

### Understand disclosure before consenting

`--allow-remote-source` is required for every remote run.  The remote context
removes known absolute project, load-path, and executable fields.  A
high-confidence credential scan runs before every request and blocks likely
private keys, cloud access keys, API tokens, and assigned secrets without
echoing their values.

This does not provide semantic redaction or inspect the AWS account's optional
Bedrock model-invocation logging setting.  Review that account configuration
before using confidential source.  Every remote run records a local
`disclosure.json` describing the provider, model, region, context hash and
size, readable roots, evidence paths, removed fields, and scan result.

### Run a bounded smoke test

This command uses the visible Byte OR calibration case and deliberately small
budgets:

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

The limits mean:

- at most eight controller actions;
- at most three read-only search, source-read, or obligation-inspection
  actions;
- at most two isolated checker executions;
- at most 120 controller seconds;
- at most 60 seconds for one provider response; and
- at most 2,048 output tokens in each provider response.

They do **not** impose an aggregate input-token or currency ceiling.  In
particular, cached input and cache-write tokens can make the provider-reported
total much larger than `--bedrock-max-tokens`.  Use AWS billing controls and
inspect the exact usage recorded in `run.json`.

### Interpret the outcome

A live run is not deterministic.  Common outcomes are:

| Exit/status | Meaning | Next step |
|---|---|---|
| `0` / `verified` | A candidate passed every configured gate | Review `summary.md`, `validation.json`, and `proposal.patch` |
| `4` / `exhausted` | An action, check, or wall-time budget ended first | Inspect the last staged proposal; it may be unchecked |
| `4` / `rejected` or `unsolved` | No candidate passed | Read `events.jsonl`, `attempts.jsonl`, and checker logs |
| `5` / provider failure | Authentication, transport, schema, or provider response failed | Inspect the recorded provider diagnostic; do not assume a proof failure |
| `2` or `3` | Project/source usage or Rocq environment failed | Correct the local environment before spending another model call |

Always inspect the run using its ID:

```console
$ run_id=PASTE_LIVE_RUN_ID_HERE
$ tools/rupicola-llm show "$run_id"
$ python3 -m json.tool ".rupicola/llm/runs/$run_id/run.json"
$ sed -n '1,260p' ".rupicola/llm/runs/$run_id/events.jsonl"
```

`run.json` records invocation count, model and region, service latency, and
uncached input, cache-read input, cache-write input, output, and total tokens
when Bedrock reports them.

### Recover an exhausted proposal locally

An exhausted run may have staged a useful final proposal immediately before
the budget ended.  Its `proposal.patch` is **not** verified merely because the
file exists.  Check whether it is nonempty:

```console
$ test -s ".rupicola/llm/runs/$run_id/proposal.patch" \
    && echo "a proposal was saved"
```

Then validate it without another provider call:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --candidate-patch ".rupicola/llm/runs/$run_id/proposal.patch" \
    --scope project
```

The current CLI does not implement automated conversational resume.  If the
saved patch fails and more model interaction is desired, start a fresh bounded
Bedrock run.  Do not silently increase budgets during a scored evaluation; the
Byte OR exercise here is unscored calibration only.

## 7. Troubleshooting

### “Makes inconsistent assumptions over library ...”

Rocq `.vo` files are compiled proof artifacts.  If a dependency was rebuilt
after one of its consumers, the consumer can contain stale assumptions.  The
sidecar reports both logical library names, concrete `.vo` paths, and
timestamps instead of misclassifying this as a proof residual.

The safest repair is a normal full rebuild:

```console
$ make -j
```

To rebuild one Rupicola module already present in `_CoqProject`, pass the
absolute `.vo` target printed by the diagnostic to the generated makefile.  For
example:

```console
$ make -f Makefile.coq \
    "$(pwd)/src/Rupicola/Examples/LLMByteOrCompiler.vo"
```

Do not rely on `make src/Rupicola/Examples/LLMByteOrCompiler.vo`; the top-level
wrapper can match a different relative target without rebuilding the generated
makefile's absolute module target.  If another dependency is then reported as
stale, use the full build.

### The Bedrock model or inference profile is unavailable

Availability is specific to the AWS account and region.  Confirm the profile,
region, IAM permission for `bedrock:InvokeModel`, and model or inference-profile
ID.  Omit `--aws-region` to use `AWS_REGION`, `AWS_DEFAULT_REGION`, or the
selected profile's configured region.

### A patch does not apply

This is an ordinary checker rejection, not a source-tree failure.  The
controller reverts the isolated candidate, records the exact failing hunk and
source location, and may allow the provider to propose a corrected patch if
budgets remain.  The user's source remains unchanged.

### The run reports `exhausted`

Inspect `events.jsonl` to see which limit ended the run and `run.json` for
`actions_used`, `checks_used`, `retrievals_used`, and elapsed time.  A final
`proposal.patch` may exist but must be rechecked as described above.

### The provider wants a “fast” check

The controller accepts `fast` and `final`, but the current implementation runs
and records the final pipeline for both.  This preserves the trust boundary at
the expense of incremental speed.

## 8. Safe follow-up exercises

These exercises use only visible calibration cases.

### Compare residual classes

Count-byte compilation leaves representation and semantic-invariant gaps:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMCountByteBaseline.v \
    --theorem baseline_count_byte_br2fn_ok
```

Find-byte compilation combines representation, control-flow/locals, and
semantic-invariant gaps:

```console
$ tools/rupicola-llm diagnose \
    src/Rupicola/Examples/LLMFindByteBaseline.v \
    --theorem baseline_find_byte_br2fn_ok
```

Compare the residual counts, classifications, and ranked evidence.  Then add
`--json` and compare the versioned records.

### Trigger local budget exhaustion deliberately

The deterministic fixture requires seven actions.  Run it with only six:

```console
$ tools/rupicola-llm solve \
    src/Rupicola/Examples/LLMByteOrBaseline.v \
    --theorem baseline_byte_or_scalar_br2fn_ok \
    --agent-script tools/tests/fixtures/byte_or_agent.json \
    --scope project \
    --max-actions 6 \
    --max-checks 2
```

It should exit with status `4` after staging the repaired proposal but before
its final check.  Inspect that run and validate its saved `proposal.patch`
through `--candidate-patch`.  This rehearses live-run recovery without network
access or cost.

### Audit the trust boundary

Open the two fixture patches and answer:

1. Why is `Axiom escape : True` rejected even though Rocq can parse it?
2. Why is `src/Rupicola/Generated/LLMByteOrSupport.v` allowed in `project`
   scope but not `local` scope?
3. Which gate prevents a candidate from weakening or changing the theorem it
   claims to prove?
4. Which two gates provide the final proof-checking evidence?

The relevant answers are, respectively: assumptions undermine proof closure;
project scope has a narrow generated-extension area; `frozen_target` preserves
the theorem obligation; and `kernel_check` plus `assumptions` provide the final
logical evidence.

## 9. Glossary

- **Assumption:** A fact accepted without a proof in the current logical
  environment.  The tutorial's target theorem must be closed under the
  configured global context.

- **Bedrock2:** A mechanized imperative language and semantics used as
  Rupicola's target.  It is unrelated to the AWS Bedrock model-hosting service
  despite the shared word “Bedrock.”

- **Calibration case:** A visible development example used to shape and test
  the tool.  It must not be counted as held-out evidence of model success.

- **Compiler rule:** A proved lemma or registered hint that tells Rupicola how
  to relate a source construct to Bedrock2 code.

- **`DEXPR`:** Rupicola's expression-compilation relation.  In this tutorial it
  asks for a Bedrock2 expression computing the word representation of byte OR.

- **Gallina:** Rocq's functional language for definitions and programs.

- **Kernel:** Rocq's small trusted proof checker.  Tactics and models may
  construct proof terms, but the kernel decides whether they are valid.

- **Proof obligation / residual goal:** A proposition still requiring proof
  after current automation stops.  A residual often identifies a missing
  compiler rule, invariant, or state transition.

- **Rocq / Coq:** The proof assistant used by Rupicola.  Rocq is the current
  project name; existing tools, files, and terminology may still use “Coq.”

- **Scope:** The set of paths a proposal may change.  `local` permits only the
  selected source; `project` also permits `.v` files below
  `src/Rupicola/Generated`.

- **Tactic:** A program that helps build a proof term.  Rupicola's compiler
  automation is tactic-driven.

- **`.v` / `.vo`:** A Rocq source file and its compiled proof artifact,
  respectively.

## 10. Where to go next

- [`tools/rupicola_llm/README.md`](tools/rupicola_llm/README.md) is the command
  and implementation reference.
- [`LLM_DESIGN.md`](LLM_DESIGN.md) explains the product architecture, trust
  boundary, planned CLI, and delivery phases.
- [`LLM_EVAL.md`](LLM_EVAL.md) defines the preregistered held-out evaluation
  protocol and explains why calibration runs are not efficacy measurements.
- [`LLM_INSIGHTS.md`](LLM_INSIGHTS.md) synthesizes the qualitative development
  evidence, research hypotheses, non-claims, and questions for the next phase.
- [`src/Rupicola/Examples/LLMByteOrCaseStudy.md`](src/Rupicola/Examples/LLMByteOrCaseStudy.md),
  [`LLMCountByteCaseStudy.md`](src/Rupicola/Examples/LLMCountByteCaseStudy.md),
  and [`LLMFindByteCaseStudy.md`](src/Rupicola/Examples/LLMFindByteCaseStudy.md)
  describe the three development cases in depth.
- [`etc/relational-compilation-tutorial.v`](etc/relational-compilation-tutorial.v)
  is the deeper hands-on introduction to relational compilation itself.

At this point you have exercised the complete implemented trust path: observe
a compiler residual, retrieve a local analogue, propose an untrusted patch,
reject an unsafe shortcut, validate a repaired extension in isolation, and let
Rocq—not the provider—decide whether the theorem holds.
