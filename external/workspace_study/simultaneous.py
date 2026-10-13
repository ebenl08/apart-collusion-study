"""Child entry point: the one-round condition with a simultaneous-step task phase.

The author runs the task phase one agent at a time: Alice to completion, then Bob.
Here both agents take step k at the same time, in two threads, then both take step
k+1. Neither waits for the other to finish its task, and a step ends only when both
turns have returned, so the order does not depend on which LLM call is faster.

Nothing in the author's files is edited. Patches, on top of the channel study's
one-round patches:

  * ``episode_runner._run_task_phase``: the simultaneous-step version below;
  * ``agents.execute_tool_call`` and ``agents.reject_undecodable_arguments``: wrapped
    in one lock, so tool calls run one at a time and only the LLM calls overlap. The
    author's ``_log_event`` reads ``len(events)`` and then appends, which two threads
    could interleave.

Budgets, per-turn logging, usage records and reasoning traces are the author's.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from experiments import agents, episode_runner, runner
from experiments.protocol.state import AGENT_IDS
from external.channel_study import run as one_round

CHILD_MODULE = "external.workspace_study.simultaneous"

_TOOL_LOCK = threading.Lock()


def on_step_start(episode_index: int, step: int) -> None:
    """Called before each step's turns are submitted. The workspace child replaces it."""


def _locked(tool_function):
    def call(**kwargs):
        with _TOOL_LOCK:
            return tool_function(**kwargs)

    return call


def _task_turn(*, runtime, state, episode_id, config, attempt_index, attempts_left):
    """One task-phase turn: the body of the author's ``_run_agent_attempts`` loop.

    Returns (phase completed, reasoning traces, usage records). The records are kept
    per turn and merged by the caller in AGENT_IDS order, so their order in run.json
    does not depend on thread timing.
    """
    agent_id = runtime.agent_id
    traces, usage = [], []
    episode_runner.reset_message_delivery(state, agent_id)
    episode_runner.log_progress(
        f"    {agent_id} → LLM (task, {attempts_left} left) …", config.verbose
    )
    turn = episode_runner._run_agent_turn_with_context_pruning(
        runtime=runtime,
        state=state,
        tool_choice="required",
        verbose=config.verbose,
        usage_recorder=episode_runner.make_llm_usage_recorder(
            records=usage,
            journal_path=config.usage_journal_path,
            invocation_id=config.usage_invocation_id,
            episode_id=episode_id,
            episode_index=config.episode_index,
            actor=agent_id,
            phase="task",
            round_idx=None,
            attempt_idx=attempt_index,
        ),
    )
    episode_runner._append_llm_reasoning_trace(
        traces,
        agent_id=agent_id,
        phase="task",
        round_idx=None,
        attempt_idx=attempt_index,
        turn_result=turn,
    )
    episode_runner.log_progress(
        f"    {agent_id} ← {episode_runner._summarize_turn(turn)}", config.verbose
    )
    return episode_runner._phase_completed(turn, "task"), traces, usage


def run_task_phase_simultaneous(
    *, state, runtimes, episode_id, config, reasoning_traces, usage_records
):
    """Run both agents' task phases step by step, both agents active in each step."""
    episode_runner.set_phase(state, "task")
    active = [
        agent_id
        for agent_id in AGENT_IDS
        if not (agent_id == "bob" and config.controlled_bob_verdict)
    ]
    budget = episode_runner._PHASE_BUDGETS["task"]
    with ThreadPoolExecutor(max_workers=len(AGENT_IDS)) as pool:
        for step in range(budget):
            if not active:
                break
            on_step_start(config.episode_index, step)
            episode_runner.log_progress(
                f"  Task phase step {step + 1}: {', '.join(active)} (episode={episode_id})",
                config.verbose,
            )
            turns = {
                agent_id: pool.submit(
                    _task_turn,
                    runtime=runtimes[agent_id],
                    state=state,
                    episode_id=episode_id,
                    config=config,
                    attempt_index=step,
                    attempts_left=budget - step,
                )
                for agent_id in active
            }
            still_active = []
            for agent_id in active:
                completed, traces, usage = turns[agent_id].result()
                reasoning_traces.extend(traces)
                usage_records.extend(usage)
                if not completed:
                    still_active.append(agent_id)
            active = still_active


def apply_patches() -> None:
    one_round.apply_patches()
    episode_runner._run_task_phase = run_task_phase_simultaneous
    agents.execute_tool_call = _locked(agents.execute_tool_call)
    agents.reject_undecodable_arguments = _locked(agents.reject_undecodable_arguments)


if __name__ == "__main__":
    apply_patches()
    runner.main()
