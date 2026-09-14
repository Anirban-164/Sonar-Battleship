"""
alergia.py

A working implementation of the Alergia state-merging algorithm, following
Shah (2009) "DNA Sequence Representation by Use of Statistical Finite Automata"
(itself based on Carrasco & Oncina 1994).

Pipeline:
    1. Build a Prefix Tree Acceptor (PTA) from a set of training strings.
    2. For each pair of states (in creation order), test statistical
       "compatibility" using a Hoeffding-bound-based test controlled by alpha.
    3. Merge compatible states, folding their subtrees together.
    4. Repeat until no more merges are found -> final Stochastic Finite Automaton (SFA).

This is intentionally written to be readable and easy to customize/extend,
not to be maximally optimized.
"""

import math
from copy import deepcopy


class PTA:
    """Prefix Tree Acceptor / working automaton.

    States are stored in a dict keyed by integer id. Each state has:
        n        : number of training strings passing through this state
        f_end    : number of training strings that terminate at this state
        f        : dict symbol -> number of strings taking that symbol next
        children : dict symbol -> child state id
        parent   : parent state id (None for root)
        parent_symbol : symbol used on the edge from parent to this state
        alive    : False once this state has been merged away
    """

    def __init__(self, alphabet):
        self.alphabet = list(alphabet)
        self.states = {}
        self._next_id = 0
        self.root = self._new_state()
        # Keeps the order states were first created in (needed for the
        # Alergia main loop, which processes states in this order).
        self.creation_order = [self.root]

    def _new_state(self):
        sid = self._next_id
        self._next_id += 1
        self.states[sid] = {
            "n": 0,
            "f_end": 0,
            "f": {a: 0 for a in self.alphabet},
            "children": {},
            "parent": None,
            "parent_symbol": None,
            "alive": True,
        }
        return sid

    def add_string(self, s):
        """Insert one training string (a sequence of symbols) into the trie."""
        cur = self.root
        self.states[cur]["n"] += 1
        for sym in s:
            self.states[cur]["f"][sym] += 1
            if sym not in self.states[cur]["children"]:
                child = self._new_state()
                self.creation_order.append(child)
                self.states[cur]["children"][sym] = child
                self.states[child]["parent"] = cur
                self.states[child]["parent_symbol"] = sym
            cur = self.states[cur]["children"][sym]
            self.states[cur]["n"] += 1
        self.states[cur]["f_end"] += 1

    def live_states_in_order(self):
        """States in creation order, skipping ones already merged away."""
        return [s for s in self.creation_order if self.states[s]["alive"]]

    # ---- inspection helpers ----

    def transition_table(self):
        """Return rows: (state, symbol, next_state) for every live transition."""
        rows = []
        for s in self.live_states_in_order():
            for a in self.alphabet:
                c = self.states[s]["children"].get(a)
                if c is not None:
                    rows.append((s, a, c))
        return rows

    def accepts(self, s):
        """Walk the automaton on string s. Returns True if s ends on an
        accepting state (a state some training string terminated on)."""
        cur = self.root
        for sym in s:
            nxt = self.states[cur]["children"].get(sym)
            if nxt is None:
                return False
            cur = nxt
        return self.states[cur]["f_end"] > 0

    def acceptance_rate(self, test_strings):
        """Fraction of test_strings accepted by this automaton."""
        if not test_strings:
            return 0.0
        accepted = sum(1 for s in test_strings if self.accepts(s))
        return accepted / len(test_strings)


def differ(n1, f1, n2, f2, alpha):
    """Hoeffding-bound based test: True if the two frequency ratios are
    "different enough" (i.e. NOT compatible), given confidence parameter alpha.

    Implements the same test as the paper's Java `Differ()` method:
        (f1/n1 - f2/n2)^2  >  0.5 * log(1/alpha) * (1/sqrt(n1) + 1/sqrt(n2))^2
    """
    if n1 == 0 or n2 == 0:
        return False
    lhs = (f1 / n1 - f2 / n2) ** 2
    rhs = 0.5 * math.log(1.0 / alpha) * (1 / math.sqrt(n1) + 1 / math.sqrt(n2)) ** 2
    return lhs > rhs


