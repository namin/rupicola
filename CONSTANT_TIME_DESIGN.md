# A constant-time domain for Rupicola

Status: selected direction, with the first feasibility proof implemented.

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

## 4. First checked slice

The existing CMove example already contains the right functional vocabulary:

- `cmove_word` and `cswap_word` are shallow Gallina models;
- `cmove_word_br2fn` and `cswap_word_br2fn` are generated Bedrock2 functions;
- `cmove_br2fn_ok` and `cswap_br2fn_ok` prove functional correctness.

[`src/Rupicola/Examples/ConstantTime/CMoveLeakage.v`](src/Rupicola/Examples/ConstantTime/CMoveLeakage.v)
adds leakage specifications and checked proofs for those same generated
functions.

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

1. **Public-length arrays.** Prove an exact trace for `cmove_array_br2fn` and
   `cswap_array_br2fn`.  This exercises loop leakage and is the first real test
   of compositionality.
2. **Reusable trace lemmas.** Factor the proof pattern currently local to
   `CMoveLeakage.v` into a small constant-time support module.
3. **Two-run interface.** Define public equivalence and derive a theorem saying
   that equal public inputs imply equal leakage traces, even when all secret
   inputs and initial secret contents differ.
4. **One additional kernel.** Add a fixed/public-length byte-array equality or
   zero test.  This checks that the domain is useful beyond the original
   CMove example.
5. **Negative examples.** Keep small secret-branch, secret-index, and
   variable-shift implementations whose leakage goals intentionally fail.
6. **Downstream story.** Identify the Bedrock2-to-machine-code path on which a
   leakage-preservation theorem can be reused or added.

The immediate next technical target is milestone 1: arrays force us to state
the public-bound loop invariant and will tell us what belongs in a reusable
domain library.

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
