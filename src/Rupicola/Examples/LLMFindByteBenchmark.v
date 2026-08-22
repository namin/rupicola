Require Import Rupicola.Lib.Api.
Require Import Rupicola.Lib.Arrays.
Require Import Rupicola.Lib.Loops.
Require Import Rupicola.Examples.LLMFindByteSpec.
Require Import Rupicola.Examples.LLMFindByteProof.

Section Benchmark.
  Context {width : Z} {BW : Bitwidth width} {word : word.word width}.
  Context {mem : map.map word Byte.byte} {locals : map.map String.string word}.
  Context {ext_spec : bedrock2.Semantics.ExtSpec}.
  Context {word_ok : word.ok word} {mem_ok : map.ok mem}.
  Context {locals_ok : map.ok locals}.
  Context {ext_spec_ok : Semantics.ext_spec.ok ext_spec}.

  Notation bytes := (sizedlistarray_value access_size.one).

  Instance spec_of_find_byte : spec_of "find_byte" :=
    fnspec! "find_byte" ptr wlen wneedle /
            (bs : ListArray.t byte) needle R ~> r,
      { requires tr mem :=
          wneedle = word.of_Z (byte.unsigned needle) /\
          wlen = word.of_Z (Z.of_nat (length bs)) /\
          Z.of_nat (length bs) < 2 ^ width /\
          (bytes (length bs) ptr bs ⋆ R) mem;
        ensures tr' mem' :=
          tr' = tr /\ r = word.of_Z (find_byte bs needle) /\
          find_byte bs needle = find_byte_spec bs needle /\
          (bytes (length bs) ptr bs ⋆ R) mem' }.

  Import LoopCompiler.
  Import SizedListArrayCompiler.
  Hint Extern 10 => lia : compiler_side_conditions.
  Hint Unfold find_byte_eqb : compiler_cleanup.

  Derive find_byte_br2fn in
         (defn! "find_byte" ("bs", "len", "needle") ~> "r"
            { find_byte_br2fn },
          implements find_byte)
         as find_byte_br2fn_ok.
  Proof.
    let compile_find_byte_step :=
      tryif (let p := compile_find_post in
             lazymatch p with
             | (_, (ExitToken.break _, _)) => idtac
             end)
      then (simple eapply compile_break_transition
              with (bound := Z.of_nat (length bs))
                   (value := from')
                   (bound_expr := expr.var (@gs "to" 0 "_gs_to0"))
                   (value_expr := expr.var (@gs "from" 0 "_gs_from0"))
                   (from_var := @gs "from" 0 "_gs_from0")
                   (result_var := "r")
                   (vars := ["b"; "hit"]);
            unfold ExitToken.branch, ExitToken.get,
                   ExitToken.break, ExitToken.new;
            cbn [fst snd])
      else compile_step in
    compile_setup; repeat repeat compile_find_byte_step.
    all: try (apply expr_compile_var;
              try rewrite map.get_put_diff by (unfold gs; congruence);
              unfold map.remove_many; cbn [List.fold_left];
              rewrite !map.get_remove_diff by (unfold gs; congruence);
              solve_map_get_goal).
    unfold lp, ExitToken.branch, ExitToken.get,
           ExitToken.break, ExitToken.new.
    cbn [fst snd].
    split; [reflexivity|split].
    - unfold map.remove_many; cbn [List.fold_left].
      unfold gs.
      eapply map.map_ext; intros key.
      repeat first
        [ rewrite map.get_put_dec
        | rewrite map.get_remove_dec
        | rewrite map.get_empty
        | match goal with
          | |- context [if ?test then _ else _] =>
              destr test; try congruence
          end ].
    - assumption.
  Qed.
End Benchmark.
