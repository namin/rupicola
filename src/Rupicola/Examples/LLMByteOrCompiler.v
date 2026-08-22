Require Import Rupicola.Lib.Api.
Require Import Rupicola.Examples.LLMByteOrSpec.

(** This file is the LLM-proposed extension.  It follows the neighboring
    byte-[and] and byte-[xor] rules in [Rupicola.Lib.ExprCompiler]. *)
Section ByteOrCompiler.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.

  Lemma byte_unsigned_or (x y : byte) :
    byte.unsigned (byte_or x y) =
    Z.lor (byte.unsigned x) (byte.unsigned y).
  Proof.
    unfold byte_or; rewrite byte.unsigned_of_Z.
    unfold byte.wrap; rewrite <- Z.land_ones.
    1: bitblast.Z.bitblast.
    1: rewrite !testbit_byte_unsigned_ge.
    all: reflexivity || lia.
  Qed.

  Lemma byte_morph_or (x y : byte) :
    word_of_byte (byte_or x y) =
    word.or (word := word) (word_of_byte x) (word_of_byte y).
  Proof.
    rewrite byte_unsigned_or, word.morph_or; reflexivity.
  Qed.

  Context {m : mem} {l : locals}.

  Lemma expr_compile_byte_or
        (x y : byte) (ex ey : expr)
        (Hx : DEXPR m l ex (word_of_byte x))
        (Hy : DEXPR m l ey (word_of_byte y)) :
    DEXPR m l (expr.op bopname.or ex ey) (word_of_byte (byte_or x y)).
  Proof.
    rewrite byte_morph_or.
    eauto using expr_compile_word_or.
  Qed.
End ByteOrCompiler.

#[export] Hint Extern 5 (DPAT (word_of_byte (byte_or _ _))) =>
  simple eapply expr_compile_byte_or; shelve : expr_compiler.
