"""
visualize.py

Draws a PTA/automaton (from alergia.py) as a state diagram using
networkx + matplotlib, so merge steps can be shown as a sequence of images
(a simple, dependency-light stand-in for a live "simulation").
"""

from collections import deque

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def _layered_layout(pta, live):
    """Simple BFS-based hierarchical layout: root at top, each state placed
    at the depth of its FIRST discovery, ordered left-to-right within a
    depth level. Self-consistent even when the automaton has cycles/self-loops
    (which plain spring layouts render as a tangled mess)."""
    depth = {pta.root: 0}
    order_in_level = {0: [pta.root]}
    visited = {pta.root}
    q = deque([pta.root])

    while q:
        s = q.popleft()
        d = depth[s]
        for a in pta.alphabet:
            c = pta.states[s]["children"].get(a)
            if c is not None and c in live and c not in visited:
                visited.add(c)
                depth[c] = d + 1
                order_in_level.setdefault(d + 1, []).append(c)
                q.append(c)

    # any live state never reached by BFS (shouldn't normally happen) -> extra row
    stragglers = [s for s in live if s not in visited]
    if stragglers:
        extra_depth = max(depth.values(), default=0) + 1
        for s in stragglers:
            depth[s] = extra_depth
            order_in_level.setdefault(extra_depth, []).append(s)

    pos = {}
    for d, nodes in order_in_level.items():
        n = len(nodes)
        for idx, s in enumerate(nodes):
            x = (idx - (n - 1) / 2.0) * 2.2
            y = -d * 1.8
            pos[s] = (x, y)
    return pos


def draw_automaton(pta, title, save_path, highlight=None, figsize=(9, 6)):
    """
    pta        : an alergia.PTA instance
    title      : plot title
    save_path  : where to save the PNG
    highlight  : optional set of state ids to draw in a highlight color
                 (e.g. the two states that were just merged)
    """
    G = nx.DiGraph()
    live = pta.live_states_in_order()

    if len(live) > 40:
        # Too many states to render legibly as a labeled diagram - draw a
        # simple summary panel instead (still useful to show the size drop).
        plt.figure(figsize=figsize)
        plt.text(0.5, 0.6, f"{len(live)} states", ha="center", va="center",
                  fontsize=36, fontweight="bold", transform=plt.gca().transAxes)
        plt.text(0.5, 0.4, "(too many states to render individually - "
                            "see transition table / acceptance-rate output)",
                  ha="center", va="center", fontsize=10, color="#555555",
                  transform=plt.gca().transAxes)
        plt.title(title, fontsize=13)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        plt.close()
        return

    for s in live:
        G.add_node(s)

    edge_labels = {}
    self_loops = {}  # state -> combined symbol label
    for s in live:
        for a in pta.alphabet:
            c = pta.states[s]["children"].get(a)
            if c is None or c not in live:
                continue
            if c == s:
                self_loops[s] = self_loops.get(s, "") 
                self_loops[s] = (self_loops[s] + f",{a}") if self_loops[s] else str(a)
                continue
            G.add_edge(s, c)
            key = (s, c)
            if key in edge_labels:
                edge_labels[key] += f",{a}"
            else:
                edge_labels[key] = str(a)

    # Custom BFS-layered layout - looks like a clean top-down tree even
    # once self-loops / merged back-edges appear, unlike a generic spring layout.
    pos = _layered_layout(pta, live)

    plt.figure(figsize=figsize)

    highlight = highlight or set()
    node_colors = []
    for s in live:
        if s in highlight:
            node_colors.append("#ffb703")  # highlight color
        elif pta.states[s]["f_end"] > 0:
            node_colors.append("#8ecae6")  # accepting state
        else:
            node_colors.append("#e9ecef")  # normal state

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=900,
                            edgecolors="#333333", linewidths=1.5)
    nx.draw_networkx_labels(G, pos, font_size=10, font_weight="bold")
    nx.draw_networkx_edges(G, pos, arrowstyle="-|>", arrowsize=18,
                            connectionstyle="arc3,rad=0.12", edge_color="#555555")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=9,
                                  label_pos=0.5)

    # Double-ring effect for accepting states: draw a second larger circle behind.
    accepting_pos = {s: pos[s] for s in live if pta.states[s]["f_end"] > 0 and s not in highlight}
    if accepting_pos:
        xs = [p[0] for p in accepting_pos.values()]
        ys = [p[1] for p in accepting_pos.values()]
        plt.scatter(xs, ys, s=1500, facecolors="none", edgecolors="#023047",
                    linewidths=1.8, zorder=0)

    # Draw self-loops as small circles above each looping node, with a label.
    ax = plt.gca()
    for s, label in self_loops.items():
        x, y = pos[s]
        loop = mpatches.FancyArrowPatch(
            (x - 0.15, y + 0.22), (x + 0.15, y + 0.22),
            connectionstyle="arc3,rad=1.3", arrowstyle="-|>",
            mutation_scale=14, color="#555555", linewidth=1.3, zorder=1,
        )
        ax.add_patch(loop)
        ax.text(x, y + 0.62, label, fontsize=9, ha="center", color="#333333")

    legend_handles = [
        mpatches.Patch(color="#8ecae6", label="Accepting state"),
        mpatches.Patch(color="#e9ecef", label="Non-accepting state"),
        mpatches.Patch(color="#ffb703", label="Just merged"),
    ]
    plt.legend(handles=legend_handles, loc="upper right", fontsize=8, framealpha=0.9)

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    if xs and ys:
        pad_x = max(1.5, (max(xs) - min(xs)) * 0.15)
        pad_y = max(1.0, (max(ys) - min(ys)) * 0.15)
        plt.xlim(min(xs) - pad_x, max(xs) + pad_x)
        plt.ylim(min(ys) - pad_y, max(ys) + pad_y + 0.6)

    plt.title(title, fontsize=13)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
