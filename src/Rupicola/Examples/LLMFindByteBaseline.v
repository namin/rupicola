Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.
Require Import Rupicola.Examples.LLMFindByteSpec.

(** Negative control: stock automation must construct the early-exit loop but
    leave the semantic relationship to the recursive specification.  No
    proposed proof support is imported. *)
Section Baseline.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  Notation bytes := (sizedlistarray_value access_size.one).

  Instance baseline_spec_of_find_byte : spec_of "find_byte" :=
    fnspec! "find_byte" ptr wlen wneedle /
            (bs : ListArray.t byte) needle R ~> r,
      { requires tr mem :=
          wneedle = word.of_Z (byte.unsigned needle) /\
          wlen = word.of_Z (Z.of_nat (length bs)) /\
          Z.of_nat (length bs) < 2 ^ width /\
          (bytes (length bs) ptr bs ⋆ R) mem;
        ensures tr' mem' :=
          tr' = tr /\ r = word.of_Z (find_byte bs needle) /\
          find_byte bs needle = find_byte_spec bs needle /\
          (bytes (length bs) ptr bs ⋆ R) mem' }.

  Import LoopCompiler.
  Import SizedListArrayCompiler.
  Hint Extern 10 => lia : compiler_side_conditions.
  Hint Unfold find_byte_eqb : compiler_cleanup.

  Derive baseline_find_byte_br2fn in
         (defn! "find_byte" ("bs", "len", "needle") ~> "r"
            { baseline_find_byte_br2fn },
          implements find_byte)
         as baseline_find_byte_br2fn_ok.
  Proof.
    compile_setup; repeat repeat compile_step.
    all: lazymatch goal with
         | |- ((0 <= byte.unsigned _ < 2 ^ _ /\
                0 <= byte.unsigned _ < 2 ^ _) \/ _) => idtac
         | |- (map.remove_many _ ["b"; "hit"] = _) => idtac
         | |- (ranged_for _ _ _ _ = find_byte_spec _ _) => idtac
         | |- ?G => fail "Unexpected find-byte baseline residual:" G
         end.
  Abort.
End Baseline.
