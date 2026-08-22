# LLM-guided compiler extension: byte OR

## Question

Can a repository-aware LLM agent turn a fresh Rupicola compilation failure
into a reusable, kernel-checked compiler rule without changing the semantic
program?

## Benchmark

The frozen semantic file defines a byte-level bitwise OR, a scalar wrapper, and
an in-place array map.  Its SHA-256 before and after augmentation was:

```text
885535ed44f0f85cc4717fe42174701d2be2f4a4a737f4cae6ca6ff9dc9310d1
```

The scalar derivation was used to diagnose the missing rule.  The array map was
a separately predeclared reuse case; it was not a blinded benchmark.

## Baseline

With only the stock API imported, `compile` constructed the scalar assignment
and the array loop, load, store, invariant, and separation-logic frame.  Both
derivations then stopped at the same expression obligation:

```coq
DEXPR mem locals ?e (word_of_byte (byte_or x y))
```

`LLMByteOrBaseline.v` keeps this expected residual as an executable negative
control.

## Agent-produced augmentation

The 44-line extension contains three proved lemmas and one exported hint:

1. `byte_unsigned_or` proves the semantic fact about byte OR.
2. `byte_morph_or` relates it to machine-word OR.
3. `expr_compile_byte_or` constructs a Bedrock2 OR expression.
4. An `expr_compiler` hint makes the rule reusable by deterministic `compile`.

The structure was retrieved from the neighboring byte-AND and byte-XOR rules;
the OR-specific bitvector proof and compiler rule were then checked by Rocq.

## Result

| Configuration | Scalar | Array map |
|---|---:|---:|
| Stock compiler | Expected residual | Expected residual |
| With proposed rule | Proved | Proved |

The extension compiled on its first Rocq attempt.  The augmented benchmark also
compiled on its first attempt, in approximately 0.67 seconds on the case-study
machine.

The synthesized scalar C statement is:

```c
r = (x)|(y);
```

The array body is a byte load, `mask | value`, and byte store inside
the generated loop.

## Validation

- `rocq compile` accepted the semantic, extension, baseline, and benchmark modules.
- `rocq check` reported `Modules were successfully checked`.
- `Print Assumptions` reported `Closed under the global context` for both
  correctness theorems.
- A repository `make -j2` build passed.
- The new sources contain no `Admitted`, `Axiom`, or unchecked-cast escape hatch.

The correctness theorems concern the generated Bedrock2 functions.  The C
printer was used only to inspect their shape; this experiment does not add a
correctness theorem for that printer or for a downstream C toolchain.

## Interpretation

This is evidence for using an LLM as an untrusted proof-search and compiler-rule
author: it localized the failure, retrieved an analogous pattern, proposed a
general rule, and let the Rocq kernel decide whether to accept it.  It is one
bounded case study, not a statistical claim about success rates.  A useful next
experiment would repeat this protocol across a mutation suite or a genuinely
new loop-invariant problem.
