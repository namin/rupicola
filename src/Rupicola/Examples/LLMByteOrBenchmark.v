Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.
Require Import Rupicola.Examples.LLMByteOrSpec.
Require Import Rupicola.Examples.LLMByteOrCompiler.

Section with_parameters.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  Instance spec_of_byte_or_scalar : spec_of "byte_or_scalar" :=
    fnspec! "byte_or_scalar" wx wy / (x y : byte) ~> r,
      { requires tr mem :=
          wx = word.of_Z (byte.unsigned x) /\
          wy = word.of_Z (byte.unsigned y);
        ensures tr' mem' :=
          tr' = tr /\ mem' = mem /\
          r = word.of_Z (byte.unsigned (byte_or_scalar x y)) }.

  Derive byte_or_scalar_br2fn in
         (defn! "byte_or_scalar" ("x", "y") ~> "r"
            { byte_or_scalar_br2fn },
          implements byte_or_scalar)
         as byte_or_scalar_br2fn_ok.
  Proof.
    compile.
  Qed.

  Import LoopCompiler.
  Import SizedListArrayCompiler.
  Hint Extern 10 => lia : compiler_side_conditions.

  Notation bytes := (sizedlistarray_value access_size.one).

  Instance spec_of_or_mask_bytes : spec_of "or_mask_bytes" :=
    fnspec! "or_mask_bytes" ptr wlen wmask /
            (bs : ListArray.t byte) mask R,
      { requires tr mem :=
          wmask = word.of_Z (byte.unsigned mask) /\
          wlen = word.of_Z (Z.of_nat (length bs)) /\
          Z.of_nat (length bs) < 2 ^ width /\
          (bytes (length bs) ptr bs ⋆ R) mem;
        ensures tr' mem' :=
          tr' = tr /\
          (bytes (length bs) ptr (or_mask_bytes bs mask) ⋆ R) mem' }.

  Derive or_mask_bytes_br2fn in
         (defn! "or_mask_bytes" ("bs", "len", "mask")
            { or_mask_bytes_br2fn },
          implements or_mask_bytes)
         as or_mask_bytes_br2fn_ok.
  Proof.
    compile.
  Qed.
End with_parameters.
