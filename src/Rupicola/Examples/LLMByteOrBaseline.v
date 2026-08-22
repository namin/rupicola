Require Import Rupicola.Lib.Api.
Require Import Rupicola.Examples.LLMByteOrSpec.

(** Negative control for the case study.  This file intentionally does not
    import [LLMByteOrCompiler].  It checks that the stock compiler reaches the
    expected byte-OR expression goal and then aborts the derivation. *)
Section Baseline.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  Instance baseline_spec_of_byte_or_scalar : spec_of "byte_or_scalar" :=
    fnspec! "byte_or_scalar" wx wy / (x y : byte) ~> r,
      { requires tr mem :=
          wx = word.of_Z (byte.unsigned x) /\
          wy = word.of_Z (byte.unsigned y);
        ensures tr' mem' :=
          tr' = tr /\ mem' = mem /\
          r = word.of_Z (byte.unsigned (byte_or_scalar x y)) }.

  Derive baseline_byte_or_scalar_br2fn in
         (defn! "byte_or_scalar" ("x", "y") ~> "r"
            { baseline_byte_or_scalar_br2fn },
          implements byte_or_scalar)
         as baseline_byte_or_scalar_br2fn_ok.
  Proof.
    compile_setup; repeat repeat compile_step.
    lazymatch goal with
    | |- DEXPR _ _ _ (word_of_byte (byte_or _ _)) => idtac
    | |- ?G => fail "Unexpected baseline residual goal:" G
    end.
  Abort.
End Baseline.
