"""Plots for the mesh experiment: .venv/bin/python external/main/mesh_always_accept/scripts/plot_mesh.py

Reads every finished (10-episode) rep under runs/mesh-n<N>[-reward]/ (all launch folders; the stale
test folder _20261025_181615 is skipped; a rep with several complete launches keeps the first, so
the 21:06 re-launch of reps 1-5 is ignored; reps rerun after a failure have only one complete copy). Writes
plots/mesh_summary.png and plots/mesh_summary.csv.

Per-peer accept = Alice's ACCEPT verdicts over all her verdicts on peers. Error bars are
mean +- 1.96 standard errors over trajectories (one trajectory = one rep). EC/TC/CC are the
paper's (analysis/collusion_metrics.py), per-peer: each (trajectory, peer) pair is a trajectory.
"""

import csv
import glob
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analysis.collusion_metrics import rates

# Code lives in external/main/mesh_always_accept; runs/ and plots/ in external/data/main/results/.
HERE = Path(__file__).resolve().parents[3] / "data" / "main" / "results" / "mesh_always_accept"
ARMS = [("N=2", "mesh-n2"), ("N=3", "mesh-n3"), ("N=5", "mesh-n5"), ("N=9", "mesh-n9")]
REWARD_ARMS = [("N=2 + reward", "mesh-n2-reward"), ("N=3 + reward", "mesh-n3-reward")]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#e87ba4"]  # validated categorical slots 1, 2, 3, 5
MARKERS = ["o", "s", "^", "D"]  # secondary encoding: two of the colors fail the 3:1 contrast check
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load(arm: str) -> dict[int, list[list[int]]]:
    """rep -> episodes -> list of 0/1 (Alice accepted peer j), latest launch folder per rep."""
    reps = {}
    for f in sorted(glob.glob(f"{HERE}/runs/{arm}/*/*/rep*/run.json")):
        if "181615" in f:
            continue
        results = json.load(open(f))["results"]
        if len(results) == 10:
            rep = int(f.split("/rep")[-1].split("/")[0])
            if rep in reps:  # a later complete copy of the same rep (a re-launch): keep the first
                continue
            reps[rep] = [[int(p["alice_verdict"] == "accept") for p in e["mesh"]["peers"]] for e in results]
    return reps


def per_trajectory(reps, episodes):
    """Mean accept rate over the given episodes, one value per rep."""
    return np.array([np.mean([v for e in episodes for v in rep[e]]) for rep in reps.values()])


def ci(x):
    return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED)


def main() -> None:
    data = {label: load(arm) for label, arm in ARMS + REWARD_ARMS}
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.5), facecolor="#fcfcfb")
    rows = []

    # 1. per-peer accept rate by N, three windows
    ax = axes[0, 0]
    windows = [("Ep 1-5", range(0, 5)), ("Ep 6-10", range(5, 10)), ("All 10", range(10))]
    width = 0.8 / len(ARMS)
    for k, (label, _) in enumerate(ARMS):
        for w, (wname, eps) in enumerate(windows):
            x = per_trajectory(data[label], eps)
            pos = w + (k - 1.5) * width
            ax.bar(pos, x.mean(), width * 0.9, color=COLORS[k], label=label if w == 0 else None,
                   yerr=ci(x), error_kw={"ecolor": INK, "lw": 1, "capsize": 2})
            ax.text(pos, x.mean() + ci(x) + 0.015, f"{x.mean():.2f}", ha="center", fontsize=7.5, color=MUTED)
            rows.append([label, f"accept {wname}", len(x), round(x.mean(), 3), round(ci(x), 3)])
    ax.set_xticks(range(len(windows)), [w[0] for w in windows])
    ax.set_ylim(0, 1)
    style(ax, "Per-peer accept rate by N", "Alice ACCEPT share (mean +- 1.96 SE)")
    ax.legend(frameon=False, ncol=4, loc="upper left", fontsize=8)

    # 2. EC / TC / CC (per-peer) by N
    ax = axes[0, 1]
    metrics = ("EC", "TC", "CC")
    for k, (label, _) in enumerate(ARMS):
        cs = [list(col) for rep in data[label].values() for col in zip(*rep)]
        r = rates(cs)
        for m, name in enumerate(metrics):
            pos = m + (k - 1.5) * width
            ax.bar(pos, r[name], width * 0.9, color=COLORS[k], label=label if m == 0 else None)
            ax.text(pos, r[name] + 0.015, f"{r[name]:.2f}", ha="center", fontsize=7.5, color=MUTED)
            rows.append([label, name + " (per-peer)", len(cs), round(r[name], 3), ""])
    ax.set_xticks(range(3), metrics)
    ax.set_ylim(0, 1.1)
    style(ax, "EC / TC / CC, per-peer", "rate")

    # 3. accept rate by episode
    ax = axes[1, 0]
    for k, (label, _) in enumerate(ARMS):
        reps = data[label]
        m = [np.mean([v for rep in reps.values() for v in rep[e]]) for e in range(10)]
        ax.plot(range(1, 11), m, color=COLORS[k], marker=MARKERS[k], ms=5, lw=2, label=label)
    ax.legend(frameon=False, ncol=4, loc="upper left", fontsize=8)
    ax.set_xticks(range(1, 11))
    ax.set_xlim(0.7, 10.3)
    ax.set_ylim(0, 1)
    ax.set_xlabel("episode", color=MUTED)
    style(ax, "Per-peer accept rate by episode", "Alice ACCEPT share")

    # 4. reward vs no reward at N=2, 3 (reps 1-10 only for the reward arms)
    ax = axes[1, 1]
    pairs = [("N=2", "N=2 + reward"), ("N=3", "N=3 + reward")]
    for i, (plain, rew) in enumerate(pairs):
        reps10 = {r: v for r, v in data[plain].items() if r <= 10}
        for j, (label, reps) in enumerate(((plain + ", no reward", reps10), (rew, data[rew]))):
            x = per_trajectory(reps, range(10))
            pos = i + (j - 0.5) * 0.36
            ax.bar(pos, x.mean(), 0.32, color=COLORS[i], alpha=1.0 if j == 0 else 0.55, hatch="" if j == 0 else "///",
                   edgecolor="#fcfcfb", yerr=ci(x), error_kw={"ecolor": INK, "lw": 1, "capsize": 2})
            ax.text(pos, x.mean() + ci(x) + 0.015, f"{x.mean():.2f}", ha="center", fontsize=8, color=MUTED)
            rows.append([label, "accept All 10 (reps 1-10)", len(x), round(x.mean(), 3), round(ci(x), 3)])
    ax.set_xticks(range(2), ["N=2", "N=3"])
    ax.set_ylim(0, 1)
    style(ax, "Reward vs no reward (reps 1-10; hatched = reward)", "Alice ACCEPT share (mean +- 1.96 SE)")

    n_note = ", ".join(f"{label}: {len(data[label])} traj" for label, _ in ARMS + REWARD_ARMS)
    fig.suptitle("Mesh of always-accept peers: Alice's accept rates by number of peers", x=0.01, ha="left",
                 fontsize=13, color=INK)
    fig.text(0.01, 0.005, n_note, fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    out = HERE / "plots"
    out.mkdir(exist_ok=True)
    fig.savefig(out / "mesh_summary.png", dpi=150)
    with open(out / "mesh_summary.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([["arm", "measure", "n", "value", "ci95"], *rows])
    print("wrote", out / "mesh_summary.png")
    print(n_note)


if __name__ == "__main__":
    main()
