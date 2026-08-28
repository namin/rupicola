From Stdlib Require Import ZArith.ZArith Lists.List Lia.
Require Import coqutil.Word.Bitwidth coqutil.Word.Interface.
Require Import coqutil.Word.Properties.
Require Import coqutil.Map.Interface coqutil.Map.Properties coqutil.Byte.
Require Import bedrock2.Array bedrock2.Scalars.
Require Import bedrock2.LeakageSemantics.
Require Import bedrock2.Map.SeparationLogic.

Import List.ListNotations.
Import SeparationLogic.
Local Open Scope list_scope.

(** A small support library for exact-trace constant-time proofs.

    The predicates in this file deliberately forget memory contents.  They
    state only that the words a public trace will access are initialized.  A
    leakage theorem can therefore quantify over arbitrary secret data while
    still using Bedrock2's separation-logic rules for loads and stores. *)

(* Keep symbolic execution from eagerly decomposing a loop invariant.  The
   sealed implementation is logically the identity, but tactics cannot unfold
   it while executing a generated loop body. *)
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

(** Bedrock2 prepends leakage events.  A public loop's final event is therefore
    the failed loop test, followed by successful iteration blocks in descending
    index order.  Kernels supply only the public trace of one iteration. *)
Section WithLeakageParameters.
  Context {width: Z} {BW: Bitwidth width} {word: word.word width}.

  Fixpoint public_loop_iterations_leakage
      (one_iteration : nat -> LeakageSemantics.leakage)
      (count : nat) : LeakageSemantics.leakage :=
    match count with
    | O => []
    | S count' =>
        one_iteration count' ++
        public_loop_iterations_leakage one_iteration count'
    end.

  Definition public_loop_leakage
      (one_iteration : nat -> LeakageSemantics.leakage)
      (count : nat) : LeakageSemantics.leakage :=
    LeakageSemantics.leak_bool false ::
    public_loop_iterations_leakage one_iteration count.

  Lemma public_loop_iterations_leakage_succ one_iteration count :
    public_loop_iterations_leakage one_iteration (S count) =
    one_iteration count ++
    public_loop_iterations_leakage one_iteration count.
  Proof. reflexivity. Qed.
End WithLeakageParameters.

(** A relational interface for the security result exposed by exact-trace
    specifications.  [call_leakage_two_run] is a product-program judgment: the
    second Bedrock2 call is checked in the postcondition of the first, and the
    two final leakage traces must agree.  The initial interaction traces and
    memories may differ; only the initial leakage prefix is shared.

    A kernel normally proves [exact_call_leakage] twice, once for each secret
    state.  If both public trace deltas agree, the generic theorem below turns
    those unary certificates into the desired two-run statement. *)
Section TwoRunInterface.
  Context {width: Z} {BW: Bitwidth width}.
  Context {word: word.word width} {mem: map.map word Byte.byte}.
  Context {locals: map.map String.string word}.
  Context {ext_spec: LeakageSemantics.ExtSpec}.
  Context {pick_sp: LeakageSemantics.PickSp}.

  Definition exact_call_leakage
      (functions : Semantics.env) (fname : String.string)
      (args : list word) (initial : LeakageSemantics.leakage)
      (t : Semantics.trace) (m : mem)
      (public_delta : LeakageSemantics.leakage) : Prop :=
    LeakageSemantics.call functions fname initial t m args
      (fun final _ _ _ => final = public_delta ++ initial).

  Definition call_leakage_two_run
      (functions : Semantics.env) (fname : String.string)
      (args1 args2 : list word) (initial : LeakageSemantics.leakage)
      (t1 t2 : Semantics.trace) (m1 m2 : mem) : Prop :=
    LeakageSemantics.call functions fname initial t1 m1 args1
      (fun final1 _ _ _ =>
         LeakageSemantics.call functions fname initial t2 m2 args2
           (fun final2 _ _ _ => final1 = final2)).

  Lemma exact_call_leakage_two_run
      functions fname args1 args2 initial t1 t2 m1 m2 delta1 delta2
      (Hdeltas : delta1 = delta2)
      (Hrun1 : exact_call_leakage
         functions fname args1 initial t1 m1 delta1)
      (Hrun2 : exact_call_leakage
         functions fname args2 initial t2 m2 delta2) :
    call_leakage_two_run
      functions fname args1 args2 initial t1 t2 m1 m2.
  Proof.
    unfold exact_call_leakage in Hrun1, Hrun2.
    unfold call_leakage_two_run.
    eapply LeakageSemantics.weaken_call; [exact Hrun1|].
    intros final1 t1' m1' rets1 Hfinal1.
    eapply LeakageSemantics.weaken_call; [exact Hrun2|].
    intros final2 t2' m2' rets2 Hfinal2.
    rewrite Hfinal1, Hfinal2, Hdeltas.
    reflexivity.
  Qed.
End TwoRunInterface.

Section WithParameters.
  Context {width: Z} {BW: Bitwidth width}.
  Context {word: word.word width} {mem: map.map word Byte.byte}.
  Context {word_ok: word.ok word} {mem_ok: map.ok mem}.

  Definition word_array_stride : word :=
    word.of_Z
      (Z.of_nat (@Memory.bytes_per width Syntax.access_size.word)).

  Definition word_array_index (base : word) (i : nat) : word :=
    word.add base
      (word.of_Z (word.unsigned word_array_stride * Z.of_nat i)).

  Definition initialized_word (addr : word) (_ : unit) : mem -> Prop :=
    Lift1Prop.ex1 (fun value => Scalars.scalar addr value).

  Definition initialized_word_array
      (base : word) (n : nat) : mem -> Prop :=
    Array.array initialized_word word_array_stride base (List.repeat tt n).

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
End WithParameters.

(** Normalize lookups in the compiler-generated locals map.  Generated loop
    bodies introduce and remove temporary variables, so a proof should not
    depend on their exact nesting beyond extensional map equality. *)
Ltac normalize_generated_map_get :=
  repeat first
    [ rewrite map.get_put_dec
    | rewrite map.get_remove_dec
    | rewrite map.get_empty
    | match goal with
      | |- context [@map.get _ _ _ ?m _] =>
          is_var m; cbv delta [m]
      end ].
