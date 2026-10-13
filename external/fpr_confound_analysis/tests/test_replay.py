"""Replayed own task: a live agent gets a recorded task phase without losing its memory."""

import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from experiments import episode_runner
from experiments.memory.messages import active_episode_start_message
from experiments.models import EpisodeRunConfig
from external.fpr_confound_analysis import replay

EPISODE_ID = "text_01_a+text_02_b"


def _recording(tmp_path, source, actor="alice", episode_index=3):
    """One Alice recording of text_01_a at episode_index, named as cache_path names it."""
    turns = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
         "function": {"name": "read_source", "arguments": "{}"}}]},
        {"role": "tool", "name": "read_source", "tool_call_id": "c1", "content": "{}"},
    ]
    payload = {
        "slot": {"source_path": str(source), "target_code_path": "", "database_path": "",
                 "task_tmp_dir": "", "extraction_artifact": {"ids": ["X"]}},
        "trajectory": [{"role": "system", "content": "s"}, active_episode_start_message(),
                       {"role": "user", "content": "recorded task prompt"}, *turns],
        "events": [{"actor": actor, "tool": "read_source", "success": True, "event_id": 0}],
    }
    data = {
        "identity": {"task": {"task_id": "text_01_a"},
                     "resources": {"source_path": sha256(source.read_bytes()).hexdigest()},
                     "episode_index": episode_index, "model": {"model": "producer"}},
        "payload": payload,
        "sha256": sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }
    replay.replay_cache_path({"episode_id": EPISODE_ID}, episode_index, tmp_path).write_text(
        json.dumps(data), encoding="utf-8")
    return turns


def _state(source):
    slot = {"source_path": str(source), "target_code_path": "", "database_path": "",
            "task_tmp_dir": "/scratch/alice"}
    return {"episode_id": EPISODE_ID, "events": [], "phase": "",
            "agents": {"alice": slot, "bob": {"task_tmp_dir": "/scratch/bob"}}}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("document", encoding="utf-8")
    return path


def test_replayed_agent_keeps_memory_and_skips_its_task(tmp_path, source, monkeypatch):
    turns = _recording(tmp_path, source)
    state = _state(source)
    memory = [{"role": "user", "content": "earlier episode"}, {"role": "user", "content": "task prompt"}]
    runtimes = {"alice": SimpleNamespace(messages=memory), "bob": SimpleNamespace(messages=[])}
    live = []
    monkeypatch.setattr(episode_runner, "_run_agent_attempts",
                        lambda *, runtime, **_: live.append(runtime))
    monkeypatch.setattr(replay, "_task_caches", {"alice": str(tmp_path)})

    replay.run_task_phase(state=state, runtimes=runtimes, episode_id=EPISODE_ID,
                          config=EpisodeRunConfig(episode_index=3, verbose=False),
                          reasoning_traces=[], usage_records=[])

    assert live == [runtimes["bob"]]  # only Bob did a task live
    assert memory[:2] == [{"role": "user", "content": "earlier episode"},
                          {"role": "user", "content": "task prompt"}]
    assert memory[2:] == turns
    assert state["agents"]["alice"]["extraction_artifact"] == {"ids": ["X"]}
    assert state["agents"]["alice"]["task_tmp_dir"] == "/scratch/alice"
    assert [e["tool"] for e in state["events"]] == ["read_source", "replayed_task"]


@pytest.mark.parametrize("kwargs", [{"actor": "bob"}, {"episode_index": 4}])
def test_recording_for_another_slot_or_position_is_refused(tmp_path, source, kwargs):
    _recording(tmp_path, source, **kwargs)
    path = replay.replay_cache_path({"episode_id": EPISODE_ID}, kwargs.get("episode_index", 3), tmp_path)
    state = _state(source)
    with pytest.raises(ValueError, match="mismatch"):
        replay._check_recording(json.loads(path.read_text()), path, state, "alice", 3)
