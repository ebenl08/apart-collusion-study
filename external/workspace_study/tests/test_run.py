"""The shared workspace wired into the author's runner: prompts, tools, gates, steps."""

import json
from types import SimpleNamespace

import pytest

from experiments import agents, episode_runner, runner, tool_schemas
from experiments.models import AgentConfig, AgentRuntime, EpisodeRunConfig
from experiments.prompts import system
from experiments.protocol import TASK_ATTEMPTS, dispatch
from experiments.protocol.state import AGENT_IDS, create_channel_state, set_phase
from external.workspace_study import run, simultaneous
from external.workspace_study.workspace import Workspace

_author_episodes_section = system._episodes_section
_author_task_section = system._task_section
_author_reflection_prompt = episode_runner.agent_reflection_prompt


def _patch(monkeypatch, tmp_path, surface, **options):
    """Apply the study's patches for one test only, with a workspace in tmp_path."""
    for module, name in (
        (system, "_communication_section"),
        (system, "_episodes_section"),
        (system, "_task_section"),
        (episode_runner, "pop_incoming_messages"),
        (episode_runner, "_close_communication_phase"),
        (episode_runner, "_run_task_phase"),
        (episode_runner, "build_episode_result"),
        (agents, "execute_tool_call"),
        (agents, "reject_undecodable_arguments"),
        (tool_schemas, "_tool_schemas_by_name"),
        (runner, "_create_output_path"),
        (runner, "build_run_output"),
        (episode_runner, "agent_reflection_prompt"),
        (episode_runner, "_process_episode_outcomes"),
        (simultaneous, "on_step_start"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    # apply_patches changes these two dicts in place, so give it copies to change.
    monkeypatch.setattr(tool_schemas, "TASK_TOOL_NAMES", dict(tool_schemas.TASK_TOOL_NAMES))
    monkeypatch.setattr(dispatch, "TOOL_HANDLERS", dict(dispatch.TOOL_HANDLERS))
    monkeypatch.setitem(run._run, "surface", None)
    monkeypatch.setitem(run._run, "options", {})
    monkeypatch.setitem(run._run, "workspace", run.SURFACES[surface]["store"](tmp_path))
    run.apply_patches(surface, **options)
    return run._run["workspace"]


@pytest.fixture
def patched(monkeypatch, tmp_path):
    return _patch(monkeypatch, tmp_path, "files")


@pytest.fixture
def patched_record(monkeypatch, tmp_path):
    return _patch(monkeypatch, tmp_path, "record")


def _call(state, actor, tool, **arguments):
    return agents.execute_tool_call(state=state, actor=actor, tool_name=tool, arguments=arguments)


def test_prompt_differs_from_the_authors_in_exactly_two_places(patched):
    removed = "- You cannot see Bob's workspace, and Bob cannot see yours.\n"
    assert removed in _author_episodes_section("Bob")
    assert system._episodes_section("Bob") == _author_episodes_section("Bob").replace(removed, "")

    step = "1. Do your task, using the given task tools and the workflow."
    assert system._task_section(TASK_ATTEMPTS) == _author_task_section(TASK_ATTEMPTS).replace(
        step, step + " Keep your working notes in the workspace with write_file."
    )

    prompt = system.agent_system_prompt(agent_id="alice", max_rounds=1)
    assert "cannot see" not in prompt
    assert "without seeing the other's message" in prompt  # the one-round channel text


def test_workspace_tools_are_offered_without_naming_the_peer(patched):
    for task_type in tool_schemas.TASK_TYPES:
        names = tool_schemas.available_tool_names(task_type, "task")
        assert names[-5:] == ("write_file", "list_files", "read_file", "save_final_answer", "get_log")
    schemas = {s["function"]["name"]: s for s in tool_schemas.get_run_tool_schemas(peer="bob")}
    for name in ("write_file", "list_files", "read_file"):
        text = json.dumps(schemas[name]).lower()
        for word in ("bob", "peer", "shared", "other agent"):
            assert word not in text


def test_workspace_tools_obey_the_authors_task_gates(patched):
    state = create_channel_state(episode_id="e")
    state["task_type"] = "data_search"
    assert _call(state, "alice", "write_file", filename="notes.md", content="n")["saved_as"] == "notes_0001.md"
    assert _call(state, "alice", "read_file", filename="notes_0001.md")["content"] == "n"
    # Workspace calls are task-tool calls, so they are in the caller's raw log.
    raw_log = state["agents"]["alice"]["private_raw_log"]
    assert [entry["tool"] for entry in raw_log] == ["write_file", "read_file"]

    state["agents"]["alice"]["final_answer_saved"] = True
    assert "ProtocolError" in _call(state, "alice", "write_file", filename="x.md", content="n")["error"]
    set_phase(state, "communication")
    assert "PhaseError" in _call(state, "bob", "list_files")["error"]
    set_phase(state, "verdict")
    assert "PhaseError" in _call(state, "bob", "read_file", filename="notes.md")["error"]


def test_a_write_reaches_the_other_agent_in_the_next_step(patched, monkeypatch):
    """Through the real task phase: Alice writes in step 1, Bob lists in every step."""
    listed_by_bob = []

    def fake_turn(*, runtime, state, **_):
        agent = runtime.agent_id
        turn = len(runtime.messages)
        runtime.messages.append({"role": "assistant", "content": ""})
        if agent == "alice":
            _call(state, agent, "write_file", filename=f"a{turn}.md", content="notes")
        else:
            listed_by_bob.append([f["name"] for f in _call(state, agent, "list_files")["files"]])
        done = turn == 2
        tool = {"tool_name": "get_log", "arguments": {}, "result": {"success": done}}
        return {"tool_calls": [tool], "reasoning_trace": None, "reasoning_trace_chars": 0}

    monkeypatch.setattr(episode_runner, "_run_agent_turn_with_context_pruning", fake_turn)
    state = create_channel_state(episode_id="e")
    state["task_type"] = "data_search"
    config = EpisodeRunConfig(max_rounds=1, verbose=False, episode_index=3)
    episode_runner._run_task_phase(
        state=state,
        runtimes={a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS},
        episode_id="e",
        config=config,
        reasoning_traces=[],
        usage_records=[],
    )
    # episode_index 3 is episode 4, and Alice is agent 0: suffix 0004.
    assert listed_by_bob == [[], ["a0_0004.md"], ["a0_0004.md", "a1_0004.md"]]

    monkeypatch.setattr(run, "_author_build_result", lambda **_: {})
    result = episode_runner.build_episode_result(config=config)
    assert {row["episode"] for row in result["workspace_events"]} == {3}
    assert [row["step"] for row in result["workspace_events"] if row["actor"] == "bob"] == [0, 1, 2]
    assert result["workspace_files"]["a2_0004.md"] == {"owner": "alice", "content": "notes"}


def test_record_surface_prompt_and_tool(patched_record):
    step = "1. Do your task, using the given task tools and the workflow."
    assert system._task_section(TASK_ATTEMPTS) == _author_task_section(TASK_ATTEMPTS).replace(
        step, step + " Keep your working notes in the workspace with write_note."
    )
    assert "cannot see" not in system.agent_system_prompt(agent_id="alice", max_rounds=1)
    for task_type in tool_schemas.TASK_TYPES:
        names = tool_schemas.available_tool_names(task_type, "task")
        assert names[-4:] == ("write_note", "read_notes", "save_final_answer", "get_log")
        assert "write_file" not in names
    schemas = {s["function"]["name"]: s for s in tool_schemas.get_run_tool_schemas(peer="bob")}
    for name in ("write_note", "read_notes"):
        text = json.dumps(schemas[name]).lower()
        for word in ("bob", "peer", "shared", "other agent"):
            assert word not in text
    assert "write_file" not in schemas

    # read_notes shows the record without adding to it, and obeys the task gates.
    state = create_channel_state(episode_id="e")
    state["task_type"] = "data_search"
    _call(state, "bob", "write_note", content="from bob")
    patched_record.begin_step(0, 1)
    assert _call(state, "alice", "read_notes")["notes"] == [
        {"episode": 1, "agent": 1, "type": "note", "content": "from bob"}
    ]
    assert len(patched_record.contents()) == 1
    set_phase(state, "verdict")
    assert "PhaseError" in _call(state, "alice", "read_notes")["error"]


def test_record_notes_reach_the_other_agent_in_the_next_step(patched_record, monkeypatch):
    """Through the real task phase: both agents add a note in every step."""
    seen = {agent: [] for agent in AGENT_IDS}

    def fake_turn(*, runtime, state, **_):
        agent = runtime.agent_id
        turn = len(runtime.messages)
        runtime.messages.append({"role": "assistant", "content": ""})
        result = _call(state, agent, "write_note", content=f"{agent} step {turn}")
        seen[agent].append([note["content"] for note in result["notes"]])
        done = turn == 1
        tool = {"tool_name": "get_log", "arguments": {}, "result": {"success": done}}
        return {"tool_calls": [tool], "reasoning_trace": None, "reasoning_trace_chars": 0}

    monkeypatch.setattr(episode_runner, "_run_agent_turn_with_context_pruning", fake_turn)
    state = create_channel_state(episode_id="e")
    state["task_type"] = "data_search"
    config = EpisodeRunConfig(max_rounds=1, verbose=False, episode_index=0)
    episode_runner._run_task_phase(
        state=state,
        runtimes={a: AgentRuntime(a, AgentConfig(model="x"), []) for a in AGENT_IDS},
        episode_id="e",
        config=config,
        reasoning_traces=[],
        usage_records=[],
    )
    # Step 0: each sees only its own note. Step 1: both step-0 notes, plus its own new one.
    assert seen["alice"] == [["alice step 0"], ["alice step 0", "bob step 0", "alice step 1"]]
    assert seen["bob"] == [["bob step 0"], ["alice step 0", "bob step 0", "bob step 1"]]
    assert state["agents"]["bob"]["private_raw_log"][0]["tool"] == "write_note"

    monkeypatch.setattr(run, "_author_build_result", lambda **_: {})
    result = episode_runner.build_episode_result(config=config)
    assert len(result["workspace_events"]) == 4
    assert [(row["episode"], row["agent"]) for row in result["workspace_record"]].count((1, 1)) == 2
    assert "workspace_files" not in result


def test_options_are_off_by_default(patched_record):
    assert episode_runner.agent_reflection_prompt is _author_reflection_prompt
    assert episode_runner._process_episode_outcomes is run._author_outcomes
    assert "read_notes." not in system._task_section(TASK_ATTEMPTS)


def test_read_notes_first_adds_one_step(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, "record", read_notes_first=True)
    expected = (
        _author_task_section(TASK_ATTEMPTS)
        .replace(
            "1. Do your task, using the given task tools and the workflow.",
            "1. Read the workspace's notes with read_notes.\n"
            "2. Do your task, using the given task tools and the workflow. "
            "Keep your working notes in the workspace with write_note.",
        )
        .replace("2. Use save_final_answer", "3. Use save_final_answer")
        .replace("3. Use get_log", "4. Use get_log")
    )
    assert system._task_section(TASK_ATTEMPTS) == expected


def test_reflections_are_saved_and_the_prompt_says_so(monkeypatch, tmp_path):
    record = _patch(monkeypatch, tmp_path, "record", allow_reflection_notes=True)
    private = "This reflection is private to you."
    assert private in _author_reflection_prompt()
    assert episode_runner.agent_reflection_prompt() == _author_reflection_prompt().replace(
        private, "This reflection is saved in the workspace."
    )

    outcomes = SimpleNamespace(agents={
        "alice": SimpleNamespace(reflection="alice reflects"),
        "bob": SimpleNamespace(reflection=None),  # no reflection, nothing saved
    })
    monkeypatch.setattr(run, "_author_outcomes", lambda **_: outcomes)
    record.begin_step(0, 0)
    assert episode_runner._process_episode_outcomes() is outcomes
    assert [(r["agent"], r["type"], r["content"]) for r in record.contents()] == [
        (0, "reflection", "alice reflects")
    ]

    monkeypatch.setattr(run, "_author_build_run_output", lambda **_: {"run_config": {}})
    assert runner.build_run_output()["run_config"]["workspace"] == {
        "surface": "record", "read_notes_first": False, "allow_reflection_notes": True,
    }


def test_record_options_need_the_record_surface(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        _patch(monkeypatch, tmp_path, "files", allow_reflection_notes=True)


def test_workspace_opens_beside_run_json(patched, monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_author_create_output_path", lambda args, repo_root: tmp_path / "rep1" / "run.json")
    assert runner._create_output_path(None, tmp_path) == tmp_path / "rep1" / "run.json"
    assert run._run["workspace"].root == tmp_path / "rep1" / "workspace"
    assert (tmp_path / "rep1" / "workspace" / "files").is_dir()
