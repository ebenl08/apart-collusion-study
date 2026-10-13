"""Child entry point: the author's runner, with chosen agents' own tasks replayed.

An agent given a task cache does not do its task. It receives a recorded one instead
(made by ``experiments.record_peer``): its slot (answer, raw log), its task events, and
its task turns, appended after the episode's own task prompt so cross-episode memory is
kept. Communication, verdict, reward, feedback and reflection stay live and unchanged.

Nothing in the author's files is edited. One patch: ``episode_runner._run_task_phase``,
which the author's ``run_one_episode`` looks up at call time.
"""

import argparse
import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from experiments import episode_runner, runner
from experiments.memory.messages import INTERNAL_ACTIVE_EPISODE_ROLE
from experiments.protocol.state import AGENT_IDS, agent_state, set_phase

CHILD_MODULE = "external.fpr_confound_analysis.replay"
TASK_CACHE_KEYS = tuple(f"{agent_id}_task_cache" for agent_id in AGENT_IDS)

# Set once per run from this child's flags; read by the patched task phase.
_task_caches: dict[str, str] = {}

# Slot keys holding the task's resources, named as in experiments.controlled.cache_identity.
_RESOURCE_SLOT_KEYS = {
    "code_path": "target_code_path",
    "source_path": "source_path",
    "database_path": "database_path",
}


def replay_cache_path(state, episode_index, cache_dir):
    """The recording for this episode; same naming as experiments.controlled.cache_path."""
    key = sha256(str(state["episode_id"]).encode()).hexdigest()[:20]
    return Path(cache_dir) / f"{episode_index:04d}-{key}.json"


def recorded_task_turns(trajectory):
    """Everything the recorded agent did after its episode's task prompt."""
    starts = [i for i, m in enumerate(trajectory) if m.get("role") == INTERNAL_ACTIVE_EPISODE_ROLE]
    if not starts:
        raise ValueError("Recorded trajectory has no active-episode marker")
    return deepcopy(trajectory[starts[-1] + 2 :])


def _check_recording(data, path, state, agent_id, episode_index):
    """Refuse a recording of another task, other resources, another slot or a tampered payload."""
    identity = data["identity"]
    task_id = str(state["episode_id"]).split("+")[AGENT_IDS.index(agent_id)]
    slot = agent_state(state, agent_id)
    resources = {
        name: sha256(Path(slot[key]).read_bytes()).hexdigest()
        for name, key in _RESOURCE_SLOT_KEYS.items()
        if slot.get(key)
    }
    digest = sha256(
        json.dumps(data["payload"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    problems = [
        what
        for what, ok in (
            ("task", identity["task"]["task_id"] == task_id),
            ("resources", identity["resources"] == resources),
            ("episode index", identity["episode_index"] == episode_index),
            ("slot", all(e.get("actor") == agent_id for e in data["payload"]["events"])),
            ("checksum", digest == data["sha256"]),
        )
        if not ok
    ]
    if problems:
        raise ValueError(f"Replay recording mismatch ({', '.join(problems)}): {path}")


def load_replayed_task(state, runtime, agent_id, episode_index, cache_dir):
    """Put a recorded task phase into the live agent's slot, events and messages."""
    path = replay_cache_path(state, episode_index, cache_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    _check_recording(data, path, state, agent_id, episode_index)
    payload = data["payload"]
    # Evaluation cleans up this invocation's scratch directory, never the recording's.
    scratch = agent_state(state, agent_id)["task_tmp_dir"]
    state["agents"][agent_id] = deepcopy(payload["slot"])
    state["agents"][agent_id]["task_tmp_dir"] = scratch
    for event in payload["events"]:
        state["events"].append({**deepcopy(event), "event_id": len(state["events"])})
    # Provenance; not a send_message event, so channel_transcript ignores it.
    state["events"].append(
        {
            "event_id": len(state["events"]),
            "actor": agent_id,
            "tool": "replayed_task",
            "success": True,
            "phase": "task",
            "round": 0,
            "cache": str(path),
            "sha256": data["sha256"],
            "recorded_model": data["identity"]["model"]["model"],
        }
    )
    runtime.messages.extend(recorded_task_turns(payload["trajectory"]))


def run_task_phase(*, state, runtimes, episode_id, config, reasoning_traces, usage_records):
    """The author's task phase, with each replayed agent loaded instead of run."""
    set_phase(state, "task")
    for agent_id in AGENT_IDS:
        if agent_id in _task_caches:
            episode_runner.log_progress(
                f"  Task phase: {agent_id} replayed (episode={episode_id})", config.verbose
            )
            load_replayed_task(
                state, runtimes[agent_id], agent_id, config.episode_index, _task_caches[agent_id]
            )
            continue
        if agent_id == "bob" and config.controlled_bob_verdict:
            continue
        episode_runner.log_progress(
            f"  Task phase: {agent_id} (episode={episode_id})", config.verbose
        )
        episode_runner._run_agent_attempts(
            runtime=runtimes[agent_id],
            state=state,
            phase="task",
            tool_choice="required",
            episode_id=episode_id,
            round_index=None,
            reasoning_traces=reasoning_traces,
            usage_records=usage_records,
            config=config,
        )


def take_task_cache_flags(argv):
    """Remove this child's flags from argv; return {agent_id: cache_dir} for those given."""
    pre = argparse.ArgumentParser(add_help=False)
    for key in TASK_CACHE_KEYS:
        pre.add_argument("--" + key.replace("_", "-"), default="")
    known, rest = pre.parse_known_args(argv[1:])
    argv[1:] = rest
    caches = {
        agent_id: getattr(known, f"{agent_id}_task_cache")
        for agent_id in AGENT_IDS
        if getattr(known, f"{agent_id}_task_cache")
    }
    if "bob" in caches and "--bob-model" in rest and rest[rest.index("--bob-model") + 1] == "controlled":
        raise ValueError("bob_task_cache needs a live Bob; a controlled Bob replays its own cache.")
    return caches


if __name__ == "__main__":
    _task_caches.update(take_task_cache_flags(sys.argv))
    episode_runner._run_task_phase = run_task_phase
    runner.main()
