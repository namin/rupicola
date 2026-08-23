# Qualitative insights from LLM-assisted Rupicola development

Status: **qualitative development memo, not evaluation results**.

Evidence cutoff: 2026-08-23.  The implementation observations below are pinned
to Rupicola commit `20e37b2`; the three case studies retain their own commit
identities.  Visible calibration examples, tuned development runs, and local
smoke tests must not be included in a held-out success rate.

This document synthesizes what development has taught us and records questions
for the next research phase.  [`LLM_DESIGN.md`](LLM_DESIGN.md) remains the
source of truth for intended architecture, and [`LLM_EVAL.md`](LLM_EVAL.md)
remains the source of truth for the proposed experimental protocol.

## Executive summary

The project has established a credible **end-to-end architecture feasibility
result**, but not yet an empirical model-capability result.

> We built an untrusted, repository-aware sidecar that observes exactly where
> stock Rupicola stops, retrieves relevant local proofs and compiler rules,
> lets a bounded agent propose Gallina patches, and accepts only patches that
> preserve the theorem obligation, close all residuals, compile, pass `rocq
> check`, add no assumptions, and leave the source tree unchanged.  Three
> calibration studies establish an initial task taxonomy, and a real AWS
> Bedrock run demonstrates a checker-driven repair loop.  The next research
> step is a frozen held-out evaluation of completion, transfer, cost, and
> failure mode.

The refined research question is not simply “Can an LLM prove Rocq theorems?”
It is:

> Can a repository-aware LLM close structured gaps in an extensible verified
> compiler, under fixed budgets and an unchanged trust boundary, and produce
> augmentations that transfer beyond the immediate theorem?

This framing distinguishes the project from unconstrained theorem proving.  A
candidate may need to identify the missing compiler knowledge, retrieve a local
analogue, adapt it to a new semantic operation or invariant, integrate it into
Rupicola's automation, and respond to exact checker feedback.  Rocq—not the
model—decides whether the resulting theorem is valid.

## What exists now

At the evidence cutoff, the repository contains:

- three completed, kernel-checked calibration studies covering expression
  compilation, semantic invariants, and early-exit control flow;
- a read-only diagnostic that replays an incomplete derivation, captures all
  focused and auxiliary goals, classifies actionable residuals, fingerprints
  them, and ranks local source evidence;
- a provider-neutral controller with seven typed actions and explicit action,
  retrieval, check, wall-time, path, and patch-size budgets;
- isolated patch application, frozen-target validation, compilation, residual
  replay, `rocq check`, `Print Assumptions`, and unchanged-source verification;
- append-only run, proposal, tool, checker, disclosure, and model-usage
  artifacts;
- a deterministic rejection-and-repair provider used as the acceptance
  harness; and
- an audited AWS Bedrock Converse adapter that has completed a real remote
  propose/check/repair loop.

The full local suite contains 60 tests.  With calibration enabled, it checks
the expected `1`, `2`, and `3` residual patterns, stable fingerprints across
fresh sessions, rejection of an unsafe axiom, verification of the Byte OR
extension, kernel and assumptions checks, and worktree preservation.  This is
strong system evidence; it is not a model benchmark.

## Evidence ledger

The following separation is deliberate: an observation is directly supported
by development evidence; an interpretation explains why it may matter; a
hypothesis still requires controlled evaluation.

| ID | Observed | Evidence | Interpretation, not yet a measured claim |
|---|---|---|---|
| O1 | Rupicola failures can be captured as stable structured residuals | Calibration tests reproduce residual counts and fingerprints across fresh proof sessions | Residual proof state may be a cleaner agent interface than generic source-plus-error prompting |
| O2 | The three development cases stop for materially different reasons | Byte OR, count byte, and find byte exercise expression, invariant, and control-state gaps | Gap class may predict required tools, scope, cost, and success probability |
| O3 | The controller rejects a parseable but logically unsafe shortcut | The scripted negative control proposes `Axiom escape : True`; policy rejects it before candidate compilation | Useful LLM assistance need not expand the trusted computing base |
| O4 | A model-authored augmentation has passed the implemented validation path | The 2026-08-22 unscored Byte OR Bedrock run closed `1 -> 0`, compiled, passed kernel and assumptions checks, and preserved the source tree | A real remote checker-driven loop is technically feasible |
| O5 | A valid proposal can exist at budget exhaustion | The 2026-08-23 capped run staged a corrected patch on its final action; model-independent rechecking later verified it | Agent termination quality and final-candidate quality should be recorded separately |
| O6 | Stale compiled artifacts can block an otherwise valid patch | The capped run's saved patch first hit an inconsistent `.vo`; rebuilding the named dependency allowed full verification | Build state is an experimental confound, not necessarily a proof-reasoning failure |
| O7 | Integration errors consumed checker turns in both live trajectories | Observed failures included an inapplicable diff and an inconsistent imported module | Proof reasoning, patch construction, environment coherence, and controller orchestration require separate failure labels |

