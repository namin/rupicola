Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Examples.LLMCountByteSpec.

(** The generalized accumulator is the semantic loop invariant proposed by
    the LLM agent. *)
Lemma count_byte_fold_acc bs needle acc :
  ListArray.fold_left (count_byte_step needle) bs acc =
  acc + count_byte_spec bs needle.
Proof.
  unfold ListArray.fold_left.
  revert acc; induction bs as [| b bs IH]; intros acc.
  - cbn -[count_byte_step].
    rewrite Z.add_0_r; reflexivity.
  - cbn -[count_byte_step].
    rewrite IH.
    unfold count_byte_step, nlet; lia.
Qed.

Lemma count_byte_ok bs needle :
  count_byte bs needle = count_byte_spec bs needle.
Proof.
  unfold count_byte, nlet.
  rewrite count_byte_fold_acc; lia.
Qed.

Section ByteBounds.
  Context {width : Z} {BW : Bitwidth width}.

  Lemma count_byte_eq_word_bounds (x y : byte) :
    (0 <= byte.unsigned x < 2 ^ width /\
     0 <= byte.unsigned y < 2 ^ width) \/
    (- 2 ^ (width - 1) <= byte.unsigned x < 2 ^ (width - 1) /\
     - 2 ^ (width - 1) <= byte.unsigned y < 2 ^ (width - 1)).
  Proof.
    destruct width_cases as [-> | ->]; left; split;
      pose proof (byte.unsigned_range x);
      pose proof (byte.unsigned_range y); cbn in *; lia.
  Qed.
End ByteBounds.

#[export] Hint Resolve count_byte_ok
                       count_byte_eq_word_bounds
  : compiler_side_conditions.
