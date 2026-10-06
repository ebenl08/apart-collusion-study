"""Child entry point for idea 2: idea 1 plus a communication window between episodes.

One episode:

    Task -> 1 round, send first then read (idea 1) -> Verdict -> Feedback -> Reflection
         -> communication window: COMMUNICATION_WINDOW_ROUNDS rounds in the paper's
            turn order -> next episode

There is no communication window after the last episode. Its messages go into both
agents' histories, so the next episode sees them. Its channel bookkeeping lives in the
episode's own state under ``state["communication_window"]``, apart from the top-level
``events`` the author builds ``channel_transcript`` from, so the two never mix. Each
episode saves it as ``communication_window_transcript`` (delivered messages) and
``communication_window_events`` (every attempt, including rejected ones). Its LLM calls
land in the episode's ``llm_usage`` and ``llm_reasoning_traces`` like any other call,
marked ``communication_window: True``.

Nothing in the author's files is edited (see run.py for how the patching works).
"""

import argparse
from functools import partial

from experiments import episode_runner, output, runner
from experiments.prompts import system
from experiments.prompts.messages import (
    communication_round_instruction,
    peer_delivery_failure_notice,
)
from experiments.protocol.state import AGENT_IDS, deliver_runner_notice, display_name, peer_id
from experiments.tool_schemas import forced_tool_choice
from external.channel_study import run as send_first
from external.channel_study.prompts import (
    communication_window_opening,
    episodes_section,
    verdict_section_with_communication_window,
)

CHILD_MODULE = "external.channel_study.cross_episode"
# Default; set per run with run.communication_window_rounds in the YAML config, which
# __main__.py passes to this child as ROUNDS_FLAG.
COMMUNICATION_WINDOW_ROUNDS = 5
ROUNDS_FLAG = "--communication-window-rounds"

_author_outcomes = episode_runner._process_episode_outcomes
_author_build_result = episode_runner.build_episode_result
_author_load_tasks = runner._load_selected_tasks
_author_verdict_section = system._verdict_section
_author_build_run_output = runner.build_run_output
_author_usage_recorder = episode_runner.make_llm_usage_recorder

# Set once per run: the episode count (load_tasks_and_count) and the communication
# window round count (apply_patches). The author's code calls our hooks with its own
# fixed arguments, so the hooks read these values from here.
_run = {"episodes": None, "communication_window_rounds": COMMUNICATION_WINDOW_ROUNDS}


def new_communication_window(state, config) -> dict:
    """The keys the author's messaging functions read, and nothing else.

    _send_message, pop_incoming_messages and the tool dispatch take a state dict and
    read these keys from it, so this sub-dict is passed to them in the episode state's
    place. It has no episode_id: it belongs to the episode state it is stored in.
    """
    return {
        "round": 0,
        "phase": "communication",
        "throttled": config.throttled,
        "char_limit": config.char_limit,
        "repo_root": state["repo_root"],
        "task_type": state["task_type"],
        "events": [],
        "agents": {agent_id: {"inbox": [], "delivered": False} for agent_id in AGENT_IDS},
    }


def mark_communication_window_usage(**kwargs):
    """The author's usage recorder, with ``communication_window: True`` on each record.

    Swapped in only while the communication window runs. The mark reaches both the
    episode's ``llm_usage`` and the run's usage journal, so window calls can be told
    apart from the in-episode round, which has the same phase name and round numbers.
    """
    record = _author_usage_recorder(**kwargs)
    return lambda usage: record({**usage, "communication_window": True})


def run_communication_window(*, state, runtimes, config, episode_id, reasoning_traces, usage_records):
    """Run the communication window in the paper's turn order, stored in ``state["communication_window"]``."""
    first_trace = len(reasoning_traces)
    episode_runner.make_llm_usage_recorder = mark_communication_window_usage
    try:
        _run_communication_window_rounds(
            state=state, runtimes=runtimes, config=config, episode_id=episode_id,
            reasoning_traces=reasoning_traces, usage_records=usage_records,
        )
    finally:
        episode_runner.make_llm_usage_recorder = _author_usage_recorder
    for trace in reasoning_traces[first_trace:]:
        trace["communication_window"] = True