## Case-study synthesis

The three cases are formative examples chosen and refined interactively.  Their
solutions remain visible to the agent, so they support qualitative design
insights only.

| Case | Commit | Stock gap | Successful augmentation | Main lesson |
|---|---|---|---|---|
| Byte OR | `cb18c1d` | Missing `DEXPR` rule for byte-level OR | Semantic byte-to-word bridge, expression compiler lemma, and narrow reusable hint | A close local compiler analogue can be adapted into checked project knowledge |
| Count byte | `0bd360f` | Compiler-shaped fold versus an independent recursive count | Generalized accumulator invariant plus representation side condition | The crucial step is often stating the right invariant, not invoking a stronger tactic |
| Find byte | `9d6338f` | Early-exit semantics, loop invariant, and locals-map transition | Shifted-suffix theorem plus explicit runtime result/counter update | Semantic control flow and generated local state must be reasoned about together |

These cases suggest an initial four-stratum benchmark taxonomy:

1. expression compilation;
2. fold or loop invariants;
3. control flow and locals-state transitions; and
4. mutation, separation-logic framing, and memory representation.

The fourth stratum remains to be represented by held-out tasks.  The taxonomy
is a design hypothesis until fresh tasks show that it predicts meaningful
differences in behavior.

## Live Bedrock observations

Both runs below used `us.openai.gpt-5.6-sol` through AWS Bedrock on the visible
Byte OR calibration case.  They were development observations, not independent
trials, and their prompts, limits, and tool configurations were not identical.
They must not be compared as efficacy measurements.

| Observation | 2026-08-22 development acceptance | 2026-08-23 small smoke run |
|---|---:|---:|
| Model invocations | 12 | 5 |
| Typed actions | 19 | 6 |
| Retrievals | 8 | 2 |
| Checker executions | 3 | 1 |
| Controller time | 67.3 s | 19.8 s |
| Uncached input tokens | 1,452 | 605 |
| Cache-read input tokens | 79,617 | 14,191 |
| Cache-write input tokens | 11,835 | 5,074 |
| Output tokens | 3,997 | 1,142 |
| Total provider-reported tokens | 96,901 | 21,012 |
| Controller outcome | Verified | Exhausted |
| Best saved candidate | Verified within run | Verified by subsequent model-independent check |

The 2026-08-22 trajectory was checker-driven:

1. the first diff did not apply;
2. the second imported a stale compiled example and failed frozen-target
   validation; and
3. the third adapted the checked Byte OR lemmas into a proof-local compiler
   rule and passed every implemented gate.

The 2026-08-23 trajectory used strict provider schemas, a six-action limit, two
retrievals, one checker execution, and a 2,048-token per-response output limit:

1. the model inspected the residual and identified the visible compiler
   analogue;
2. its first patch had incorrect hunk indentation and failed to apply;
3. it used that feedback to stage a corrected patch on action six; and
4. the controller exhausted its action budget before a second check was
   available.

The saved patch initially exposed a stale `LLMByteOrCompiler.vo` dependency.
After that ignored build artifact was rebuilt, the same patch reduced the
actionable residual from one to zero and passed compilation, frozen-target,
kernel, assumptions, and unchanged-source checks.

