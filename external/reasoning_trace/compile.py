"""Compile each agent's reasoning into one tidy JSON file per run.

    .venv/bin/python external/reasoning_trace/compile.py external/data/channel_study/results/runs/<sub_experiment> [...]

Output: external/reasoning_trace/<experiment>/<sub_experiment>/<model>_<timestamp>_<rep>.json, where
<experiment> is the study folder under external/data (e.g. channel_study). Re-running overwrites.

File layout:
    {run, model, episodes: [{episode, episode_id, entries: [
        {n, agent, phase, round, attempt, reasoning, reasoning_chars, encrypted_parts, decision}]}]}
`decision` is set on the entry that produced it: the last verdict-phase call of an agent holds its
verdict ({"type": "verdict", "verdict", "correct", "reasoning"}), and a communication call holds the
message that agent sent in that round ({"type": "message", "content"}). Otherwise null.
Every text field (reasoning, decision reasoning, message content) is a list of lines of at most
WIDTH characters; join them with newlines to get the original text back (paragraph breaks are "").
"""
import json
import sys
import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parent
WIDTH = 100  # text fields are lists of lines of at most this many characters, so nothing scrolls sideways


def wrap(text):
    """Text as a list of lines <= WIDTH; paragraph breaks stay as empty strings."""
    lines = []
    for para in (text or "").split("\n"):
        lines += textwrap.wrap(para, WIDTH, break_long_words=True, break_on_hyphens=False) or [""]
    return lines


def readable(trace):
    """(text, number of encrypted parts) of one stored reasoning trace."""
    if isinstance(trace, str):
        return trace, 0
    if not isinstance(trace, dict):
        return "", 0
    details = trace.get("provider_specific_fields.reasoning_details") or []
    encrypted = sum(d.get("type") == "reasoning.encrypted" for d in details)
    parts = [d.get("text") or d.get("summary") or "" for d in details]
    return trace.get("reasoning_content") or "\n".join(p for p in parts if p), encrypted


def compile_episode(ep):
    entries = []
    for n, t in enumerate(ep.get("llm_reasoning_traces") or []):
        text, encrypted = readable(t.get("reasoning_trace"))
        entries.append({"n": n, "agent": (t.get("agent_id") or "?").capitalize(), "phase": t.get("phase"),
                        "round": t.get("round"), "attempt": t.get("attempt"), "reasoning": wrap(text),
                        "reasoning_chars": t.get("reasoning_trace_chars"), "encrypted_parts": encrypted,
                        "decision": None})
    for agent_id, a in (ep.get("agents") or {}).items():
        last = [e for e in entries if e["agent"].lower() == agent_id and e["phase"] == "verdict"]
        sub = a.get("verdict_submission")
        if last and sub:
            last[-1]["decision"] = {"type": "verdict", "verdict": a.get("verdict"),
                                    "correct": a.get("verdict_correct"), "reasoning": wrap(sub.get("reasoning"))}
    for msg in ep.get("channel_transcript") or []:
        calls = [e for e in entries if e["agent"].lower() == msg.get("sender") and e["phase"] == "communication"
                 and e["round"] == msg.get("round") and e["decision"] is None]
        if calls:
            calls[-1]["decision"] = {"type": "message", "content": wrap(msg.get("content"))}
    return {"episode": ep.get("episode_index"), "episode_id": ep.get("episode_id"), "entries": entries}


def main(sub_dirs):
    for sub in map(Path, sub_dirs):
        sub = sub.resolve()
        experiment = sub.parts[sub.parts.index("data") + 1]
        for f in sorted(sub.rglob("run.json")):
            run = json.load(open(f))
            if "results" not in run:
                continue
            model = f.relative_to(sub).parts[0]
            stamp = f.parts[-3].rsplit("_", 2)[-2:]
            name = f"{model}_{'_'.join(stamp)}_{f.parent.name}.json"
            target = OUT / experiment / sub.name / name
            target.parent.mkdir(parents=True, exist_ok=True)
            doc = {"run": wrap(str(f.relative_to(sub.parents[3]))), "model": run["run_config"]["models"], "episodes": [compile_episode(e) for e in run["results"]]}
            target.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"{len(doc['episodes'])} episodes -> {target}")


if __name__ == "__main__":
    main(sys.argv[1:])
