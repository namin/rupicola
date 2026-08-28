Require Import Rupicola.Examples.ConstantTime.ArrayXorDiff.
Require Import Rupicola.Lib.ConstantTime.
From Stdlib Require Import ZArith.ZArith Strings.String Lia.
Require Import coqutil.Word.Bitwidth coqutil.Word.Interface.
Require Import coqutil.Word.Properties.
Require Import coqutil.Map.Interface coqutil.Byte.
Require Import coqutil.Map.Properties.
Require Import bedrock2.LeakageSemantics.
Require Import bedrock2.LeakageWeakestPrecondition.
Require Import bedrock2.LeakageProgramLogic.
Require Import bedrock2.LeakageLoops.
Require Import bedrock2.Map.SeparationLogic.

Import List.ListNotations.
Import LeakageProgramLogic.Coercions.
Import SeparationLogic.
Local Open Scope string_scope.
Local Open Scope list_scope.

Section WithParameters.
  Context {width: Z} {BW: Bitwidth width}.
  Context {word: word.word width} {mem: map.map word Byte.byte}.
  Context {locals: map.map String.string word}.
  Context {ext_spec: LeakageSemantics.ExtSpec}.
  Context {word_ok: word.ok word} {mem_ok: map.ok mem}.
  Context {locals_ok: map.ok locals}.
  Context {ext_spec_ok: LeakageSemantics.ext_spec.ok ext_spec}.
  Context {pick_sp: LeakageSemantics.PickSp}.

  Local Ltac prove_leakage :=
    repeat straightline;
    repeat (straightline || eexists || split ||
            (match goal with
             | |- @map.get _ _ _ ?l _ = _ =>
                 is_var l; cbv delta [l]
             end) ||
            (rewrite ?map.get_put_dec, ?map.get_empty,
                     ?word.of_Z_unsigned; cbn));
    repeat (straightline || ecancel_assumption || eauto ||
            (match goal with
             | |- @map.get _ _ _ ?l _ = _ =>
                 is_var l; cbv delta [l]
             end) ||
            (rewrite ?map.get_put_dec, ?map.get_empty,
                     ?word.of_Z_unsigned; cbn)).

  Definition xor_diff_loop_locals
      (len ptr1 ptr2 from diff index : word) : locals :=
    map.put
      (map.put
        (map.put
          (map.put
            (map.put
              (map.put
                (map.put map.empty "len" len)
                "a1" ptr1)
              "a2" ptr2)
            "from" from)
          "diff" diff)
        "_gs_from0" index)
      "_gs_to0" len.

  Definition xor_diff_one_iteration_leakage
      (ptr1 ptr2 : word) (i : nat) : leakage :=
    [leak_word (word_array_index ptr2 i);
     leak_word (word_array_index ptr1 i);
     leak_bool true].

  Definition xor_diff_iterations_leakage
      (ptr1 ptr2 : word) (count : nat) : leakage :=
    public_loop_iterations_leakage
      (xor_diff_one_iteration_leakage ptr1 ptr2) count.

  Definition xor_diff_public_leakage
      (ptr1 ptr2 : word) (count : nat) : leakage :=
    public_loop_leakage
      (xor_diff_one_iteration_leakage ptr1 ptr2) count.

  Definition array_xor_diff_leakage_spec : spec_of "array_xor_diff" :=
    fnspec! "array_xor_diff" (len ptr1 ptr2 : word) /
      (n : nat) (R : mem -> Prop) ~> diff,
      { requires k t m :=
          word.unsigned len = Z.of_nat n /\
          (initialized_word_array ptr1 n
           * initialized_word_array ptr2 n * R)%sep m;
        ensures k' t' m' :=
          k' = xor_diff_public_leakage ptr1 ptr2 n ++ k /\
          t' = t }.

  Lemma array_xor_diff_leakage_ok :
    program_logic_goal_for (@array_xor_diff_br2fn width word)
      (forall functions : Semantics.env,
        map.get functions "array_xor_diff" =
          Some (@array_xor_diff_br2fn width word) ->
        array_xor_diff_leakage_spec functions).
  Proof.
    prove_leakage.
    lazymatch goal with
    | |- LeakageSemantics.exec ?functions
           (Syntax.cmd.while ?condition ?body) ?K ?T ?M ?L ?post =>
        change (LeakageWeakestPrecondition.cmd functions
                  (Syntax.cmd.while condition body) K T M L post)
    end.
    eapply LeakageLoops.wp_while.
    eexists nat, Nat.lt,
      (fun remaining K T M L =>
         exists i acc,
           (i <= n)%nat /\
           map.get L "len" = Some len /\
           map.get L "a1" = Some ptr1 /\
           map.get L "a2" = Some ptr2 /\
           map.get L "from" = Some from /\
           map.get L "diff" = Some acc /\
           map.get L "_gs_from0" = Some (word.of_Z (Z.of_nat i)) /\
           map.get L "_gs_to0" = Some len /\
           L = xor_diff_loop_locals len ptr1 ptr2 from acc
                 (word.of_Z (Z.of_nat i)) /\
           K = xor_diff_iterations_leakage ptr1 ptr2 i ++ k /\
           T = t /\
           (initialized_word_array ptr1 n
            * initialized_word_array ptr2 n * R)%sep M /\
           remaining = (n - i)%nat).
    split.
    { eapply Wf_nat.lt_wf. }
    split.
    { exists n, O. eexists.
      assert (_gs_from0 = word.of_Z 0) as Hgs0.
      { subst _gs_from0; apply word.of_Z_unsigned. }
      subst _gs_from0; subst l3; subst l2; subst l1; subst l0; subst l.
      repeat split; try assumption; try reflexivity.
      all: repeat (rewrite ?map.get_put_dec, ?map.get_empty; cbn).
      all: try unfold xor_diff_loop_locals.
      all: repeat rewrite Hgs0.
      all: try rewrite word.of_Z_unsigned.
      all: cbn [xor_diff_iterations_leakage
                public_loop_iterations_leakage List.app].
      all: try reflexivity.
      all: try apply Nat.le_0_l.
      all: try ecancel_assumption.
      all: try lia.
      all: reflexivity. }
    intros remaining K T M L
      (i & acc & Hi & Hlen & Hptr1 & Hptr2 & Hfrom & Hdiff &
       Hindex & Hbound & Hlocals & HK & HT & HM & Hremaining).
    eexists (if word.ltu (word.of_Z (Z.of_nat i)) len
             then word.of_Z 1 else word.of_Z 0), K.
    split.
    { eexists; split; [exact Hindex|].
      eexists; split; [exact Hbound|].
      cbn [LeakageSemantics.leak_binop Semantics.interp_binop].
      split; reflexivity. }
    split.
    { intro Hnonzero.
      destruct (word.ltu (word.of_Z (Z.of_nat i)) len) eqn:Hltu.
      2: rewrite word.unsigned_of_Z_0 in Hnonzero; contradiction.
      assert (Hindex_range : 0 <= Z.of_nat i < 2 ^ width).
      { pose proof (word.unsigned_range len). lia. }
      assert (Hlt : (i < n)%nat).
      { rewrite Interface.word.unsigned_ltu in Hltu.
        rewrite word.unsigned_of_Z_nowrap in Hltu by exact Hindex_range.
        apply Z.ltb_lt in Hltu. lia. }
      unfold xor_diff_loop_locals in Hlocals.
      subst L.
      SeparationLogic.seprewrite_in
        (initialized_word_array_index ptr1 n i Hlt) HM.
      SeparationLogic.seprewrite_in
        (initialized_word_array_index ptr2 n i Hlt) HM.
      unfold initialized_word, word_array_index in HM.
      repeat rewrite word.ring_morph_mul, word.of_Z_unsigned in HM.
      extract_ex1_and_emp_in_hyps.
      lazymatch goal with
      | body := context[
          Syntax.cmd.set "v1"
            (Syntax.expr.load Syntax.access_size.word
              (Syntax.expr.op Syntax.bopname.add _
                (Syntax.expr.op Syntax.bopname.mul
                  (Syntax.expr.literal ?stride) _)))] |- _ =>
          assert (word.of_Z stride = word_array_stride) as Hstride
            by reflexivity;
          rewrite <- Hstride in HM
      end.
      lazymatch goal with
      | |- LeakageWeakestPrecondition.cmd ?fs ?body ?K0 ?T0 ?M0 ?L0 ?post =>
          eapply LeakageWeakestPreconditionProperties.weaken_cmd
            with (post1 := fun K1 T1 M1 L1 =>
              LeakageProofFence.t (post K1 T1 M1 L1))
      end.
      2: { intros K1 T1 M1 L1 Hpost.
           exact (LeakageProofFence.elim _ Hpost). }
      prove_leakage.
      all: try lazymatch goal with
      | |- @map.get _ _ _ _ _ = _ =>
          normalize_generated_map_get;
          cbn;
          reflexivity
      end.
      apply LeakageProofFence.intro.
      exists (n - S i)%nat.
      split; [|lia].
      exists (S i). eexists.
      repeat split.
      all: try lia.
      all: try reflexivity.
      all: try lazymatch goal with
      | |- @map.get _ _ _ _ _ = _ =>
          normalize_generated_map_get;
          rewrite ?word_of_Z_nat_succ;
          cbn;
          reflexivity
      end.
      - unfold xor_diff_loop_locals.
        apply map.map_ext; intros key.
        normalize_generated_map_get.
        repeat rewrite word_of_Z_nat_succ.
        repeat first
          [ rewrite map.get_put_dec
          | rewrite map.get_remove_dec
          | rewrite map.get_empty
          | match goal with
            | |- context [if ?test then _ else _] =>
                destr.destr test; try congruence
            end ].
      - lazymatch type of Hstride with
        | ?generated_stride = word_array_stride =>
            change
              (leak_word
                 (word.add ptr2
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_word
                 (word.add ptr1
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_bool true ::
                 xor_diff_iterations_leakage ptr1 ptr2 i ++ k =
               xor_diff_iterations_leakage ptr1 ptr2 (S i) ++ k)
        end.
        rewrite Hstride.
        cbn [xor_diff_iterations_leakage
             public_loop_iterations_leakage
             xor_diff_one_iteration_leakage List.app].
        repeat rewrite word_array_index_as_mul.
        reflexivity.
      - SeparationLogic.seprewrite
          (initialized_word_array_index ptr1 n i Hlt).
        SeparationLogic.seprewrite
          (initialized_word_array_index ptr2 n i Hlt).
        unfold initialized_word.
        repeat rewrite word_array_index_as_mul.
        rewrite <- Hstride.
        extract_ex1_and_emp_in_goal.
        ecancel_assumption.
    }
    intro Hzero.
    destruct (word.ltu (word.of_Z (Z.of_nat i)) len) eqn:Hltu.
    { rewrite word.unsigned_of_Z_1 in Hzero; lia. }
    assert (Hindex_range : 0 <= Z.of_nat i < 2 ^ width).
    { pose proof (word.unsigned_range len). lia. }
    assert (Hi_eq : (i = n)%nat).
    { rewrite Interface.word.unsigned_ltu in Hltu.
      rewrite word.unsigned_of_Z_nowrap in Hltu by exact Hindex_range.
      apply Z.ltb_ge in Hltu.
      lia. }
    subst i.
    prove_leakage.
    all: try (rewrite HK; reflexivity).
    all: try exact HT.
  Qed.

  Lemma array_xor_diff_exact_call_leakage
      functions len ptr1 ptr2 n R k t m
      (Hfunction :
         map.get functions "array_xor_diff" =
           Some (@array_xor_diff_br2fn width word))
      (Hpre :
         word.unsigned len = Z.of_nat n /\
         (initialized_word_array ptr1 n
          * initialized_word_array ptr2 n * R)%sep m) :
    exact_call_leakage functions "array_xor_diff"
      [len; ptr1; ptr2] k t m
      (xor_diff_public_leakage ptr1 ptr2 n).
  Proof.
    pose proof array_xor_diff_leakage_ok as Hspec.
    cbv [LeakageProgramLogic.program_logic_goal_for] in Hspec.
    specialize (Hspec functions Hfunction len ptr1 ptr2 n R k t m Hpre).
    unfold exact_call_leakage.
    eapply LeakageSemantics.weaken_call; [exact Hspec|].
    intros final t' m' rets (diff & Hrets & Hfinal & Htrace).
    exact Hfinal.
  Qed.

  (** Two executions may start from unrelated memories and interaction traces.
      The content-agnostic array predicates allow every element, and hence the
      internal mismatch accumulator and returned result, to differ.  Equal
      public length and base addresses are sufficient for equal leakage. *)
  Lemma array_xor_diff_leakage_noninterference
      functions len ptr1 ptr2 n k t1 t2 m1 m2 R1 R2
      (Hfunction :
         map.get functions "array_xor_diff" =
           Some (@array_xor_diff_br2fn width word))
      (Hlen : word.unsigned len = Z.of_nat n)
      (Hmem1 :
         (initialized_word_array ptr1 n
          * initialized_word_array ptr2 n * R1)%sep m1)
      (Hmem2 :
         (initialized_word_array ptr1 n
          * initialized_word_array ptr2 n * R2)%sep m2) :
    call_leakage_two_run functions "array_xor_diff"
      [len; ptr1; ptr2] [len; ptr1; ptr2] k t1 t2 m1 m2.
  Proof.
    eapply exact_call_leakage_two_run
      with (delta1 := xor_diff_public_leakage ptr1 ptr2 n)
           (delta2 := xor_diff_public_leakage ptr1 ptr2 n).
    - reflexivity.
    - eapply array_xor_diff_exact_call_leakage; eauto.
    - eapply array_xor_diff_exact_call_leakage; eauto.
  Qed.
End WithParameters.
