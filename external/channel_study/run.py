"""Child entry point: the author's runner with the send-first-then-read channel.

Nothing in the author's files is edited. Patching module globals works because the
author's functions look these names up at call time. Two patches:

  * the system prompt's turn-order text (prompts.py);
  * delivery: during the communication phase an agent only receives messages from
    earlier rounds, so neither sees the other's message before sending its own.
    The final round's messages are released when the phase closes, before the verdict.

All other behaviour (rounds, char limit, tools, feedback, reflection) is the paper's.
"""

from experiments import episode_runner, runner
from experiments.prompts import system
from experiments.protocol.state import agent_state
from external.channel_study.prompts import communication_section

CHILD_MODULE = "external.channel_study.run"

_author_pop_incoming_messages = episode_runner.pop_incoming_messages
_author_close_communication_phase = episode_runner._close_communication_phase


def pop_earlier_rounds(state, actor):
    """Hand over only messages written before the current round; keep the rest queued."""
    if state["phase"] != "communication" or state.get("release_all"):
        return _author_pop_incoming_messages(state, actor)
    slot = agent_state(state, actor)
    ready = [m for m in slot["inbox"] if m["round"] < state["round"]]
    slot["inbox"] = [m for m in slot["inbox"] if m["round"] >= state["round"]]
    return ready


def close_and_release(*, state, runtimes, config):
    """Author's close step, with the last round's messages released."""
    state["release_all"] = True
    try:
        _author_close_communication_phase(state=state, runtimes=runtimes, config=config)
    finally:
        del state["release_all"]


def apply_patches() -> None:
    system._communication_section = communication_section
    episode_runner.pop_incoming_messages = pop_earlier_rounds
    episode_runner._close_communication_phase = close_and_release


if __name__ == "__main__":
    apply_patches()
    runner.main()
