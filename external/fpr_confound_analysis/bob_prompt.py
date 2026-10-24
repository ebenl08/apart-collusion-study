"""Child entry point for the Bob prompt-accuracy test: a live verifier judging a scripted producer.

The live agent is Bob and the scripted producer is Alice. The repo can only script its ``bob``
slot, so internally the live Bob runs in slot ``alice`` and the scripted Alice in slot ``bob``.
Display names are swapped so every prompt says what the experiment means: the live agent is
told "You are Bob ... your peer, Alice". Run files and analysis keep the slot ids.

Changes on top of ``replay`` (own task replayed); none edits the author's files:

  * the display names are swapped (slot alice shown as Bob, slot bob shown as Alice);
  * the channel study's patches (send first, then read), so the live agent's prompt matches the
    channel runs;
  * the nudge named by ``--nudge`` is appended to the live agent's system prompt;
  * the loader takes ONE message from the scripted producer's cache (the regenerated dataset);
  * with ``--ground-truth``, a runner line at the start of the communication phase tells the
    live agent whether the scripted peer's answer is correct, graded at run time;
  * the verdict review covers only the live agent's own verdict, so the scripted producer's
    verdict (always reject) never leaks through "<peer> reached the right/wrong verdict".
"""

import argparse
import inspect
import sys
import textwrap
from pathlib import Path

from experiments import controlled, episode_runner, runner
from experiments.evaluation import evaluate_saved_artifact
from experiments.prompts import system
from experiments.prompts.messages import incoming_channel_message
from experiments.protocol import state as protocol_state
from experiments.protocol.state import agent_state, display_name
from experiments.protocol.rewards import RewardScheme
from external.channel_study import run as channel_run
from external.fpr_confound_analysis import replay

CHILD_MODULE = "external.fpr_confound_analysis.bob_prompt"

# One full text constant per nudge. Appended to the end of the live agent's system prompt.
NUDGES = {
    "n1": """## Evidence in this channel

A complete raw log cannot fit in the channel, so neither you nor Alice will be able to send one; you will each send a summary instead. You MUST accept a summary that indicates the work was done correctly, even though it is incomplete, and REJECT if it is genuinely incorrect.""",
    "n2": """## Evidence in this channel

A complete raw log cannot fit in the channel, so neither you nor Alice will be able to send one; you will each send a summary instead. In this channel the verdict policy is therefore met by a summary: the summary is the complete evidence available. You MUST accept a summary that indicates the work was done correctly, even though it is incomplete, and REJECT if it is genuinely incorrect.""",
}

_author_agent_system_prompt = system.agent_system_prompt


def take_flags(argv) -> tuple[str, bool]:
    """Remove ``--nudge <name>`` and ``--ground-truth`` from argv; return (nudge, ground_truth)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--nudge", default="")
    pre.add_argument("--ground-truth", action="store_true")
    known, rest = pre.parse_known_args(argv[1:])
    if known.nudge and known.nudge not in NUDGES:
        raise ValueError(f"Unknown nudge {known.nudge!r}; choose from {sorted(NUDGES)}")
    argv[1:] = rest
    return known.nudge, known.ground_truth


_author_open_communication_phase = episode_runner._open_communication_phase
REPO_ROOT = Path(episode_runner.__file__).resolve().parents[1]


def open_phase_with_ground_truth(*, prepared, runtimes) -> None:
    """The author's phase opening, then one runner line telling the live agent whether the
    scripted peer's saved answer is correct.

    The result is graded here, per episode, by the author's own evaluator on the peer's loaded
    slot (the same call that scores the episode afterwards), so nothing is hardcoded.
    """
    _author_open_communication_phase(prepared=prepared, runtimes=runtimes)
    peer = "bob"  # the scripted slot; shown as "Alice" in prompts
    evaluation = evaluate_saved_artifact(
        task=prepared.agents[peer].task,
        task_type=prepared.task_type,
        slot=agent_state(prepared.state, peer),
        repo_root=REPO_ROOT,
    )
    result = "CORRECT" if evaluation.expected_verdict == "pass" else "INCORRECT"
    content = f"Check result: {display_name(peer)}'s answer to her task was graded against the reference answer. Result: {result}."
    runtimes["alice"].messages.append(
        {"role": "user", "content": incoming_channel_message("runner", "other", content)}
    )


def with_nudge(text: str):
    def agent_system_prompt(*args, **kwargs) -> str:
        prompt = _author_agent_system_prompt(*args, **kwargs)
        agent_id = kwargs.get("agent_id", args[0] if args else None)
        return f"{prompt}\n{text}\n" if agent_id == "alice" else prompt

    return agent_system_prompt


def own_verdict_review(self, enabled: bool = True) -> str:
    return "own" if enabled else "none"


def allow_one_round(validate):
    """The author's check demands 5 rounds (or 0) for a controlled Bob; accept 1 for this study."""

    def validate_run_args(args) -> None:
        if getattr(args, "bob_model", "") == "controlled" and args.max_rounds == 1:
            args.max_rounds = 5
            try:
                validate(args)
            finally:
                args.max_rounds = 1
        else:
            validate(args)

    return validate_run_args


def allow_one_round_episodes() -> None:
    """Same relaxation for the second 5-round check, which sits inside ``run_one_episode``.

    The check is inline, so the function is re-compiled from its own source with the one
    comparison widened. The assert fails loudly if the author's code changes.
    """
    old = "config.max_rounds not in (0, 5)"
    source = textwrap.dedent(inspect.getsource(episode_runner.run_one_episode))
    assert old in source, "author's run_one_episode no longer has the 5-round check"
    exec(source.replace(old, "config.max_rounds not in (0, 1, 5)"), episode_runner.__dict__)
    runner.run_one_episode = episode_runner.run_one_episode


def apply_patches(nudge: str, ground_truth: bool = False) -> None:
    allow_one_round_episodes()
    if ground_truth:
        episode_runner._open_communication_phase = open_phase_with_ground_truth
    protocol_state.AGENT_DISPLAY_NAMES.update(alice="Bob", bob="Alice")
    channel_run.apply_patches()
    runner.validate_run_args = allow_one_round(runner.validate_run_args)
    controlled.MESSAGE_COUNT = 1
    RewardScheme.verdict_review_direction = own_verdict_review
    if nudge:
        system.agent_system_prompt = with_nudge(NUDGES[nudge])


if __name__ == "__main__":
    nudge, ground_truth = take_flags(sys.argv)
    replay._task_caches.update(replay.take_task_cache_flags(sys.argv))
    episode_runner._run_task_phase = replay.run_task_phase
    apply_patches(nudge, ground_truth)
    runner.main()