def _run_communication_window_rounds(*, state, runtimes, config, episode_id, reasoning_traces, usage_records):
    rounds = _run["communication_window_rounds"]
    channel = state["communication_window"] = new_communication_window(state, config)
    tool_choice = forced_tool_choice(state["task_type"], "communication")

    for agent_id, runtime in runtimes.items():
        runtime.messages.append({
            "role": "user", 
            "content": communication_window_opening(
                episode=config.episode_index + 1,
                peer=display_name(peer_id(agent_id)),
                rounds=rounds,
        )})
    for round_index in range(rounds):
        channel["round"] = round_index
        for agent_id in AGENT_IDS:
            runtime = runtimes[agent_id]
            # The author's pop delivers immediately: the paper's turn order.
            episode_runner._inject_incoming_messages(
                runtime.messages,
                incoming=send_first._author_pop_incoming_messages(channel, agent_id),
                max_rounds=rounds,
            )
            runtime.messages.append({"role": "user", "content": communication_round_instruction(
                round_index + 1, rounds
            )})
            delivered = episode_runner._run_agent_attempts(
                runtime=runtime,
                state=channel,
                phase="communication",
                tool_choice=tool_choice,
                episode_id=episode_id,
                round_index=round_index,
                reasoning_traces=reasoning_traces,
                usage_records=usage_records,
                config=config,
            )
            if not delivered:
                deliver_runner_notice(channel, peer_id(agent_id), peer_delivery_failure_notice(
                    peer=agent_id, round_number=round_index + 1
                ))
    # Bob's last message reaches Alice before the next episode starts.
    for agent_id in AGENT_IDS:
        episode_runner._inject_incoming_messages(
            runtimes[agent_id].messages,
            incoming=send_first._author_pop_incoming_messages(channel, agent_id),
            max_rounds=rounds,
        )


def outcomes_then_communication_window(**kwargs):
    """Author's feedback and reflection, then the communication window (not after the last episode)."""
    outcomes = _author_outcomes(**kwargs)
    config = kwargs["config"]
    if config.episode_index < _run["episodes"] - 1:
        run_communication_window(
            state=kwargs["state"],
            runtimes=kwargs["runtimes"],
            config=config,
            episode_id=kwargs["episode_id"],
            reasoning_traces=kwargs["reasoning_traces"],
            usage_records=kwargs["usage_records"],
        )
    return outcomes


def build_result_with_communication_window(**kwargs):
    """Author's episode result, plus the communication window stored in the episode's state.

    ``prepared`` is the PreparedPair the author's run_one_episode passes in; its
    ``state`` is the same episode state run_communication_window wrote to.
    """
    result = _author_build_result(**kwargs)
    channel = kwargs["prepared"].state.get("communication_window")
    events = channel["events"] if channel else []
    result["communication_window_transcript"] = output._build_channel_transcript(events)
    result["communication_window_events"] = events
    return result


def load_tasks_and_count(**kwargs):
    selected = _author_load_tasks(**kwargs)
    _run["episodes"] = len(selected.pairs)
    return selected


def build_run_output_with_rounds(**kwargs):
    """Author's run record, plus the communication window round count in run_config."""
    record = _author_build_run_output(**kwargs)
    record["run_config"]["communication_window_rounds"] = _run["communication_window_rounds"]
    return record


def check_args(argv=None) -> None:
    """The communication window needs a live Bob; a controlled Bob only replays messages."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--bob-model", default="")
    if pre.parse_known_args(argv)[0].bob_model == "controlled":
        raise ValueError("The cross-episode communication window needs a live Bob, not a controlled one.")


def take_rounds_flag(argv: list[str]) -> int:
    """Read and remove --communication-window-rounds, which the author's parser doesn't know."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument(ROUNDS_FLAG, type=int, default=COMMUNICATION_WINDOW_ROUNDS)
    known, rest = pre.parse_known_args(argv)
    if known.communication_window_rounds < 1:
        raise ValueError(f"{ROUNDS_FLAG} must be at least 1.")
    argv[:] = rest
    return known.communication_window_rounds


def apply_patches(communication_window_rounds: int = COMMUNICATION_WINDOW_ROUNDS) -> None:
    send_first.apply_patches()
    _run["communication_window_rounds"] = communication_window_rounds
    system._episodes_section = episodes_section
    system._verdict_section = partial(
        verdict_section_with_communication_window,
        _author_verdict_section,
        communication_window_rounds,
    )
    episode_runner._process_episode_outcomes = outcomes_then_communication_window
    episode_runner.build_episode_result = build_result_with_communication_window
    runner._load_selected_tasks = load_tasks_and_count
    runner.build_run_output = build_run_output_with_rounds


if __name__ == "__main__":
    import sys

    check_args()
    rounds = take_rounds_flag(sys.argv)
    apply_patches(rounds)
    runner.main()
