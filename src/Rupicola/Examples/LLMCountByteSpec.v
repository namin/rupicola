Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.

Definition count_byte_eqb (x y : byte) :=
  Z.eqb (byte.unsigned x) (byte.unsigned y).

Definition count_byte_step (needle : byte) (r : Z) (b : byte) :=
  let/n hit := count_byte_eqb b needle in
  let/n r := r + Z.b2z hit in
  r.

Definition count_byte (bs : ListArray.t byte) (needle : byte) :=
  let/n r := 0%Z in
  let/n r := ListArray.fold_left (count_byte_step needle) bs r in
  r.

(** Independent, structurally recursive specification. *)
Fixpoint count_byte_spec (bs : list byte) (needle : byte) : Z :=
  match bs with
  | [] => 0
  | b :: bs' =>
      Z.b2z (count_byte_eqb b needle) + count_byte_spec bs' needle
  end.
