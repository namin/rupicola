# A constant-time domain for Rupicola

Status: working domain slice, with reusable support plus functional and exact
leakage proofs for conditional move/swap and a public-length mismatch scan.

## 1. Decision

Add a domain for compiling and certifying **data-oblivious, constant-time
building blocks**.  The first version should use explicit constant-time
combinators rather than a secrecy type system:

- conditional move and conditional swap on words;
- the same operations over public-length arrays;
- fixed- or public-bound scans such as equality and zero tests;
- later, domain-specific branchless rewrites used by cryptographic code.

This fits Rupicola's central idea from `pldi.pdf`: experts teach the relational
compiler a small, composable vocabulary of implementation strategies.  Here,
the extra result is not only a fast functionally correct Bedrock2 program, but
also a certificate that its observable behavior does not depend on secrets.

The LLM is deliberately not the first component.  We first need a real domain,
a precise security statement, and checked examples.  An LLM can later search
for implementations and proof hints inside that boundary; Rocq remains the
authority for both functional correctness and leakage safety.

## 2. What we want to achieve

A user should be able to write a functional operation such as conditional
move and obtain one generated Bedrock2 function with two complementary
certificates:

1. **Functional correctness:** the generated function implements the Gallina
   model under its ordinary precondition.
2. **Leakage safety:** the generated function's control-flow and address trace
   is a function only of explicitly public inputs.

Concretely, if two executions use the same public pointers and public lengths
but different masks and data, they must produce the same leakage trace.  Their
output memories may differ: that is the intended functional result, not a
leak.

For simple straight-line routines, we can prove the stronger, easier-to-audit
statement that the entire trace equals an explicit public-only list.  For
loops, the analogous statement will compute a trace from the public base
addresses and loop bound.

## 3. Threat model

The first version uses Bedrock2's existing leakage semantics.  It records:

- branch and loop decisions;
- load and store addresses;
- operands of operations modeled as variable-time, including division,
  remainder, and data-dependent shifts;
- calls, stack allocation, and external-interaction leakage.

Ordinary subtraction and bitwise `and`/`or` do not reveal their operands in
this model.  For the initial combinators:

- **secret:** masks and values stored in the cells or arrays;
- **public:** object addresses, non-aliasing/layout facts, and array lengths;
- **required:** all accessed memory is valid according to the existing
  separation-logic representation predicates.

The leakage proof does not need the mask to be valid.  Even an arbitrary mask
produces the same trace; mask validity is needed only to prove the intended
conditional-move functional behavior.

This is a source-level constant-time claim for Bedrock2's leakage model.  It is
not, by itself, a claim about speculative execution, cache-bank conflicts,
hardware instructions whose timing is outside the model, or transformations
performed by an unverified downstream C compiler.  An end-to-end physical
timing claim would additionally need leakage-preserving lowering to the final
machine code and an appropriate hardware model.

## 4. Checked slice

The existing CMove example already contains the right functional vocabulary:

- `cmove_word` and `cswap_word` are shallow Gallina models;
- `cmove_word_br2fn` and `cswap_word_br2fn` are generated Bedrock2 functions;
- `cmove_br2fn_ok` and `cswap_br2fn_ok` prove functional correctness.

[`src/Rupicola/Examples/ConstantTime/CMoveLeakage.v`](src/Rupicola/Examples/ConstantTime/CMoveLeakage.v)
adds leakage specifications and checked proofs for those same generated
functions, including `cmove_array_br2fn` and `cswap_array_br2fn`.

The results are:

| Function | Execution-order memory accesses | Bedrock2 leakage list |
|---|---|---|
| `cmove_word` | load `c1`, load `c2`, store `c1` | `[c1; c2; c1]` |
| `cswap_word` | load `c1`, load `c2`, store `c1`, store `c2` | `[c2; c1; c2; c1]` |

Bedrock2 prepends events, so its list is in reverse execution order.  Neither
trace contains the mask or loaded values, and neither function emits a branch
event.  The proofs are generic in word width, memory implementation, locals
map, external specification, and stack-pointer choice.

This is the key feasibility result: the functional compiler output can be
checked directly with Bedrock2's leakage program logic.  We do not need to
replace Rupicola's compiler or trust a syntactic scan for branches.

The public-length array milestone is now checked as well.  If `a[i]` denotes
the public address of element `i`, each successful loop iteration prepends the
following events:

| Function | Per-iteration Bedrock2 leakage list |
|---|---|
| `cmove_array` | `[store a1[i]; load a2[i]; load a1[i]; loop true]` |
| `cswap_array` | `[store a2[i]; store a1[i]; load a2[i]; load a1[i]; loop true]` |

The complete trace starts with `loop false`, followed by those blocks for
indices `n - 1` down to `0`, because leakage events are prepended.  The proofs
compute every address from only the two public base pointers, the public word
stride, and the public length.  They quantify over arbitrary masks and over
arbitrary initialized word contents; neither can affect the trace.

This closes the first compositionality test.  The proof maintains two framed
array predicates across loads and stores, a canonical generated-locals state,
the exact accumulated trace, and a decreasing public loop measure.  Both array
theorems are closed under Rocq's global context: no admitted facts or added
axioms are used.

The reusable pieces now live in
[`src/Rupicola/Lib/ConstantTime.v`](src/Rupicola/Lib/ConstantTime.v):

- content-agnostic initialized-word and initialized-array predicates;
- public word-array stride and address normalization;
- a generic reverse-order trace constructor for public-bound loops;
- generated-locals normalization; and
- a sealed proof fence for executing one generated loop body at a time.

