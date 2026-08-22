Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.

(** A deliberately fresh byte operation: coqutil's byte API currently exposes
    [and] and [xor], but not bitwise [or]. *)
Definition byte_or (x y : byte) : byte :=
  byte.of_Z (Z.lor (byte.unsigned x) (byte.unsigned y)).

Definition byte_or_scalar (x y : byte) :=
  let/n r := byte_or x y in
  r.

Definition or_mask_bytes (bs : ListArray.t byte) (mask : byte) :=
  let/n bs := ListArray.map (byte_or mask) bs in
  bs.
