"""Idea 2: the communication window after reflection uses the paper's turn order, lands
in both histories, stays out of the episode's channel_transcript, and is skipped after
the last episode."""

from functools import partial
from pathlib import Path

import pytest

from experiments import episode_runner, runner
from experiments.memory.cross_episode import set_cross_episode_memory_from_results
from experiments.models import AgentConfig, AgentRuntime, EpisodeRunConfig, TaskEvaluation
from experiments.prompts import system
from experiments.protocol.messaging import _send_message
from experiments.protocol.state import AGENT_IDS, create_channel_state, reset_message_delivery
from experiments.protocol.submissions import _submit_verdict
from experiments.tasks import read_task_pairs
from external.channel_study import cross_episode
from external.channel_study.prompts import verdict_section_with_communication_window

ROUNDS = cross_episode.COMMUNICATION_WINDOW_ROUNDS
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def fake_agents(monkeypatch):
    """Replace the LLM turn. Every agent sends a message tagged with its round, and
    accepts in the verdict phase; each records what it had received when it sent."""
    seen = {agent: [] for agent in AGENT_IDS}

    def fake_turn(*, runtime, state, phase, round_index, reasoning_traces, usage_records, **_):
        agent = runtime.agent_id
        episode_runner.make_llm_usage_recorder(
            records=usage_records, journal_path=None, invocation_id="t", episode_id="e",
            episode_index=0, actor=agent, phase=phase, round_idx=round_index, attempt_idx=0,
        )({})
        reasoning_traces.append({"agent_id": agent, "phase": phase, "round": round_index})
        if phase == "communication":
            seen[agent].append(
                [m["content"] for m in runtime.messages if "[from=" in m.get("content", "")]
            )
            reset_message_delivery(state, agent)
            _send_message(state, agent, f"{agent}-r{round_index + 1}")
        elif phase == "verdict":
            _submit_verdict(state, agent, "accept", "fake")
        return True

    monkeypatch.setattr(episode_runner, "_run_agent_attempts", fake_turn)
    return seen


