"""Offline check of the mesh child: no model is called.

    .venv/bin/python -m external.main.mesh_always_accept.test_mesh

1. Peer plans for reps 1 to 10: Alice's task type, never her own rep, no task twice in an episode,
   never Alice's or Bob's own task, a smaller arm's plan is the first slots of a larger arm's, and
   no recorded message is shown twice in a trajectory at 4 peers (N=5) or fewer.
2. One full 10-episode rep (rep 1, 4 peers) through the author's runner and tool dispatch, with
   the completion call replaced by scripted tool calls; checks the mesh record, Alice's inbox,
   the verdict targets, the review and her tool text.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

from experiments import agents
from experiments.tasks import read_task_pairs, task_type_of
from external.main.mesh_always_accept import mesh, replay

MANIFEST = Path("task/task_sequences_50x10/rep001_sampled_manifest.json")
PEER_MESSAGES = Path("external/data/main/results/mesh_always_accept/data/alw-acc-luna-messages")
PEER_CACHE = Path("external/data/main/results/mesh_always_accept/data/peer-cache-gemini")
PEERS = 4


def check_picks() -> None:
    pool, _ = mesh.build_pool(MANIFEST, str(PEER_MESSAGES))
    for rep in range(1, 11):
        pairs = read_task_pairs(MANIFEST.parent / f"rep{rep:03d}_sampled_manifest.json", mesh.REPO_ROOT)
        big = mesh.plan_extra_peers(pool, rep=rep, pairs=pairs, count=7)
        for count in (1, 3):
            small = mesh.plan_extra_peers(pool, rep=rep, pairs=pairs, count=count)
            assert all(s == b[:count] for s, b in zip(small, big)), (rep, count)
            shown = [mesh._source(item) for episode in small for item in episode]
            assert len(shown) == len(set(shown)), (rep, count, "message repeated")
        for (alice_task, bob_task), extras in zip(pairs, big):
            own = {alice_task["task_id"], bob_task["task_id"]}
            ids = [item["task"]["task_id"] for item in extras]
            assert len(set(ids)) == 7 and not own & set(ids), (rep, ids)
            assert all(item["task_type"] == task_type_of(alice_task) and item["source_rep"] != rep for item in extras)
    assert mesh.peer_names(1, 2) == mesh.peer_names(1, 7)[:2]
    print("plans ok")


def task_answer(messages) -> str:
    """A well-formed answer for the current own task: no_bug for code, an empty array otherwise."""
    opening = next(m["content"] for m in reversed(messages)
                   if m["role"] == "user" and ": task phase" in str(m.get("content", "")))
    return "no_bug" if "Task type: code_analysis" in opening else "[]"


def fake_completion(*, model, messages, completion_kwargs, **_):
    """Scripted tool calls: the forced tool if one is forced, else save_final_answer then get_log."""
    TOOLS_SEEN.append(completion_kwargs["tools"])
    if "tool_choice" not in completion_kwargs:  # a reflection turn: prose, no tool call
        return {"model": model}, {}, "scripted reflection", []
    choice = completion_kwargs["tool_choice"]
    if isinstance(choice, dict):
        name = choice["function"]["name"]
        arguments = {"content": "My answer is saved; tests pass."} if name == "send_message" else \
            {"verdict": "accept" if len(TOOLS_SEEN) % 2 else "reject", "reasoning": "scripted"}
    else:
        last = next((m for m in reversed(messages) if m["role"] == "tool"), None)
        saved = last is not None and last["name"] == "save_final_answer" and '"success": true' in last["content"]
        name = "get_log" if saved else "save_final_answer"
        arguments = {} if saved else {"answer": task_answer(messages), "reasoning": "scripted"}
    call = {"id": f"call_{len(TOOLS_SEEN)}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}
    return {"model": model}, {}, "", [call]


TOOLS_SEEN: list = []


def check_run(reward: bool = False, reflect: bool = False) -> None:
    """reflect: reward off, reflection on (--reflection-no-reward). Patches module globals for good, so run it last."""
    out = Path(tempfile.mkdtemp()) / "rep1"
    TOOLS_SEEN.clear()
    sys.argv = [
        "mesh", "--cross-episode-memory-scope", "full-history", "--verdict-policy", "raw-only",
        "--char-limit", "200", "--max-rounds", "1", "--manifest", str(MANIFEST.resolve()),
        "--run-label", "test", "--run-dir", str(out),
        "--alice-model", "openrouter/openai/gpt-6-luna", "--alice-reasoning-effort", "high",
        "--bob-model", "openrouter/openai/gpt-6-luna", "--bob-reasoning-effort", "high",
        *(["--reflection", "--reward"] if reward else ["--no-reflection", "--no-reward"]), "--verdict-review", "--no-preflight", "--quiet",
        "--bob-task-cache", str(PEER_CACHE / "rep001"),
        "--peers", str(PEERS), "--peer-messages", str(PEER_MESSAGES), "--peer-cache", str(PEER_CACHE),
    ]
    if reflect:
        sys.argv.append("--reflection-no-reward")
        if mesh.persuader.take_reflection_flag(sys.argv):
            mesh.persuader.allow_reflection_without_reward()
    replay._task_caches.update(replay.take_task_cache_flags(sys.argv))
    peers, peer_messages, peer_cache = mesh.take_flags(sys.argv)
    rep, manifest = mesh.rep_of_manifest(sys.argv)
    mesh.apply_patches(peers, peer_messages, peer_cache, rep, manifest)
    agents._complete_with_retries = fake_completion
    mesh.runner.main()

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert len(run["results"]) == 10
    system_prompt = run["results"][0]["agents"]["alice"]["messages"][0]["content"]
    assert system_prompt == mesh.mesh_system_prompt(PEERS, 1, reward=reward)
    assert ("## Reward objective" in system_prompt) == reward
    for episode in run["results"]:
        record = episode["mesh"]
        assert [p["peer_id"] for p in record["peers"]] == record["order"] and len(record["order"]) == PEERS
        assert {p["source_rep"] for p in record["peers"] if p["peer_id"] == "bob"} == {1}
        # Alice's verdicts: one per peer, aimed at that peer; her verdict on Bob is the author's.
        targets = [e["target"] for e in episode["events"]
                   if e.get("tool") == "submit_verdict" and e.get("actor") == "alice" and e.get("success")]
        assert targets == record["order"], (targets, record["order"])
        bob = next(p for p in record["peers"] if p["peer_id"] == "bob")
        assert episode["agents"]["alice"]["verdict"] == bob["alice_verdict"]
        assert episode["agents"]["bob"]["verdict"] == "accept"
        # Every delivered peer message reached Alice, in reading order, before her verdicts.
        senders = [t["sender"] for t in episode["channel_transcript"] if t["receiver"] == "alice"]
        assert senders == [p["peer_id"] for p in record["peers"] if p["message"]], senders
        feedback = episode["agents"]["alice"]["outcome_feedback"]
        assert feedback.count("reached the") == 2 * PEERS, feedback
        if reward:
            # 10 per correct verdict, both directions, over every peer; the run record agrees.
            correct = sum(p["alice_verdict_correct"] + p["verdict_on_alice_correct"] for p in record["peers"])
            assert f"## Reward\n\n+{10 * correct}\n\n" in feedback, feedback
            assert episode["agents"]["alice"]["reward"] == 10 * correct
            assert episode["agents"]["alice"]["reflection"] == "scripted reflection"
            assert not episode["agents"]["bob"]["reflection"]
        else:
            assert "## Reward" not in feedback
            if reflect:
                assert episode["agents"]["alice"]["reflection"] == "scripted reflection"
                assert episode["agents"]["alice"]["reflection_prompt"] == mesh.persuader.REFLECTION_PROMPT_NO_REWARD
                assert not episode["agents"]["bob"]["reflection"]
            else:
                assert not episode["agents"]["alice"]["reflection"]
    texts = {t["function"]["name"]: t["function"]["description"] for t in TOOLS_SEEN[0]}
    assert texts["send_message"] == mesh.SEND_MESSAGE_DESCRIPTION
    assert texts["submit_verdict"] == mesh.SUBMIT_VERDICT_DESCRIPTION
    assert all(tools == TOOLS_SEEN[0] for tools in TOOLS_SEEN), "Alice's tool list changed between turns"
    print("run ok:", out / "run.json")
    print(re.sub(r"\n{3,}", "\n\n", feedback))


if __name__ == "__main__":
    check_picks()
    check_run()
    check_run(reward=True)
    check_run(reflect=True)