`CMoveLeakage.v` imports this module rather than defining those pieces locally.
As a cross-example check,
[`src/Rupicola/Examples/ConstantTime/MemcpyLeakage.v`](src/Rupicola/Examples/ConstantTime/MemcpyLeakage.v)
certifies the existing, functionally verified `sizedlist_memcpy_br2fn`.  Each
successful iteration has the public-only reverse trace
`[store dst[i]; load src[i]; loop true]`.  This matters because `memcpy` was not
created for the constant-time case study: the support layer applies to an
independent Rupicola-generated loop.

The first new scan kernel is in
[`src/Rupicola/Examples/ConstantTime/ArrayXorDiff.v`](src/Rupicola/Examples/ConstantTime/ArrayXorDiff.v).
`array_xor_diff` traverses two public-length word arrays without early exit and
accumulates the bitwise OR of pairwise XORs.  Its generated function has both:

- `array_xor_diff_br2fn_ok`, the ordinary Rupicola functional certificate; and
- `array_xor_diff_leakage_ok` in
  [`ArrayXorDiffLeakage.v`](src/Rupicola/Examples/ConstantTime/ArrayXorDiffLeakage.v),
  whose iteration trace is `[load a2[i]; load a1[i]; loop true]`.

The accumulator and both arrays' contents are arbitrary secrets in the leakage
proof.  This is the scan core of an equality/zero-test primitive.  It does not
yet certify the separate conversion from a zero accumulator to a Boolean or
all-ones mask; keeping that boundary explicit avoids silently assuming that a
target-level comparison or shift is constant time.

## 5. Proposed domain shape

Version 0 should remain small and explicit.

### Source vocabulary

Start with named Gallina combinators whose public/secret conventions are part
of their contracts:

- `ct_select_word mask x y`;
- `ct_cmove_word mask dst src`;
- `ct_cswap_word mask a b`;
- `ct_cmove_array mask public_len dst src`;
- `ct_cswap_array mask public_len a b`.

The current CMove definitions can seed this library.  We should not add a
general information-flow type system yet.  Explicit combinators make the
security boundary reviewable and let us validate the proof architecture
before attempting inference.

### Generated artifacts

Each public combinator should expose or generate:

- its ordinary Rupicola `implements` theorem;
- a leakage specification for the generated Bedrock2 function;
- a leakage proof showing that the trace is computed from public inputs;
- eventually, a small relational corollary phrased as two-run
  noninterference.

The functional and leakage theorems certify the same generated function.  They
can remain separate proof obligations initially, which avoids disturbing the
ordinary Rupicola compiler relation.

### Compiler extensions

Once the examples stabilize, promote only the reusable pieces into
`Rupicola.Lib`:

- domain combinators and representation predicates;
- leakage-spec constructors for straight-line and public-bound loop patterns;
- proof hints that compose public-only traces;
- negative checks for forbidden secret-dependent branches, addresses, and
  variable-time operands.

The existing compiler should still generate ordinary Bedrock2 syntax.  The
domain layer adds a second checked property; it should not introduce a new
target language.

## 6. Next milestones

1. **Public-length arrays (complete).** Exact public-only traces are proved for
   both `cmove_array_br2fn` and `cswap_array_br2fn`.
2. **Reusable trace foundation (complete).** Shared predicates, address
   normalization, public-loop trace construction, locals normalization, and
   proof fencing are factored into `Rupicola.Lib.ConstantTime` and reused by an
   independent generated `memcpy` loop.
3. **Two-run interface (next).** Define public equivalence and derive a theorem saying
   that equal public inputs imply equal leakage traces, even when all secret
   inputs and initial secret contents differ.
4. **One additional kernel (scan core complete).** The public-length
   `array_xor_diff` kernel has functional and exact leakage certificates.  Next,
   specify its zero/equality meaning and add a target-appropriate constant-time
   zero-to-mask wrapper.
5. **Negative examples.** Keep small secret-branch, secret-index, and
   variable-shift implementations whose leakage goals intentionally fail.
6. **Downstream story.** Identify the Bedrock2-to-machine-code path on which a
   leakage-preservation theorem can be reused or added.

The immediate proof-engineering target is now a higher-level public-loop
interface that removes the remaining invariant boilerplate.  The immediate
domain target is the zero/equality specification around `array_xor_diff`.
Together, those give a useful next test for LLM assistance: propose the wrapper
and proof plan, while Rocq rejects any implementation whose comparison,
control flow, address calculation, or modeled variable-time operand reveals
the secret accumulator.

## 7. Where an LLM helps later

Once the checked domain exists, an LLM can be useful as an untrusted search
component:

- propose branchless Gallina implementations for a functional specification;
- choose among known constant-time combinators and compiler hints;
- suggest public-bound loop invariants and trace formulas;
- retrieve similar Bedrock2 leakage proofs;
- explore domain-specific rewrites and performance variants.

Every proposal must pass both proof obligations.  A candidate that is
functionally correct but leaks a secret branch or address is rejected by the
leakage proof; a candidate with a convincing constant-time shape but the wrong
result is rejected by the functional proof.  Thus the LLM can broaden search
without entering the trusted computing base.

## 8. How to evaluate the domain

Evaluation should answer four substantive questions:

1. **Coverage:** can the library express and certify a small suite of word and
   array kernels without one-off semantic proofs?
2. **Security:** do the checked traces depend only on declared public inputs,
   and do deliberately leaky variants fail for the expected reason?
3. **Engineering cost:** how many lines of domain-specific definitions,
   invariants, and proof scripts are needed per new kernel after the reusable
   layer exists?
4. **Code quality:** does generated C have the expected branchless/public-loop
   shape, and how does its performance compare with handwritten constant-time
   implementations?

Only after this baseline is established should we measure the LLM's benefit:
additional solved kernels, reduced author effort, and accepted suggestions
versus rejected or misleading ones.  The main research result should remain
the verified constant-time domain; LLM assistance is an optional way to make
that domain easier to extend.
