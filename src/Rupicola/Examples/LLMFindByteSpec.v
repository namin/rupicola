Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.

Definition find_byte_eqb (x y : byte) :=
  Z.eqb (byte.unsigned x) (byte.unsigned y).

(** Return the first matching index, or the array length when no byte matches. *)
Definition find_byte (bs : ListArray.t byte) (needle : byte) :=
  let/n r := Z.of_nat (length bs) in
  let/n r :=
    ranged_for 0 (Z.of_nat (length bs))
      (fun r tok idx _ =>
         let/n b := ListArray.get bs idx in
         let/n hit := find_byte_eqb b needle in
         if hit then
           let tok := ExitToken.break tok in
           (tok, idx)
         else
           (tok, r))
      r in
  r.

(** Independent, structurally recursive specification. *)
Fixpoint find_byte_spec (bs : list byte) (needle : byte) : Z :=
  match bs with
  | [] => 0
  | b :: bs' =>
      if find_byte_eqb b needle
      then 0
      else 1 + find_byte_spec bs' needle
  end.
