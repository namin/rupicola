Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.
Require Import Rupicola.Examples.LLMCountByteSpec.
Require Import Rupicola.Examples.LLMCountByteProof.

Section Benchmark.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  Notation bytes := (sizedlistarray_value access_size.one).

  Instance spec_of_count_byte : spec_of "count_byte" :=
    fnspec! "count_byte" ptr wlen wneedle /
            (bs : ListArray.t byte) needle R ~> r,
      { requires tr mem :=
          wneedle = word.of_Z (byte.unsigned needle) /\
          wlen = word.of_Z (Z.of_nat (length bs)) /\
          Z.of_nat (length bs) < 2 ^ width /\
          (bytes (length bs) ptr bs ⋆ R) mem;
        ensures tr' mem' :=
          tr' = tr /\ r = word.of_Z (count_byte bs needle) /\
          count_byte bs needle = count_byte_spec bs needle /\
          (bytes (length bs) ptr bs ⋆ R) mem' }.

  Import LoopCompiler.
  Import SizedListArrayCompiler.
  Hint Extern 10 => lia : compiler_side_conditions.
  Hint Unfold count_byte_step count_byte_eqb : compiler_cleanup.

  Derive count_byte_br2fn in
         (defn! "count_byte" ("bs", "len", "needle") ~> "r"
            { count_byte_br2fn },
          implements count_byte)
         as count_byte_br2fn_ok.
  Proof.
    compile.
  Qed.
End Benchmark.