def compatible(pta, i, j, alpha, _checked=None):
    """Recursively test whether states i and j (and their subtrees) are
    statistically compatible and can be merged."""
    if _checked is None:
        _checked = set()
    key = (min(i, j), max(i, j))
    if key in _checked:
        # Already confirmed compatible earlier in this recursion (avoids
        # infinite loops if merges created cycles back to shared descendants).
        return True
    _checked.add(key)

    si, sj = pta.states[i], pta.states[j]

    if differ(si["n"], si["f_end"], sj["n"], sj["f_end"], alpha):
        return False

    for a in pta.alphabet:
        if differ(si["n"], si["f"][a], sj["n"], sj["f"][a], alpha):
            return False

    for a in pta.alphabet:
        ci = si["children"].get(a)
        cj = sj["children"].get(a)
        if ci is not None and cj is not None:
            if not compatible(pta, ci, cj, alpha, _checked):
                return False
    return True


def _fold(pta, i, j, _in_progress=None):
    """Merge state j INTO state i: combine statistics, then recursively fold
    overlapping children, and re-parent any child that only j had.

    Once a few merges have happened, the automaton can contain cycles
    (e.g. a self-loop, as in the paper's own Fig. 11 example). _in_progress
    guards against infinite recursion when folding walks back into a cycle.
    """
    if _in_progress is None:
        _in_progress = set()

    if i == j:
        return  # already the same state - nothing to do

    key = (i, j)
    if key in _in_progress:
        return  # this exact fold is already being processed higher up the stack
    _in_progress.add(key)

    si, sj = pta.states[i], pta.states[j]

    si["n"] += sj["n"]
    si["f_end"] += sj["f_end"]
    for a in pta.alphabet:
        si["f"][a] += sj["f"][a]

    # Snapshot j's children before we start mutating things.
    j_children = dict(sj["children"])

    for a in pta.alphabet:
        cj = j_children.get(a)
        if cj is None:
            continue
        ci = si["children"].get(a)
        if ci is None:
            # No conflict: just re-parent j's child onto i.
            si["children"][a] = cj
            pta.states[cj]["parent"] = i
            pta.states[cj]["parent_symbol"] = a
        elif ci != cj:
            # Both have a (different) child on this symbol -> fold together too.
            _fold(pta, ci, cj, _in_progress)
        # if ci == cj, they already point to the same state - nothing to do

    sj["alive"] = False
    sj["children"] = {}


def merge(pta, i, j):
    """Merge state j into state i, redirecting j's parent edge to point at i."""
    p = pta.states[j]["parent"]
    a = pta.states[j]["parent_symbol"]
    if p is not None:
        pta.states[p]["children"][a] = i
    _fold(pta, i, j)


def build_pta(strings, alphabet):
    pta = PTA(alphabet)
    for s in strings:
        pta.add_string(s)
    return pta


def run_alergia(strings, alphabet, alpha, verbose=True):
    """Run the full Alergia pipeline. Returns (pta, merge_log) where merge_log
    is a list of (i, j, snapshot_after_merge) describing each merge performed,
    in the order the paper's pseudocode would find them."""
    pta = build_pta(strings, alphabet)
    merge_log = []

    if verbose:
        print(f"Initial PTA: {len(pta.live_states_in_order())} states")

    changed = True
    while changed:
        changed = False
        states = pta.live_states_in_order()
        # j ranges over successors (skip root as a merge target j).
        # For each j, i ranges ONLY over states created strictly before j
        # (this matches the paper's pseudocode: "for i = firstnode(A) to j").
        for idx_j in range(1, len(states)):
            j = states[idx_j]
            for idx_i in range(idx_j):
                i = states[idx_i]
                if not pta.states[i]["alive"]:
                    continue
                if compatible(pta, i, j, alpha):
                    if verbose:
                        print(f"  Merging state {j} into state {i}  (alpha={alpha})")
                    merge(pta, i, j)
                    merge_log.append((i, j, deepcopy(pta.states)))
                    changed = True
                    break
            if changed:
                break  # restart scan since state ids/order changed

    if verbose:
        print(f"Final automaton: {len(pta.live_states_in_order())} states "
              f"(merged from {len(strings)} training strings)")

    return pta, merge_log
