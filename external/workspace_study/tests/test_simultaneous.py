"""Simultaneous-step task phase: both agents act in every step, neither waits.

Runs the study's task phase with a fake agent turn in place of the LLM.
"""

import threading

import pytest

from experiments import agents, episode_runner
from experiments.models import AgentConfig, AgentRuntime, EpisodeRunConfig
from experiments.prompts import system
from experiments.protocol.state import AGENT_IDS, create_channel_state
from external.workspace_study import simultaneous


@pytest.fixture
def patched(monkeypatch):
    """Apply the study's patches for one test only."""
    for module, name in (
        (system, "_communication_section"),
        (episode_runner, "pop_incoming_messages"),
        (episode_runner, "_close_communication_phase"),
        (episode_runner, "_run_task_phase"),
        (agents, "execute_tool_call"),
        (agents, "reject_undecodable_arguments"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    simultaneous.apply_patches()


def _play(monkeypatch, turns_needed):
    """Run the task phase; each agent finishes on its ``turns_needed``-th turn."""
    both_in_step = threading.Barrier(len(AGENT_IDS))
    calls = {agent: 0 for agent in AGENT_IDS}

    def fake_turn(*, runtime, usage_recorder, **_):
        agent = runtime.agent_id
        calls[agent] += 1
        if calls[agent] <= min(turns_needed.values()):
            # Both agents are still working at this step. The barrier passes only if
            # the other agent's turn for the step is running at the same time.
            both_in_step.wait(timeout=5)
        usage_recorder({"cost_usd": 0.0})
        done = calls[agent] == turns_needed[agent]
        tool = {"tool_name": "get_log", "arguments": {}, "result": {"success": done}}
        return {"tool_calls": [tool], "reasoning_trace": None, "reasoning_trace_chars": 0}

    monkeypatch.setattr(episode_runner, "_run_agent_turn_with_context_pruning", fake_turn)
    usage = []
    episode_runner._run_task_phase(
        state=create_channel_state(episode_id="e"),
        runtimes={a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS},
        episode_id="e",
        config=EpisodeRunConfig(max_rounds=1, verbose=False),
        reasoning_traces=[],
        usage_records=usage,
    )
    return calls, usage


def test_both_agents_act_in_the_same_step(patched, monkeypatch):
    calls, usage = _play(monkeypatch, {"alice": 2, "bob": 2})
    assert calls == {"alice": 2, "bob": 2}
    # Records are merged in AGENT_IDS order within each step, whatever the thread timing.
    assert [(u["actor"], u["agent_attempt"]) for u in usage] == [
        ("alice", 1), ("bob", 1), ("alice", 2), ("bob", 2),
    ]


def test_finished_agent_sits_out_later_steps(patched, monkeypatch):
    calls, usage = _play(monkeypatch, {"alice": 1, "bob": 3})
    assert calls == {"alice": 1, "bob": 3}
    assert [(u["actor"], u["agent_attempt"]) for u in usage] == [
        ("alice", 1), ("bob", 1), ("bob", 2), ("bob", 3),
    ]


def test_budget_ends_the_phase(patched, monkeypatch):
    budget = episode_runner._PHASE_BUDGETS["task"]
    calls, _ = _play(monkeypatch, {"alice": budget + 5, "bob": 1})
    assert calls == {"alice": budget, "bob": 1}


def test_tool_calls_from_two_threads_get_unique_event_ids(patched, monkeypatch):
    def slow_log(state, actor, **_):
        # The author's pattern, widened: read the length, yield, then append.
        event_id = len(state["events"])
        threading.Event().wait(0.001)
        state["events"].append({"event_id": event_id, "actor": actor})
        return {"success": True}

    monkeypatch.setattr(agents, "execute_tool_call", simultaneous._locked(slow_log))
    state = create_channel_state(episode_id="e")

    def worker(actor):
        for _ in range(20):
            agents.execute_tool_call(state=state, actor=actor, tool_name="t", arguments={})

    threads = [threading.Thread(target=worker, args=(a,)) for a in AGENT_IDS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [e["event_id"] for e in state["events"]] == list(range(40))
