From Stdlib Require Import ZArith.
Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.

(** A branchless public-length scan.  The result is the bitwise OR of the XOR
    of each pair of words.  [array_xor_diff_zero_iff] below proves that zero
    is exactly the witness that no word differed.  Keeping the primitive as a
    mismatch accumulator avoids introducing a data-dependent early exit. *)
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

  (** A pure list model used to state the scan's mathematical meaning. *)
  Definition array_xor_diff_step
      (diff : word) (values : word * word) : word :=
    word.or diff (word.xor (fst values) (snd values)).

  Definition array_xor_diff_fold
      (a1 a2 : ListArray.t word.rep) : word :=
    List.fold_left array_xor_diff_step (List.combine a1 a2) (word.of_Z 0).

  Lemma array_xor_diff_word_zero_iff (x y : word) :
    word.xor x y = word.of_Z 0 <-> x = y.
  Proof.
    split.
    - intro H.
      apply word.unsigned_inj.
      apply (proj1 (Z.lxor_eq_0_iff _ _)).
      rewrite <- word.unsigned_xor_nowrap, H, word.unsigned_of_Z_0.
      reflexivity.
    - intro H; subst y.
      apply word.xor_eq_0_iff; reflexivity.
  Qed.

  Lemma array_xor_diff_fold_pairs_zero_iff pairs acc :
    List.fold_left array_xor_diff_step pairs acc = word.of_Z 0 <->
    acc = word.of_Z 0 /\
    List.Forall (fun values => fst values = snd values) pairs.
  Proof.
    revert acc; induction pairs as [|[x y] pairs IH]; intro acc;
      cbn [array_xor_diff_step].
    - split.
      + intro H; split; [exact H | constructor].
      + intros [H _]; exact H.
    - rewrite (IH (array_xor_diff_step acc (x, y))).
      unfold array_xor_diff_step at 1.
      rewrite word.lor_0_iff, array_xor_diff_word_zero_iff.
      rewrite List.Forall_cons_iff.
      cbn.
      tauto.
  Qed.

  Lemma combine_words_equal_iff (a1 a2 : list word) :
    List.length a1 = List.length a2 ->
    List.Forall (fun values => fst values = snd values)
      (List.combine a1 a2) <->
    a1 = a2.
  Proof.
    revert a2; induction a1 as [|x xs IH]; intros [|y ys] Hlen;
      cbn in Hlen; try discriminate.
    - split; [intro; reflexivity | intro; constructor].
    - cbn [List.combine].
      rewrite List.Forall_cons_iff; cbn.
      rewrite IH by lia.
      split.
      + intros [Hxy Htl]; subst; reflexivity.
      + injection 1 as -> ->; split; reflexivity.
  Qed.

  Lemma array_xor_diff_fold_zero_iff a1 a2 :
    List.length a1 = List.length a2 ->
    array_xor_diff_fold a1 a2 = word.of_Z 0 <-> a1 = a2.
  Proof.
    intros Hlen; unfold array_xor_diff_fold.
    rewrite array_xor_diff_fold_pairs_zero_iff.
    rewrite combine_words_equal_iff by exact Hlen.
    split.
    - intros [_ H]; exact H.
    - intro H; split; [reflexivity | exact H].
  Qed.

  Lemma array_xor_diff_as_ranged_for_all len a1 a2 :
    array_xor_diff len a1 a2 =
    ranged_for_all_u
      (word.of_Z 0) len
      (fun diff idx _ =>
         word.or diff
           (word.xor (ListArray.get a1 idx) (ListArray.get a2 idx)))
      (word.of_Z 0).
  Proof.
    unfold array_xor_diff, nlet.
    unfold ranged_for_u, ranged_for_all_u, ranged_for_w, ranged_for_all_w.
    rewrite ranged_for_all_as_ranged_for.
    reflexivity.
  Qed.

  Lemma array_xor_diff_as_nd_ranged_for_all len a1 a2 :
    array_xor_diff len a1 a2 =
    nd_ranged_for_all_u
      (word.of_Z 0) len
      (fun diff idx =>
         word.or diff
           (word.xor (ListArray.get a1 idx) (ListArray.get a2 idx)))
      (word.of_Z 0).
  Proof.
    rewrite array_xor_diff_as_ranged_for_all.
    unfold ranged_for_all_u, nd_ranged_for_all_u.
    symmetry; apply nd_as_ranged_for_all_w.
  Qed.

  Lemma array_xor_diff_eq_fold len a1 a2 :
    word.unsigned len = Z.of_nat (List.length a1) ->
    List.length a1 = List.length a2 ->
    array_xor_diff len a1 a2 = array_xor_diff_fold a1 a2.
  Proof.
    intros Hlen Hlengths.
    rewrite array_xor_diff_as_nd_ranged_for_all.
    unfold nd_ranged_for_all_u, nd_ranged_for_all_w, nd_w_body.
    rewrite <- fold_left_as_nd_ranged_for_all.
    rewrite word.unsigned_of_Z_0.
    unfold array_xor_diff_fold.
    rewrite (copying_fold_left_as_ranged_fold_left
               array_xor_diff_step (List.combine a1 a2) (word.of_Z 0)).
    eapply fold_left_Proper.
    - f_equal.
      rewrite List.length_combine, <- Hlengths, Nat.min_id.
      exact Hlen.
    - reflexivity.
    - intros diff idx Hin.
      apply z_range_sound in Hin.
      unfold array_xor_diff_step, ListArray.get, cast, Convertible_word_nat.
      rewrite List.nth_error_nth'
        with (d := (word.of_Z 0, word.of_Z 0)).
      2: { rewrite List.length_combine, <- Hlengths, Nat.min_id; lia. }
      rewrite List.combine_nth by exact Hlengths.
      rewrite !word.unsigned_of_Z, !word.wrap_small
        by (pose proof word.unsigned_range len; lia).
      reflexivity.
  Qed.

  (** The semantic certificate for the full public-length scan.  The length
      hypotheses are exactly the list-size facts carried by the functional
      specification's [sizedlistarray_value] predicates. *)
  Theorem array_xor_diff_zero_iff len a1 a2 :
    word.unsigned len = Z.of_nat (List.length a1) ->
    List.length a1 = List.length a2 ->
    array_xor_diff len a1 a2 = word.of_Z 0 <-> a1 = a2.
  Proof.
    intros Hlen Hlengths.
    rewrite array_xor_diff_eq_fold by assumption.
    apply array_xor_diff_fold_zero_iff; assumption.
  Qed.

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
