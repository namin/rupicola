# LLM-guided early-exit search: find a byte

## Question

Can a repository-aware LLM agent bridge an independent recursive search
specification to Rupicola's break-capable loop semantics and materialize the
exit token in generated Bedrock2 code?

## Benchmark

`find_byte` returns the zero-based index of the first matching byte, or the
array length when no byte matches.  Its implementation uses `ranged_for` and
`ExitToken.break`; its specification is a separate structural recursion over
the list.  The semantic file was frozen with SHA-256:

```text
f8c56d52651510b1ec1227851d80ed32811acffc0e84dd3e64b5a961924f0e55
```

## Baseline

The stock compiler constructs the loop, byte load, comparison, and conditional,
but leaves exactly three classes of obligation:

1. the routine byte-to-word bounds fact;
2. a break-branch locals transition that stock compilation cannot materialize;
3. equality between the break-capable ranged loop and the recursive search.

The second residual is significant.  Logically, a break token changes the next
loop index to the bound, while the generated loop increments its counter after
the body.  A correct runtime branch must therefore copy the found index into
the result and write `bound - 1` into the counter.  Treating the branch as
`skip` makes the inferred locals equality false.

`LLMFindByteBaseline.v` checks these residual shapes and aborts without
declaring a theorem.

## Agent-produced augmentation

The semantic invariant is a shifted-suffix theorem:

```coq
find_byte_from bs needle base = base + find_byte_spec bs needle
```

On a matching head byte, the exit token freezes `base`.  On a nonmatch, the
remaining loop is rewritten as the same search over the tail at `base + 1`, so
the induction hypothesis applies.  A small index-shifting lemma relates the
two `ListArray.get` expressions.

The agent also supplied the kernel-checked `compile_break_transition` rule.  It
takes runtime expressions for the current index and bound, removes branch-local
temporaries, copies the current index to the result variable, and emits the
counter assignment for early exit.  The benchmark invokes this rule only at
the exit-token branch and delegates all other steps to the stock compiler.

Checker feedback exposed two useful design constraints during refinement:

- generated syntax cannot depend on ghost values such as the Gallina list
  length, so the rule must use the runtime bound variable;
- the transition must update both the loop counter and the result accumulator.

## Result

The augmented derivation closes.  The generated Bedrock2 body has this C-like
shape:

```c
r = len;
i = 0;
while (i < len) {
  b = load_byte(bs + i);
  if (b == needle) {
    r = i;
    i = len - 1;
  }
  i = i + 1;
}
return r;
```

The correctness theorem connects the returned machine word to `find_byte`, and
the proved semantic theorem connects `find_byte` to the independent recursive
`find_byte_spec`.  Thus the first-match and not-found behaviors are both covered.

## Validation

- Direct `rocq compile` checks pass for the specification, negative control,
  proof support, and augmented benchmark.
- A dependency-aware targeted build of the negative control and augmented
  benchmark passes.
- `rocq check -silent` passes for all four modules.
- The augmented benchmark compiles in approximately 1.0 second on the
  case-study machine.
- `Print Assumptions` reports `Closed under the global context` for
  `compile_break_transition`, `find_byte_ok`, and `find_byte_br2fn_ok`.
- The generated Bedrock2 AST contains the byte load, equality branch, result
  copy, `bound - 1` counter assignment, and standard loop increment.
- The proof, specification, and benchmark contain no `Admitted`, `Axiom`, or
  unchecked cast.  The baseline's `Abort` is intentional.

## Interpretation

This case is harder than the preceding byte-OR and count-byte studies.  It
combines semantic invariant recovery with a genuine control-flow integration
gap.  The LLM remained an untrusted producer: every semantic lemma, compiler
transition, and final function theorem was accepted by Rocq's kernel.

It is still one selected case, not a success-rate estimate.  The next step is
to freeze a common agent protocol, machine-readable metrics, and a multi-case
suite before drawing comparative conclusions.
