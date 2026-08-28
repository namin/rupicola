Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.

(** A branchless public-length scan.  The result is the bitwise OR of the XOR
    of each pair of words; in particular, zero is the conventional witness
    that no word differed.  Keeping the primitive as a mismatch accumulator
    avoids introducing a data-dependent early exit. *)
Section WithParameters.
  Context {width: Z} {BW: Bitwidth width}.
  Context {word: word.word width} {mem: map.map word Byte.byte}.
  Context {locals: map.map String.string word}.
  Context {ext_spec: bedrock2.Semantics.ExtSpec}.
  Context {word_ok: word.ok word} {mem_ok: map.ok mem}.
  Context {locals_ok: map.ok locals}.
  Context {ext_spec_ok: Semantics.ext_spec.ok ext_spec}.

  Instance HasDefault_word : HasDefault word := word.of_Z 0.

  Definition array_xor_diff
      (len : word)
      (a1 a2 : ListArray.t word.rep) : word :=
    let/n from := word.of_Z 0 in
    let/n diff := word.of_Z 0 in
    let/n diff :=
      ranged_for_u
        from len
        (fun diff tok idx Hlt =>
           let/n v1 := ListArray.get a1 idx in
           let/n v2 := ListArray.get a2 idx in
           let/n diff := word.or diff (word.xor v1 v2) in
           (tok, diff)) diff in
    diff.

  Instance spec_of_array_xor_diff : spec_of "array_xor_diff" :=
    fnspec! "array_xor_diff" len ptr1 ptr2 /
      n a1 a2 R ~> diff,
      { requires tr m :=
          word.unsigned len = Z.of_nat n /\
          (sizedlistarray_value AccessWord n ptr1 a1
           * sizedlistarray_value AccessWord n ptr2 a2 * R)%sep m;
        ensures tr' m' :=
          tr' = tr /\
          diff = array_xor_diff len a1 a2 /\
          (sizedlistarray_value AccessWord n ptr1 a1
           * sizedlistarray_value AccessWord n ptr2 a2 * R)%sep m' }.

  Import SizedListArrayCompiler.
  Import LoopCompiler.
  Hint Extern 10 (_ < _) => lia : compiler_side_conditions.

  Derive array_xor_diff_br2fn SuchThat
         (defn! "array_xor_diff" ("len", "a1", "a2") ~> "diff"
           { array_xor_diff_br2fn },
          implements array_xor_diff)
         As array_xor_diff_br2fn_ok.
  Proof.
    compile.
  Qed.
End WithParameters.