The small run's exact artifacts remain in a local Git-ignored run directory and
are not part of the committed research record.  Its statistics are included
here as a dated development observation, not as a reproducible result.  The
larger observation is also summarized in [`LLM_EVAL.md`](LLM_EVAL.md#development-acceptance-observation).

## Insights suggested by development

### 1. Residual proof state may be the right abstraction boundary

Rupicola has already compiled routine structure before the sidecar intervenes.
The residual retains elaborated hypotheses, locals, memory context, goal shape,
and a precise missing relation.  This constrains the agent's task and permits
stable before/after measurement.  A held-out ablation is needed to establish
whether this structure improves completion or cost.

### 2. Repository knowledge may matter more than generic proof fluency

The Byte OR case is largely an analogue-adaptation problem.  Count byte and
find byte require discovering semantic patterns already represented elsewhere
in the repository.  The retriever's usefulness is plausible but not yet
causal: every development case and its solution was visible, and no
no-retrieval ablation has been run.

### 3. Checker feedback appears central rather than incidental

Neither live trajectory was a clean one-shot success.  The model used exact
patch or validation feedback to change its next proposal.  This motivates an
interactive-checker ablation, but the current observations alone do not show
that feedback improves success probability relative to a one-shot baseline.

### 4. “Unsuccessful run” is too coarse a research label

The capped run was unsuccessful under the controller's primary criterion but
ended with a valid unchecked candidate.  Conversely, an apparently plausible
proof can fail scope, patch application, frozen-target, build, residual,
kernel, or assumptions gates.  The primary outcome should remain “verified
within the frozen budget,” while secondary fields distinguish:

- no candidate produced;
- policy-invalid candidate;
- patch-integration failure;
- environment or stale-build failure;
- checker-invalid candidate;
- valid candidate staged but not checked before exhaustion; and
- verified candidate.

Post-hoc candidate validity must not be silently promoted to primary success.
It is useful diagnostic evidence about controller sequencing and budget design.

### 5. Reuse is a stronger target than one-theorem closure

A model can overfit a visible proof or copy a nearby solution.  A generated
compiler rule becomes more interesting when it closes a separately prepared
importing derivation without another model call.  The proposed evaluation
therefore scores a sealed transfer case independently of the visible primary
task.

### 6. The external-sidecar trust boundary is workable

The model can remain outside the trusted computing base.  Typed tools, path and
patch policy, frozen theorem obligations, isolated workspaces, kernel checks,
assumptions probes, and append-only evidence provide defense in depth.  This
does not eliminate operational risks: memory and OS-level filesystem limits,
complete semantic redaction, a second clean replay, and aggregate token/cost
ceilings remain incomplete.

### 7. Evaluation infrastructure is part of the research contribution

Stable residual capture, exact repository identity, clean builds, failure
taxonomy, source-disclosure records, fixed budgets, and saved patches determine
whether model behavior can be interpreted.  The stale `.vo` incident shows how
easily an environment failure could otherwise be reported as a reasoning
failure.

## Falsifiable research hypotheses

These are hypotheses to discuss and preregister, not conclusions.

| Hypothesis | Proposed test |
|---|---|
| H1: Structured residual context plus repository retrieval improves verified completion | Compare the frozen full agent with a no-retrieval configuration on the same held-out tasks and budgets |
| H2: Interactive checker feedback improves integration and completion | Compare the full loop with a one-shot proposal configuration, preserving total model-token and wall-time accounting |
| H3: Gap strata predict different success, cost, and failure profiles | Report task-level outcomes and resource use separately for expression, invariant, control-flow, and mutation/framing strata |
| H4: Project-scoped augmentations can transfer beyond the visible theorem | Score a sealed importing transfer case without another model call |
| H5: A meaningful fraction of failures are integration or environment failures rather than proof-idea failures | Use the fixed failure taxonomy and independently rescore every saved final candidate in a clean workspace |
| H6: Repository retrieval and checker feedback can be exposed without expanding logical trust | Audit every accepted patch for frozen semantics, scope, assumptions, kernel acceptance, and unchanged trusted-base files |

The primary experiment in `LLM_EVAL.md` currently fixes one agent
configuration rather than silently adding these ablations.  Any selected
ablation should be preregistered as a separate treatment using the same frozen
task set.

## What cannot yet be claimed

- No success rate, generalization rate, or comparative model ranking has been
  measured.
- The three calibration cases were selected and refined interactively, and
  their solutions remain visible.
- Prompts, budgets, schema compatibility, and model selection changed during
  development.
- Only one remote model/provider configuration has been exercised in depth.
- There is no human-expert, retrieval-free, checker-free, or one-shot baseline.
- Three trials per held-out task will support descriptive stability evidence,
  not fine-grained statistical ranking.
- Verification currently ends at a proved Bedrock2 function theorem; it does
  not establish correctness of printed C, a downstream C compiler, or machine
  code.
- The product still lacks an independent second-workspace final replay,
  automated resume, aggregate token/cost enforcement, `verify`, and explicit
  `apply`.

## Questions for the team

### Research contribution

1. Is the intended first contribution primarily a system, an empirical study,
   or a systems-plus-evaluation paper?
2. Is “verified-compiler extension synthesis with transfer” the right framing,
   or should the scope remain general proof repair?
3. Which parts are likely novel relative to existing interactive theorem-prover
   agents: residual capture, repository retrieval, transfer, the trust boundary,
   or the evaluation design?

### Benchmark design

4. Are the four proposed strata the right decomposition?
5. Should held-out tasks be controlled synthetic gaps, reconstructed historical
   Rupicola gaps, or a mixture?
6. Is a sealed transfer case required for every task, or only tasks whose
   declared output is a reusable extension?
7. Should post-hoc-valid but budget-exhausted candidates be a reported secondary
   outcome while remaining primary failures?

### Experimental scope

8. Are eight tasks with three fresh agent trials per task sufficient for the
   intended claim?
9. Which ablation is most important: no retrieval, no interactive checker, or
   one-shot generation?
10. Is a human-expert baseline necessary for the first study, or better left to
    a separately scoped extension?
11. Which model snapshot, provider, source-disclosure policy, and total budget
    can be frozen for the complete batch?

### Publication and artifact

12. What venue and claim strength should drive the amount of engineering versus
    benchmark breadth?
13. Which transcripts, patches, scorer logs, and provider records can be
    published?
14. Should the first protocol be frozen before any concrete held-out task is
    authored, as currently proposed, or should task-family feasibility work
    precede the final freeze without exposing actual instances?

## Recommended next steps

The next move should follow the meeting's decision about the primary claim.
The current recommended order is:

1. Review and revise [`LLM_EVAL.md`](LLM_EVAL.md) with the team.
2. Decide the task strata, primary outcome, secondary post-hoc candidate field,
   transfer requirement, model configuration, and any first-study ablation.
3. Commit and tag the resulting protocol before instantiating held-out tasks or
   running scored trials.
4. Finish the runner, event logger, public scorer, `result.schema.json`, and
   independent clean-workspace replay.
5. Prepare and feasibility-check two sealed tasks per stratum using reference
   solutions unavailable to the agent.
6. Publish the complete suite-manifest digest.
7. Run the eight stock controls and 24 fresh agent trials without adapting the
   protocol to outcomes.
8. Publish every result record, patch, transcript, scorer output, failure
   classification, and aggregate report permitted by the disclosure policy.

Until the protocol is frozen, additional visible calibration experiments may
improve the product but should be recorded as formative development, not added
to the eventual numerator or denominator.

## Suggested Monday discussion flow

1. Give the executive summary above in about one minute.
2. Show the one-residual Byte OR `diagnose` output.
3. Show the deterministic run summary: unsafe axiom rejected, repaired patch
   verified, worktree unchanged.
4. Summarize the two live trajectories rather than spending meeting time or
   money on another live call.
5. Walk through the three-case taxonomy and the distinction between proof,
   integration, environment, and budget failures.
6. Spend the remaining time on the proposed claim, held-out task construction,
   transfer scoring, and which protocol decisions must be frozen.

## Document map

- [`LLM_TUTORIAL.md`](LLM_TUTORIAL.md): self-contained newcomer walkthrough
- [`tools/rupicola_llm/README.md`](tools/rupicola_llm/README.md): command and
  implementation reference
- [`LLM_DESIGN.md`](LLM_DESIGN.md): product architecture and delivery phases
- [`LLM_EVAL.md`](LLM_EVAL.md): proposed controlled evaluation protocol
- [`src/Rupicola/Examples/LLMByteOrCaseStudy.md`](src/Rupicola/Examples/LLMByteOrCaseStudy.md),
  [`LLMCountByteCaseStudy.md`](src/Rupicola/Examples/LLMCountByteCaseStudy.md),
  and [`LLMFindByteCaseStudy.md`](src/Rupicola/Examples/LLMFindByteCaseStudy.md):
  formative case-study evidence
