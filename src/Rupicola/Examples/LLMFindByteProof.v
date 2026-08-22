Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.
Require Import Rupicola.Examples.LLMFindByteSpec.

Section BreakCompiler.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {memT : map.map word Byte.byte} {localsT : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok memT}.
  Context {locals_ok : map.ok localsT}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  (** Materialize an exit-token transition in the runtime loop counter.  The
      generic ranged-loop compiler increments the counter after its body, so a
      break branch writes [bound - 1]. *)
  Lemma compile_break_transition {tr mem locals functions}
        (bound value : Z) (bound_expr value_expr : expr)
        (from_var result_var : string) (vars : list string)
        (post : predicate) :
    WeakestPrecondition.dexpr
      mem (map.remove_many locals vars) value_expr (word.of_Z value) ->
    WeakestPrecondition.dexpr
      mem
      (map.put (map.remove_many locals vars) result_var (word.of_Z value))
      bound_expr (word.of_Z bound) ->
    post tr mem
      (map.put
         (map.put (map.remove_many locals vars) result_var (word.of_Z value))
         from_var (word.of_Z (bound - 1))) ->
    <{ Trace := tr;
       Memory := mem;
       Locals := locals;
       Functions := functions }>
      fold_right
        (fun var cmd => cmd.seq (cmd.unset var) cmd)
        (cmd.seq
           (cmd.set result_var value_expr)
           (cmd.set from_var
              (expr.op bopname.sub bound_expr (expr.literal 1))))
        vars
    <{ post }>.
  Proof.
    intros Hvalue Hbound Hpost.
    apply compile_unsets.
    repeat straightline.
    exists (word.of_Z value); split.
    - exact Hvalue.
    - exists (word.of_Z (bound - 1)); split.
      + eapply expr_compile_Z_sub.
        * exact Hbound.
        * apply expr_compile_Z_literal.
      + exact Hpost.
  Qed.
End BreakCompiler.

(** Shifted form of the search loop.  It lets the induction hypothesis describe
    the unprocessed suffix after a nonmatching head byte. *)
Definition find_byte_from (bs : list byte) (needle : byte) (base : Z) :=
  ranged_for base (base + Z.of_nat (length bs))
    (fun r tok idx _ =>
       let/n b := ListArray.get bs (idx - base) in
       let/n hit := find_byte_eqb b needle in
       if hit then (ExitToken.break tok, idx) else (tok, r))
    (base + Z.of_nat (length bs)).

Lemma listarray_get_cons_shift (b : byte) (bs : list byte) (base idx : Z) :
  base < idx ->
  ListArray.get (b :: bs) (idx - base) =
  ListArray.get bs (idx - (base + 1)).
Proof.
  intros Hidx.
  unfold ListArray.get, cast, Convertible_Z_nat.
  replace (Z.to_nat (idx - base))
    with (S (Z.to_nat (idx - (base + 1)))) by lia.
  reflexivity.
Qed.

Lemma find_byte_from_ok bs needle base :
  find_byte_from bs needle base = base + find_byte_spec bs needle.
Proof.
  revert base; induction bs as [| b bs IH]; intros base.
  - unfold find_byte_from, ranged_for, ranged_for'.
    rewrite ranged_for_break_exit by (cbn; lia).
    cbn; lia.
  - unfold find_byte_from, ranged_for, ranged_for' at 1.
    rewrite ranged_for_break_unfold_l.
    destruct Z_lt_dec as [Hlt | Hnlt]; [|cbn in Hnlt; lia].
    replace (base - base) with 0 by lia.
    assert (ListArray.get (b :: bs) (0 : Z) = b) as Hhead.
    { unfold ListArray.get, cast, Convertible_Z_nat.
      rewrite Z2Nat.inj_0; reflexivity. }
    rewrite Hhead.
    unfold nlet.
    cbn [ExitToken.get ExitToken.new].
    destruct (find_byte_eqb b needle) eqn:Hb.
    + rewrite ranged_for_break_stop by reflexivity.
      cbn [find_byte_spec]; rewrite Hb.
      unfold ExitToken.get, ExitToken.new, ExitToken.break.
      cbn; lia.
    + unfold ExitToken.get, ExitToken.new, ExitToken.break.
      cbn [find_byte_spec]; rewrite Hb.
      cbn [fst snd].
      replace (base + Z.of_nat (length (b :: bs)))
        with (base + 1 + Z.of_nat (length bs)) by (cbn -[Z.of_nat]; lia).
      set (head_body :=
        fun (acc : ExitToken.t * Z) (idx : Z)
            (_ : base + 1 - 1 < idx < base + 1 + Z.of_nat (length bs)) =>
          if find_byte_eqb (ListArray.get (b :: bs) (idx - base)) needle
          then (true, idx)
          else (false, snd acc)).
      set (tail_body :=
        fun (acc : ExitToken.t * Z) (idx : Z)
            (_ : base + 1 - 1 < idx < base + 1 + Z.of_nat (length bs)) =>
          if find_byte_eqb (ListArray.get bs (idx - (base + 1))) needle
          then (true, idx)
          else (false, snd acc)).
      change (snd (ranged_for_break
                     (base + 1) (base + 1 + Z.of_nat (length bs))
                     head_body (fun tok_acc => fst tok_acc)
                     (false, base + 1 + Z.of_nat (length bs))) =
              base + (1 + find_byte_spec bs needle)).
      assert (Hbody : forall acc idx pr,
                 head_body acc idx pr = tail_body acc idx pr).
      { intros [tok acc] idx pr.
        unfold head_body, tail_body.
        rewrite listarray_get_cons_shift by lia.
        reflexivity. }
      pose proof
        (@ranged_for_break_Proper_irrelevant
           (ExitToken.t * Z)
           (base + 1) (base + 1 + Z.of_nat (length bs))
           head_body tail_body
           (fun tok_acc => fst tok_acc) (fun tok_acc => fst tok_acc)
           (false, base + 1 + Z.of_nat (length bs))
           (false, base + 1 + Z.of_nat (length bs))
           eq_refl Hbody (fun _ => eq_refl)) as Hloop.
      rewrite Hloop.
      unfold tail_body.
      change (find_byte_from bs needle (base + 1) =
              base + (1 + find_byte_spec bs needle)).
      rewrite IH; lia.
Qed.

Lemma find_byte_as_from bs needle :
  find_byte bs needle = find_byte_from bs needle 0.
Proof.
  unfold find_byte, find_byte_from, nlet.
  replace (0 + Z.of_nat (length bs)) with (Z.of_nat (length bs)) by lia.
  unfold ranged_for.
  f_equal.
  apply ranged_for'_Proper; try reflexivity.
  intros r tok idx Hidx Hidx'.
  replace (idx - 0) with idx by lia.
  reflexivity.
Qed.

Lemma find_byte_ok bs needle :
  find_byte bs needle = find_byte_spec bs needle.
Proof.
  rewrite find_byte_as_from, find_byte_from_ok; lia.
Qed.

Section ByteBounds.
  Context {width : Z} {BW : Bitwidth width}.

  Lemma find_byte_eq_word_bounds (x y : byte) :
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

#[export] Hint Resolve find_byte_ok
                       find_byte_eq_word_bounds
  : compiler_side_conditions.