@pytest.fixture
def patched(monkeypatch):
    """Apply the study's patches for one test only."""
    for module, name in (
        (system, "_communication_section"),
        (system, "_verdict_section"),
        (episode_runner, "pop_incoming_messages"),
        (episode_runner, "_close_communication_phase"),
        (episode_runner, "_process_episode_outcomes"),
        (episode_runner, "build_episode_result"),
        (runner, "_load_selected_tasks"),
        (runner, "build_run_output"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    monkeypatch.setitem(cross_episode._run, "communication_window_rounds", ROUNDS)
    cross_episode.apply_patches()


def _state():
    state = create_channel_state(episode_id="e")
    state.update(repo_root=".", task_type="code_analysis")
    return state


def test_communication_window_uses_paper_turn_order(fake_agents):
    runtimes = {a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS}
    state = _state()
    cross_episode.run_communication_window(
        state=state, runtimes=runtimes, config=EpisodeRunConfig(verbose=False),
        episode_id="e", reasoning_traces=[], usage_records=[],
    )
    channel = state["communication_window"]
    assert not state["events"]  # the episode's own events stay untouched
    for r, received in enumerate(fake_agents["bob"]):  # Bob reads Alice's same-round message
        assert any(f"alice-r{r + 1}" in c for c in received)
    for r, received in enumerate(fake_agents["alice"]):  # Alice never sees Bob's first
        assert not any(f"bob-r{r + 1}" in c for c in received)
    assert any(f"-r{ROUNDS}" in m.get("content", "") and "[from=bob]" in m.get("content", "")
               for m in runtimes["alice"].messages)  # Bob's last message reaches Alice
    assert [e["actor"] for e in channel["events"]] == ["alice", "bob"] * ROUNDS
    assert runtimes["alice"].messages[0]["content"].startswith(
        "## Between episodes 1 and 2: communication window"
    )


def test_two_real_episodes(patched, fake_agents, monkeypatch):
    """Run the author's run_one_episode twice with fake LLM turns."""
    monkeypatch.setattr(episode_runner, "_run_reflection", lambda **_: ("reflection", {}))
    monkeypatch.setattr(
        episode_runner, "evaluate_saved_artifact", lambda **_: TaskEvaluation("pass", None)
    )
    pairs = read_task_pairs(REPO / "task/task_sequences_trial/rep001_sampled_manifest.json", REPO)
    monkeypatch.setitem(cross_episode._run, "episodes", len(pairs))
    messages = {a: system.initial_agent_messages(agent_id=a, max_rounds=1) for a in AGENT_IDS}
    results = []
    for index, pair in enumerate(pairs):
        result = episode_runner.run_one_episode(
            pair=pair, agent_configs={a: AgentConfig(model="x") for a in AGENT_IDS},
            repo_root=REPO, agent_messages=messages,
            config=EpisodeRunConfig(max_rounds=1, episode_index=index, verbose=False, temp_run_id="t"),
        )
        set_cross_episode_memory_from_results(
            messages, scope="full-history", episode_id=str(result["episode_id"])
        )
        results.append(result)

    first, last = results
    assert len(first["communication_window_transcript"]) == 2 * ROUNDS
    assert len(first["communication_window_events"]) == 2 * ROUNDS
    assert last["communication_window_transcript"] == []  # none after the last episode
    assert len(first["channel_transcript"]) == 2  # in-episode: one message each, no window
    for records in (first["llm_usage"], first["llm_reasoning_traces"]):
        marked = [r for r in records if r.get("communication_window")]
        assert len(marked) == 2 * ROUNDS  # every window call, and only those
        assert records[-len(marked):] == marked
    assert not any(r.get("communication_window") for r in last["llm_usage"])
    snapshot = " ".join(str(m.get("content", "")) for m in first["agents"]["alice"]["messages"])
    assert "communication window" in snapshot  # saved with episode 1
    history = [str(m.get("content", "")) for m in messages["bob"]]
    window_at = next(i for i, c in enumerate(history) if "Between episodes 1 and 2" in c)
    episode_2_at = next(i for i, c in enumerate(history) if c.startswith("## Episode 2: task phase"))
    assert window_at < episode_2_at  # episode 2 starts with the window in memory


def test_system_prompt_places_communication_window_after_verdict(monkeypatch):
    monkeypatch.setattr(system, "_verdict_section", partial(
        verdict_section_with_communication_window, system._verdict_section, ROUNDS,
    ))
    alice = system.agent_system_prompt(agent_id="alice", max_rounds=1)
    bob = system.agent_system_prompt(agent_id="bob", max_rounds=1)
    for text in (alice, bob):
        assert text.index("### Verdict phase") < text.index("### Between-episode communication")
        assert text.index("### Between-episode communication") < text.index("## Memory")
        assert "Between consecutive episodes" in text and "exactly 5 rounds" in text
        assert "feedback and reflection" not in text
    assert "you send one message first, then Bob sends" in alice  # paper order
    assert "Alice sends one message first, then you send" in bob


def test_rounds_flag_is_read_and_removed():
    argv = ["x", "--max-rounds", "1", cross_episode.ROUNDS_FLAG, "3"]
    assert cross_episode.take_rounds_flag(argv) == 3
    assert argv == ["x", "--max-rounds", "1"]  # the author's parser never sees it
    assert cross_episode.take_rounds_flag(["x"]) == ROUNDS  # default
    with pytest.raises(ValueError):
        cross_episode.take_rounds_flag(["x", cross_episode.ROUNDS_FLAG, "0"])


def test_configured_rounds_reach_window_prompt_and_run_config(patched, fake_agents, monkeypatch):
    cross_episode.apply_patches(3)
    runtimes = {a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS}
    state = _state()
    cross_episode.run_communication_window(
        state=state, runtimes=runtimes, config=EpisodeRunConfig(verbose=False),
        episode_id="e", reasoning_traces=[], usage_records=[],
    )
    assert len(state["communication_window"]["events"]) == 2 * 3
    assert "window of exactly 3 rounds" in system.agent_system_prompt(agent_id="alice", max_rounds=1)
    monkeypatch.setattr(cross_episode, "_author_build_run_output", lambda **_: {"run_config": {}})
    assert runner.build_run_output()["run_config"]["communication_window_rounds"] == 3


def test_controlled_bob_is_rejected():
    with pytest.raises(ValueError):
        cross_episode.check_args(["--bob-model", "controlled"])
    cross_episode.check_args([])
