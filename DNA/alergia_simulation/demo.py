"""
demo.py

1. Reproduces the paper's own toy example (Figs 8-11, Table 1) as a
   correctness check for the implementation.
2. Runs the same pipeline on a small DNA-codon-group-style example so it
   ties back to the actual project.
3. Saves step-by-step diagrams for both, for use in the presentation.
"""

import os
from alergia import build_pta, run_alergia, differ, compatible
from visualize import draw_automaton

OUT = "/home/claude/output_images"
os.makedirs(OUT, exist_ok=True)


def print_table1(pta):
    """Print the frequency-statistics table in the same shape as the
    paper's Table 1, for direct visual comparison."""
    live = pta.live_states_in_order()
    print(f"{'i':>4} | {'n_i':>4} | {'f_i(#)':>7} | " +
          " | ".join(f"f_i({a})" for a in pta.alphabet))
    print("-" * (4 + 4 + 7 + sum(9 for _ in pta.alphabet) + 9))
    for s in live:
        st = pta.states[s]
        row = f"{s:>4} | {st['n']:>4} | {st['f_end']:>7} | "
        row += " | ".join(f"{st['f'][a]:>6}" for a in pta.alphabet)
        print(row)


# ---------------------------------------------------------------------------
# PART 1: Paper's toy binary example (Section 4, Figs 8-11, Table 1)
# ---------------------------------------------------------------------------
print("=" * 70)
print("PART 1: Reproducing the paper's toy example (S, alpha=0.7)")
print("=" * 70)

# S = {lambda, lambda, 01, 01, 001, 001, 001, 011, 00101, 00101}
S = [
    [], [],
    ["0", "1"], ["0", "1"],
    ["0", "0", "1"], ["0", "0", "1"], ["0", "0", "1"],
    ["0", "1", "1"],
    ["0", "0", "1", "0", "1"], ["0", "0", "1", "0", "1"],
]
alphabet = ["0", "1"]

pta = build_pta(S, alphabet)
print("\nInitial PTA frequency statistics (should match paper's Table 1):\n")
print_table1(pta)
draw_automaton(pta, "Initial PTA (8 states) - matches Fig. 8",
                f"{OUT}/toy_step0_pta.png")

print("\nRunning Alergia merge steps (alpha=0.7)...\n")
pta2, log = run_alergia(S, alphabet, alpha=0.7, verbose=True)

for step, (i, j, _) in enumerate(log, start=1):
    # Redraw current live automaton after each merge for a step-by-step view
    draw_automaton(pta2, f"After merge step {step}: state {j} -> state {i}",
                   f"{OUT}/toy_step{step}.png", highlight={i})

print(f"\nSaved {len(log) + 1} diagrams to {OUT}/toy_step*.png")

print("\nFinal transition table:")
for s, a, c in pta2.transition_table():
    print(f"  delta({s}, {a}) = {c}")

# Sanity check against the paper's own worked example: it states nodes
# 2,3,5,7 end up compatible/merged, and 4,6 end up compatible/merged.
merged_pairs = [(i, j) for i, j, _ in log]
print(f"\nMerge order found: {merged_pairs}")
print("(Paper's own narrative: 2&3 merge, then 2&5, then 2&7 and 4&6 -- "
      "compare this to the merge order above; exact numbering may differ "
      "slightly by traversal order but the SAME states should end up grouped.)")

# Paper's test set Q, used to demonstrate acceptance-rate scoring
Q = [
    list("101"),
    list("01111"),
    list("0101010"),
    list("11011"),
    list("001010101"),
]
rate = pta2.acceptance_rate(Q)
print(f"\nAcceptance rate on paper's test set Q: {rate * 100:.0f}% "
      f"(paper reports 40% for its own merge outcome)")


# ---------------------------------------------------------------------------
# PART 2: Small DNA-codon-group-style example (ties back to the project)
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("PART 2: Small DNA-codon-group-style example")
print("=" * 70)

# Using the paper's own 4 sample training strings (Chapter 4), converted to
# numerical amino-acid-group codes. Using strings as lists of symbols
# (as strings, including "-1" as the stop-codon symbol).
dna_strings_raw = [
    "0 0 0 3 0 1 0 0 3 0 0 3 -1",
    "0 3 0 1 3 0 0 1 1 0 0 1 1 3 3 1 0 0 0 1 0 0 0 3 1 1 -1",
    "0 3 1 3 1 -1",
    "0 0 0 1 1 0 3 0 1 1 0 1 0 0 0 1 3 1 0 1 1 0 0 1 0 1 3 0 0 0 3 2 0 1 1 3 3 3 -1",
]
dna_strings = [s.split() for s in dna_strings_raw]
dna_alphabet = ["0", "1", "2", "3", "-1"]

pta_dna = build_pta(dna_strings, dna_alphabet)
print(f"\nInitial DNA-example PTA: {len(pta_dna.live_states_in_order())} states")
draw_automaton(pta_dna, "Initial PTA - DNA codon-group example",
                f"{OUT}/dna_step0_pta.png")

for alpha in [0.7, 0.5, 0.3]:
    pta_dna_run, log_dna = run_alergia(dna_strings, dna_alphabet, alpha=alpha, verbose=False)
    print(f"alpha={alpha}: {len(log_dna)} merges -> "
          f"{len(pta_dna_run.live_states_in_order())} final states")
    draw_automaton(pta_dna_run,
                    f"Final automaton, DNA example (alpha={alpha})",
                    f"{OUT}/dna_final_alpha{str(alpha).replace('.', '')}.png")

print(f"\nAll images saved under {OUT}/")
