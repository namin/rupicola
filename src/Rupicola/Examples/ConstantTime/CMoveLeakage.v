Require Import Rupicola.Examples.CMove.CMove.
Require Import Rupicola.Examples.Cells.Cells.
From Stdlib Require Import ZArith.ZArith Strings.String.
Require Import coqutil.Word.Bitwidth coqutil.Word.Interface.
Require Import coqutil.Map.Interface coqutil.Byte.
Require Import coqutil.Map.Properties.
Require Import bedrock2.LeakageSemantics.
Require Import bedrock2.LeakageWeakestPrecondition.
Require Import bedrock2.LeakageProgramLogic.
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
End WithParameters.
