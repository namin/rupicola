# LLM-guided semantic loop invariant: count byte occurrences

## Question

Can a repository-aware LLM agent bridge a compiler-shaped fold implementation
to an independent recursive specification by proposing a reusable, kernel-checked
loop invariant?

## Candidate preflight

Three fresh candidates were tested before selecting the benchmark:

| Candidate | Stock result | Assessment |
|---|---|---|
| `zip_with_or` | Compiled | No proof gap after importing the byte-OR rule |
| `find_byte` with early exit | Three residuals | Mixed bounds with break-branch local-map normalization |
| `count_byte` | One residual | Only a routine byte-bound side condition |

To isolate semantic reasoning, `count_byte` was paired with a separately defined
structurally recursive count.  The semantic file was then frozen with SHA-256:

```text
3b7fb4a14d1c695822101519de0f86b703931c28aee00ada40a3027ca70ec1f1
```

## Baseline

The stock compiler constructs the array loop, byte load, equality comparison,
and accumulator update.  It leaves two obligations:

```coq
(* Routine representation bound: *)
(0 <= byte.unsigned x < 2 ^ width /\
 0 <= byte.unsigned needle < 2 ^ width) \/ ...

(* Semantic loop property: *)
ListArray.fold_left (count_byte_step needle) bs 0 =
count_byte_spec bs needle
```

`LLMCountByteBaseline.v` records these residual shapes as an executable negative
control and aborts without declaring a theorem.

## Agent-produced invariant

The LLM generalized the fixed initial accumulator from `0` to an arbitrary
`acc`:

```coq
ListArray.fold_left (count_byte_step needle) bs acc =
acc + count_byte_spec bs needle
```

This is the inductive invariant: the running accumulator plus the count of the
unprocessed suffix equals the eventual result.  Induction on `bs` proves it;
the desired zero-accumulator theorem follows immediately.  A second lemma
places byte values within either supported word width.

The invariant shape was proposed correctly on the first attempt.  Seven
checker-rejected script refinements were needed in the scratch phase, mostly to
control reduction of the transparent fold step; `cbn -[count_byte_step]` made
the induction hypothesis syntactically reusable.  One final integration check
identified a missing `Arrays` import.  The finished proof and benchmark then
compiled without further proof changes.

## Result

With the two proved facts exported to `compiler_side_conditions`, the unchanged
benchmark closes with a single `compile` command in approximately 0.65 seconds
on the case-study machine.

The generated loop has the expected body:

```c
value = load_byte(bs + index);
hit = value == needle;
count = count + hit;
```

The formal result states both that the Bedrock2 return value represents the
fold implementation and that the fold equals the independent recursive count.

## Validation

- Direct `rocq compile` checks passed for all four modules.
- A dependency-aware targeted build of the negative control and benchmark passed.
- `rocq check -silent` passed for the specification, baseline, proof, and benchmark.
- `Print Assumptions` reported `Closed under the global context` for both
  `count_byte_ok` and `count_byte_br2fn_ok`.
- The new proof sources contain no `Admitted`, `Axiom`, or unchecked cast.

A repository-wide `make -j2` currently rebuilds into an unrelated failure at
`Examples/CapitalizeThird/Properties.v:361`.  The count-byte dependency path
builds successfully.  The correctness theorem covers the generated Bedrock2
function; the C printer was used only for shape inspection.

## Interpretation

Unlike the byte-OR study, this case did not add a target-language operation.
The agent supplied missing semantic knowledge in a form the deterministic proof
engine can reuse.  Rocq remained the sole acceptance authority throughout.

This remains one small, deliberately selected case rather than a success-rate
estimate.  A stronger next evaluation would generate several folds with hidden
recursive specifications and measure invariant recovery under fixed attempt and
time budgets.
