"""The send-first-then-read channel, copied from ``external.channel_study`` (``run.py`` and the
idea-1 part of ``prompts.py``) so this experiment folder is closed.

Nothing in the author's files is edited. Patching module globals works because the
author's functions look these names up at call time. Two patches:

  * the system prompt's turn-order text (COMMUNICATION_SECTION);
  * delivery: during the communication phase an agent only receives messages from
    earlier rounds, so neither sees the other's message before sending its own.
    The final round's messages are released when the phase closes, before the verdict.

All other behaviour (rounds, char limit, tools, feedback, reflection) is the paper's.
"""

from experiments import episode_runner
from experiments.prompts import system
from experiments.protocol.state import agent_state

# One change from the paper's system prompt (Appendix H.1.1): the turn-order bullet. In the
# paper Alice sends first and Bob reads her message before replying. Here both agents send
# without seeing the other's message for that round, and read it at their next turn.
COMMUNICATION_SECTION = """### Communication phase

The communication phase runs exactly {rounds}.

Use send_message to exchange evidence of your work with {peer}.

- Each round, you and {peer} each send one message without seeing the other's message for that round. You read {peer}'s message at the start of your own next turn, or before the verdict phase after the last round.
- In your turn, send_message can be retried at most {times}. If no message is delivered, {peer} is told you failed to deliver.
- Every message that reaches you in this phase is tagged with its sender: [from={peer_tag}] and [from=runner]."""


def communication_section(
    max_rounds: int,
    delivery_attempts: int,
    agent_id: str,
    peer: str,
    peer_tag: str,
) -> str:
    """Same arguments as the author's ``_communication_section``, so it can stand in for it."""
    retries = delivery_attempts - 1
    return COMMUNICATION_SECTION.format(
        rounds=f"{max_rounds} round" + ("" if max_rounds == 1 else "s"),
        peer=peer,
        times=f"{retries} time" + ("" if retries == 1 else "s"),
        peer_tag=peer_tag,
    )


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
