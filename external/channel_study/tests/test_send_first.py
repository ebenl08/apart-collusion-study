"""Send-first-then-read: nobody sees the other's message for a round before sending.

Runs the author's real communication loop with a fake agent turn in place of the LLM.
"""

from types import SimpleNamespace

import pytest

from experiments import episode_runner
from experiments.models import AgentConfig, AgentRuntime, EpisodeRunConfig
from experiments.prompts.system import agent_system_prompt
from experiments.protocol.messaging import _send_message
from experiments.protocol.state import AGENT_IDS, create_channel_state, reset_message_delivery
from external.channel_study import run


@pytest.fixture
def patched(monkeypatch):
    """Apply the study's patches for one test only."""
    from experiments.prompts import system

    for module, name in (
        (system, "_communication_section"),
        (episode_runner, "pop_incoming_messages"),
        (episode_runner, "_close_communication_phase"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    run.apply_patches()


def _play(monkeypatch, rounds):
    """Run the communication phase; each agent records what it had seen when it sent."""
    seen_when_sending = {agent: [] for agent in AGENT_IDS}

    def fake_turn(*, runtime, state, round_index, **_):
        received = [m["content"] for m in runtime.messages if "[from=" in m.get("content", "")]
        seen_when_sending[runtime.agent_id].append(received)
        reset_message_delivery(state, runtime.agent_id)  # the real attempt loop does this
        _send_message(state, runtime.agent_id, f"{runtime.agent_id}-r{round_index + 1}")
        return True

    monkeypatch.setattr(episode_runner, "_run_agent_attempts", fake_turn)
    state = create_channel_state(episode_id="e")
    prepared = SimpleNamespace(
        task_type="code_analysis",
        agents={a: SimpleNamespace(judging_prompt="peer task") for a in AGENT_IDS},
    )
    runtimes = {a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS}
    episode_runner._run_communication_phase(
        prepared=prepared, state=state, runtimes=runtimes, episode_id="e",
        config=EpisodeRunConfig(max_rounds=rounds, verbose=False),
        reasoning_traces=[], usage_records=[],
    )
    return seen_when_sending, runtimes


def test_one_round_both_blind_then_both_see_before_verdict(patched, monkeypatch):
    seen, runtimes = _play(monkeypatch, rounds=1)
    assert seen == {"alice": [[]], "bob": [[]]}  # neither saw anything before sending
    for agent, peer in (("alice", "bob"), ("bob", "alice")):
        assert any(f"{peer}-r1" in m.get("content", "") for m in runtimes[agent].messages)


def test_multi_round_each_reads_only_earlier_rounds(patched, monkeypatch):
    seen, _ = _play(monkeypatch, rounds=3)
    for agent, peer in (("alice", "bob"), ("bob", "alice")):
        for r, received in enumerate(seen[agent]):
            assert not any(f"{peer}-r{r + 1}" in c for c in received)  # never same round
            if r:
                assert any(f"{peer}-r{r}" in c for c in received)  # previous round arrived


def test_author_loop_is_unchanged_without_patches(monkeypatch):
    seen, _ = _play(monkeypatch, rounds=1)
    assert seen["bob"] == [["[round=1/1][from=alice][type=other]\n\nalice-r1"]]


def test_prompt_states_send_first(patched):
    text = agent_system_prompt(agent_id="bob", max_rounds=1)
    assert "each send one message without seeing the other's message" in text
    assert "sends one message first" not in text and "exactly 1 round." in text
