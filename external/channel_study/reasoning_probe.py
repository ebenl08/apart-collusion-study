"""Probe: how often does an agent reason before its first communication-window message?

Replays a saved history from a cross-episode run, cut just before the agent's round-1
communication-window turn, and samples that one turn again with the run's own model
settings and the author's run_agent_turn. Nothing is written back to the run.

A variant changes the replayed history; only the control (v0: history as saved) exists
so far. Each call records the provider's reasoning_tokens from the author's usage record.

Run from the repo root:

    .venv/bin/python -m external.channel_study.reasoning_probe \
        --run <run.json> --config external/channel_study/configs/cross-episode-trial.yaml
"""

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import yaml

from experiments.agents import run_agent_turn
from experiments.protocol.state import AGENT_IDS, create_channel_state
from experiments.tool_schemas import forced_tool_choice

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "external/data/channel_study/results/tables/reasoning_probe.csv"
ROUND_1 = "Use the send_message tool to send your message (round 1 of"

VARIANTS = {"v0": lambda messages: messages}  # control: the history as saved


def history_before_window_round_1(episode: dict, agent: str) -> list[dict]:
    """The agent's saved history up to and including its window round-1 instruction."""
    messages = episode["agents"][agent]["messages"]
    opening = next(i for i, m in enumerate(messages)
                   if m["role"] == "user" and str(m.get("content", "")).startswith("## Between episodes"))
    cut = next(i for i in range(opening, len(messages))
               if str(messages[i].get("content", "")).startswith(ROUND_1))
    return deepcopy(messages[: cut + 1])


def sample(*, agent, messages, task_type, settings):
    usage = []
    state = create_channel_state(episode_id="probe")
    state.update(phase="communication", task_type=task_type, repo_root=str(ROOT))
    turn = run_agent_turn(
        actor=agent,
        model=settings["model"],
        reasoning_effort=settings.get("reasoning_effort", "default"),
        messages=deepcopy(messages),
        state=state,
        tool_choice=forced_tool_choice(task_type, "communication"),
        usage_recorder=usage.append,
    )
    sent = [c["arguments"] for c in turn["tool_calls"] if c.get("tool_name") == "send_message"]
    return {
        "reasoning_tokens": usage[-1].get("reasoning_tokens") if usage else None,
        "cost_usd": usage[-1].get("cost_usd") if usage else None,
        "message": json.dumps(sent, ensure_ascii=False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="cross-episode run.json")
    parser.add_argument("--config", required=True, help="the run's YAML config (model settings)")
    parser.add_argument("--variants", nargs="+", default=["v0"], choices=sorted(VARIANTS))
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--episode", type=int, default=0, help="episode index whose window to probe")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    episode = json.loads(Path(args.run).read_text(encoding="utf-8"))["results"][args.episode]
    jobs = [
        dict(variant=v, agent=a, sample_index=s,
             messages=VARIANTS[v](history_before_window_round_1(episode, a)))
        for v in args.variants for a in AGENT_IDS for s in range(args.samples)
    ]

    def work(job):
        return {"variant": job["variant"], "agent": job["agent"], "sample": job["sample_index"],
                **sample(agent=job["agent"], messages=job["messages"],
                         task_type=episode["task_type"], settings=config[job["agent"]])}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(work, jobs))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")

    print(f"\n{'variant':>8} {'agent':>6} {'n':>3} {'reasoning>0':>12} {'mean_tokens':>12}")
    for v in args.variants:
        for a in AGENT_IDS:
            tokens = [r["reasoning_tokens"] or 0 for r in rows if r["variant"] == v and r["agent"] == a]
            share = sum(t > 0 for t in tokens)
            print(f"{v:>8} {a:>6} {len(tokens):>3} {share:>6}/{len(tokens):<5} {sum(tokens) / len(tokens):>12.1f}")
    print(f"\ncost: ${sum(r['cost_usd'] or 0 for r in rows):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
