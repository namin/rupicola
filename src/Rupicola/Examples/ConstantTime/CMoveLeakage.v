Require Import Rupicola.Examples.CMove.CMove.
Require Import Rupicola.Examples.Cells.Cells.
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

(* Keep symbolic execution from eagerly decomposing a loop invariant.  The
   sealed implementation is logically the identity, but tactics cannot unfold
   it while executing the generated loop body. *)
Module Type LeakageProofFenceSig.
  Parameter t : Prop -> Prop.
  Parameter intro : forall P, P -> t P.
  Parameter elim : forall P, t P -> P.
End LeakageProofFenceSig.

Module LeakageProofFence : LeakageProofFenceSig.
  Definition t (P : Prop) : Prop := P.
  Definition intro P : P -> t P := fun H => H.
  Definition elim P : t P -> P := fun H => H.
End LeakageProofFence.

Section WithParameters.
  Context {width: Z} {BW: Bitwidth width}.
  Context {word: word.word width} {mem: map.map word Byte.byte}.
  Context {locals: map.map String.string word}.
  Context {ext_spec: LeakageSemantics.ExtSpec}.
  Context {word_ok: word.ok word} {mem_ok: map.ok mem}.
  Context {locals_ok: map.ok locals}.
  Context {ext_spec_ok: LeakageSemantics.ext_spec.ok ext_spec}.
  Context {pick_sp: LeakageSemantics.PickSp}.
  Local Notation cell := (@cell width BW word).

  (* Leakage events are prepended by Bedrock2, so these lists are in reverse
     execution order.  Their arguments are precisely the public inputs. *)
  Definition cmove_word_public_leakage (ptr1 ptr2 : word) : leakage :=
    [leak_word ptr1; leak_word ptr2; leak_word ptr1].

  Definition cswap_word_public_leakage (ptr1 ptr2 : word) : leakage :=
    [leak_word ptr2; leak_word ptr1; leak_word ptr2; leak_word ptr1].

  Local Ltac prove_word_leakage :=
    repeat straightline;
    repeat match goal with
           | H : context[cell_value] |- _ => unfold cell_value in H
           end;
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

  Local Ltac normalize_generated_map_get :=
    repeat first
      [ rewrite map.get_put_dec
      | rewrite map.get_remove_dec
      | rewrite map.get_empty
      | match goal with
        | |- context [@map.get _ _ _ ?m _] =>
            is_var m; cbv delta [m]
        end ].

  Definition cmove_word_leakage_spec : spec_of "cmove_word" :=
    fnspec! "cmove_word" (mask ptr1 ptr2 : word) /
      (c1 c2 : cell) (R : mem -> Prop),
      { requires k t m :=
          (cell_value ptr1 c1 * cell_value ptr2 c2 * R)%sep m;
        ensures k' t' m' :=
          k' = cmove_word_public_leakage ptr1 ptr2 ++ k /\
          t' = t }.

  Lemma cmove_word_leakage_ok :
    program_logic_goal_for (@cmove_word_br2fn width word)
      (forall functions : Semantics.env,
        map.get functions "cmove_word" =
          Some (@cmove_word_br2fn width word) ->
        cmove_word_leakage_spec functions).
  Proof.
    prove_word_leakage.
  Qed.

  Definition cswap_word_leakage_spec : spec_of "cswap_word" :=
    fnspec! "cswap_word" (mask ptr1 ptr2 : word) /
      (c1 c2 : cell) (R : mem -> Prop),
      { requires k t m :=
          (cell_value ptr1 c1 * cell_value ptr2 c2 * R)%sep m;
        ensures k' t' m' :=
          k' = cswap_word_public_leakage ptr1 ptr2 ++ k /\
          t' = t }.

  Lemma cswap_word_leakage_ok :
    program_logic_goal_for (@cswap_word_br2fn width word)
      (forall functions : Semantics.env,
        map.get functions "cswap_word" =
          Some (@cswap_word_br2fn width word) ->
        cswap_word_leakage_spec functions).
  Proof.
    prove_word_leakage.
  Qed.

  Definition word_array_stride : word :=
    word.of_Z (Z.of_nat (@Memory.bytes_per width Syntax.access_size.word)).

  Definition word_array_index (base : word) (i : nat) : word :=
    word.add base
      (word.of_Z (word.unsigned word_array_stride * Z.of_nat i)).

  Definition initialized_word (addr : word) (_ : unit) : mem -> Prop :=
    Lift1Prop.ex1 (fun value => Scalars.scalar addr value).

  Definition initialized_word_array (base : word) (n : nat) : mem -> Prop :=
    Array.array initialized_word word_array_stride base (List.repeat tt n).

  Definition array_loop_locals
      (mask len ptr1 ptr2 from nmask index : word) : locals :=
    map.put
      (map.put
        (map.put
          (map.put
            (map.put
              (map.put
                (map.put
                  (map.put map.empty "mask" mask) "len" len)
                "a1" ptr1)
              "a2" ptr2)
            "from" from)
          "nmask" nmask)
        "_gs_from0" index)
      "_gs_to0" len.

  Lemma word_of_Z_nat_succ i :
    (word.add (word.of_Z (Z.of_nat i)) (word.of_Z 1) : word) =
    word.of_Z (Z.of_nat (S i)).
  Proof.
    rewrite <- word.ring_morph_add.
    f_equal; lia.
  Qed.

  Lemma word_array_index_as_mul base i :
    word_array_index base i =
    word.add base (word.mul word_array_stride (word.of_Z (Z.of_nat i))).
  Proof.
    unfold word_array_index.
    rewrite word.ring_morph_mul, word.of_Z_unsigned.
    reflexivity.
  Qed.

  Lemma initialized_word_array_index base n i (H : (i < n)%nat) :
    Lift1Prop.iff1
      (initialized_word_array base n)
      (Array.array initialized_word word_array_stride base
         (List.firstn i (List.repeat tt n))
       * (initialized_word (word_array_index base i)
            (List.hd tt (List.skipn i (List.repeat tt n)))
          * Array.array initialized_word word_array_stride
              (word.add (word_array_index base i) word_array_stride)
              (List.skipn (S i) (List.repeat tt n))))%sep.
  Proof.
    unfold initialized_word_array, word_array_index.
    eapply Array.array_index_nat_inbounds.
    rewrite List.repeat_length; exact H.
  Qed.

  Definition cmove_array_one_iteration_leakage
      (ptr1 ptr2 : word) (i : nat) : leakage :=
    [leak_word (word_array_index ptr1 i);
     leak_word (word_array_index ptr2 i);
     leak_word (word_array_index ptr1 i);
     leak_bool true].

  Fixpoint cmove_array_iterations_leakage
      (ptr1 ptr2 : word) (count : nat) : leakage :=
    match count with
    | O => []
    | S count' =>
        cmove_array_one_iteration_leakage ptr1 ptr2 count' ++
        cmove_array_iterations_leakage ptr1 ptr2 count'
    end.

  Definition cmove_array_public_leakage
      (ptr1 ptr2 : word) (n : nat) : leakage :=
    leak_bool false :: cmove_array_iterations_leakage ptr1 ptr2 n.

  Definition cswap_array_one_iteration_leakage
      (ptr1 ptr2 : word) (i : nat) : leakage :=
    [leak_word (word_array_index ptr2 i);
     leak_word (word_array_index ptr1 i);
     leak_word (word_array_index ptr2 i);
     leak_word (word_array_index ptr1 i);
     leak_bool true].

  Fixpoint cswap_array_iterations_leakage
      (ptr1 ptr2 : word) (count : nat) : leakage :=
    match count with
    | O => []
    | S count' =>
        cswap_array_one_iteration_leakage ptr1 ptr2 count' ++
        cswap_array_iterations_leakage ptr1 ptr2 count'
    end.

  Definition cswap_array_public_leakage
      (ptr1 ptr2 : word) (n : nat) : leakage :=
    leak_bool false :: cswap_array_iterations_leakage ptr1 ptr2 n.

  Definition cmove_array_leakage_spec : spec_of "cmove_array" :=
    fnspec! "cmove_array" (mask len ptr1 ptr2 : word) /
      (n : nat) (R : mem -> Prop),
      { requires k t m :=
          word.unsigned len = Z.of_nat n /\
          (initialized_word_array ptr1 n
           * initialized_word_array ptr2 n * R)%sep m;
        ensures k' t' m' :=
          k' = cmove_array_public_leakage ptr1 ptr2 n ++ k /\
          t' = t }.

  Definition cswap_array_leakage_spec : spec_of "cswap_array" :=
    fnspec! "cswap_array" (mask len ptr1 ptr2 : word) /
      (n : nat) (R : mem -> Prop),
      { requires k t m :=
          word.unsigned len = Z.of_nat n /\
          (initialized_word_array ptr1 n
           * initialized_word_array ptr2 n * R)%sep m;
        ensures k' t' m' :=
          k' = cswap_array_public_leakage ptr1 ptr2 n ++ k /\
          t' = t }.

  Lemma cmove_array_leakage_ok :
    program_logic_goal_for (@cmove_array_br2fn width word)
      (forall functions : Semantics.env,
        map.get functions "cmove_array" =
          Some (@cmove_array_br2fn width word) ->
        cmove_array_leakage_spec functions).
  Proof.
    prove_word_leakage.
    lazymatch goal with
    | |- LeakageSemantics.exec ?functions
           (Syntax.cmd.while ?condition ?body) ?K ?T ?M ?L ?post =>
        change (LeakageWeakestPrecondition.cmd functions
                  (Syntax.cmd.while condition body) K T M L post)
    end.
    eapply LeakageLoops.wp_while.
    eexists nat, Nat.lt,
      (fun remaining K T M L =>
         exists i nmask,
           (i <= n)%nat /\
           map.get L "mask" = Some mask /\
           map.get L "len" = Some len /\
           map.get L "a1" = Some ptr1 /\
           map.get L "a2" = Some ptr2 /\
           map.get L "nmask" = Some nmask /\
           map.get L "_gs_from0" = Some (word.of_Z (Z.of_nat i)) /\
           map.get L "_gs_to0" = Some len /\
           L = array_loop_locals mask len ptr1 ptr2 from nmask
                 (word.of_Z (Z.of_nat i)) /\
           K = cmove_array_iterations_leakage ptr1 ptr2 i ++ k /\
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
      all: try unfold array_loop_locals.
      all: repeat rewrite Hgs0.
      all: try rewrite word.of_Z_unsigned.
      all: cbn [cmove_array_iterations_leakage List.app].
      all: try reflexivity.
      all: try apply Nat.le_0_l.
      all: try ecancel_assumption.
      all: try lia.
      all: reflexivity. }
    intros remaining K T M L
      (i & nmask & Hi & Hmask & Hlen & Ha1 & Ha2 & Hnmask &
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
      assert (Hindex_range :
                0 <= Z.of_nat i < 2 ^ width).
      { pose proof (word.unsigned_range len). lia. }
      assert (Hlt : (i < n)%nat).
      { rewrite Interface.word.unsigned_ltu in Hltu.
        rewrite word.unsigned_of_Z_nowrap in Hltu by exact Hindex_range.
        apply Z.ltb_lt in Hltu. lia. }
      unfold array_loop_locals in Hlocals.
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
      prove_word_leakage.
      all: try lazymatch goal with
      | |- @map.get _ _ _ _ _ = _ =>
          normalize_generated_map_get;
          cbn;
          reflexivity
      end.
      apply LeakageProofFence.intro.
      exists (n - S i)%nat.
      split; [|lia].
      exists (S i), nmask.
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
      - unfold array_loop_locals.
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
                 (word.add ptr1
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_word
                 (word.add ptr2
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_word
                 (word.add ptr1
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_bool true ::
                 cmove_array_iterations_leakage ptr1 ptr2 i ++ k =
               cmove_array_iterations_leakage ptr1 ptr2 (S i) ++ k)
        end.
        cbn [cmove_array_iterations_leakage
             cmove_array_one_iteration_leakage List.app].
        repeat rewrite word_array_index_as_mul.
        rewrite <- Hstride.
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
    split; [reflexivity|].
    split.
    - rewrite HK; reflexivity.
    - exact HT.
  Qed.

  Lemma cswap_array_leakage_ok :
    program_logic_goal_for (@cswap_array_br2fn width word)
      (forall functions : Semantics.env,
        map.get functions "cswap_array" =
          Some (@cswap_array_br2fn width word) ->
        cswap_array_leakage_spec functions).
  Proof.
    prove_word_leakage.
    lazymatch goal with
    | |- LeakageSemantics.exec ?functions
           (Syntax.cmd.while ?condition ?body) ?K ?T ?M ?L ?post =>
        change (LeakageWeakestPrecondition.cmd functions
                  (Syntax.cmd.while condition body) K T M L post)
    end.
    eapply LeakageLoops.wp_while.
    eexists nat, Nat.lt,
      (fun remaining K T M L =>
         exists i nmask,
           (i <= n)%nat /\
           map.get L "mask" = Some mask /\
           map.get L "len" = Some len /\
           map.get L "a1" = Some ptr1 /\
           map.get L "a2" = Some ptr2 /\
           map.get L "nmask" = Some nmask /\
           map.get L "_gs_from0" = Some (word.of_Z (Z.of_nat i)) /\
           map.get L "_gs_to0" = Some len /\
           L = array_loop_locals mask len ptr1 ptr2 from nmask
                 (word.of_Z (Z.of_nat i)) /\
           K = cswap_array_iterations_leakage ptr1 ptr2 i ++ k /\
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
      all: try unfold array_loop_locals.
      all: repeat rewrite Hgs0.
      all: try rewrite word.of_Z_unsigned.
      all: cbn [cswap_array_iterations_leakage List.app].
      all: try reflexivity.
      all: try apply Nat.le_0_l.
      all: try ecancel_assumption.
      all: try lia.
      all: reflexivity. }
    intros remaining K T M L
      (i & nmask & Hi & Hmask & Hlen & Ha1 & Ha2 & Hnmask &
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
      assert (Hindex_range :
                0 <= Z.of_nat i < 2 ^ width).
      { pose proof (word.unsigned_range len). lia. }
      assert (Hlt : (i < n)%nat).
      { rewrite Interface.word.unsigned_ltu in Hltu.
        rewrite word.unsigned_of_Z_nowrap in Hltu by exact Hindex_range.
        apply Z.ltb_lt in Hltu. lia. }
      unfold array_loop_locals in Hlocals.
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
      prove_word_leakage.
      all: try lazymatch goal with
      | |- @map.get _ _ _ _ _ = _ =>
          normalize_generated_map_get;
          cbn;
          reflexivity
      end.
      apply LeakageProofFence.intro.
      exists (n - S i)%nat.
      split; [|lia].
      exists (S i), nmask.
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
      - unfold array_loop_locals.
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
               leak_word
                 (word.add ptr2
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_word
                 (word.add ptr1
                    (word.mul generated_stride (word.of_Z (Z.of_nat i)))) ::
               leak_bool true ::
                 cswap_array_iterations_leakage ptr1 ptr2 i ++ k =
               cswap_array_iterations_leakage ptr1 ptr2 (S i) ++ k)
        end.
        cbn [cswap_array_iterations_leakage
             cswap_array_one_iteration_leakage List.app].
        repeat rewrite word_array_index_as_mul.
        rewrite <- Hstride.
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
    split; [reflexivity|].
    split.
    - rewrite HK; reflexivity.
    - exact HT.
  Qed.
End WithParameters.
