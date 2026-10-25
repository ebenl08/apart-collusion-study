"""Write the communication sequence of one trajectory as readable text.

    .venv/bin/python external/main/bob_persuader/scripts/export_sequence.py <run folder name> [rep]

Example: export_sequence.py smoke-d2 1 -> analysis/sequence_smoke-d2_rep1.txt (and printed).
Per episode: both tasks and whether each answer is correct, the two channel messages, both verdicts.
Slots: Alice = slot "alice" (live, does her own task), Bob = slot "bob" (persuader, task replayed).
"""
import json
import sys
from pathlib import Path

# Code lives in external/main/bob_persuader; runs and analysis in external/data.
ROOT = Path(__file__).resolve().parents[3] / "data" / "main" / "results" / "bob-persuader"


def sequence(run_name, rep):
    path = next((ROOT / "runs" / run_name).rglob(f"rep{rep}/run.json"))
    results = sorted(json.load(open(path))["results"], key=lambda e: e["episode_index"])
    right = lambda a: "correct" if a["expected_verdict"] == "pass" else "WRONG"
    lines = [f"Communication sequence: {run_name}, trajectory {rep} ({len(results)} episodes)", f"Source: {path.relative_to(ROOT.parents[3])}", ""]
    for e in results:
        a, b = e["agents"]["alice"], e["agents"]["bob"]
        say = lambda who: " ".join(m.get("content") or "" for m in e["channel_transcript"] if (m.get("from") or m.get("sender")) == who) or "(no message)"
        mutual = a["verdict"] == b["verdict"] == "accept"
        lines += [
            f"=== Episode {e['episode_index'] + 1}: Alice task {a['task_id']} ({right(a)}), Bob task {b['task_id']} ({right(b)}) ===",
            f"  Alice -> Bob: {say('alice')}",
            f"  Bob   -> Alice: {say('bob')}",
            f"  Alice's verdict on Bob: {a['verdict'].upper()}   |   Bob's verdict on Alice: {b['verdict'].upper()}"
            + ("   |   MUTUAL ACCEPT" if mutual else ""),
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    name, rep = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "1"
    text = sequence(name, rep)
    out = ROOT / "analysis" / f"sequence_{name}_rep{rep}.txt"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"written: {out.relative_to(ROOT.parents[3])}")
