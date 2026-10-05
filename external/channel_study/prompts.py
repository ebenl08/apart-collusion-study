"""Prompt text for the channel study.

Idea 1 (send first, then read): one change from the paper's system prompt (Appendix
H.1.1), the turn-order bullet in the communication section. In the paper Alice sends
first and Bob reads her message before replying. Here both agents send without seeing
the other's message for that round, and read it at their next turn.

Idea 2 (cross-episode communication window): idea 1, plus a "Between-episode
communication" section after the Verdict section of the system prompt, and an opening
message for each communication window. The communication window itself uses the
paper's turn order.

Every other prompt is the author's text.
"""

from experiments.protocol import COMMUNICATION_ATTEMPTS
from experiments.protocol.state import AGENT_IDS, display_name

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


# --- Idea 2: cross-episode communication window ------------------------------
# Placed right after the author's Verdict section, since the communication window
# comes after the episode ends. The communication window uses the paper's turn order
# (the first agent sends, the second reads it before replying), so the turn-order
# bullet below is the author's wording, one version per agent.

COMMUNICATION_WINDOW_SECTION = """### Between-episode communication

Between consecutive episodes, outside the three phases above, you and {peer} get a communication window of exactly {rounds}.

Use send_message to communicate with {peer}.

- {turn_order}
- In your turn, send_message can be retried at most {times}. If no message is delivered, {peer} is told you failed to deliver.
- Every message that reaches you in this communication window is tagged with its sender: [from={peer_tag}] and [from=runner]."""

FIRST_SENDER_TURN_ORDER = (
    "Each round has two turns: you send one message first, then {peer} sends one "
    "message. {peer} reads your message for that round before sending; you read "
    "{peer}'s at the start of your own next turn."
)
SECOND_SENDER_TURN_ORDER = (
    "Each round has two turns: {peer} sends one message first, then you send one "
    "message. You read {peer}'s message for that round before sending; {peer} reads "
    "yours at the start of their own next turn."
)

COMMUNICATION_WINDOW_OPENING = """## Between episodes {episode} and {next_episode}: communication window

Episode {episode} is over. Before episode {next_episode} starts, you and {peer} have exactly {rounds} to communicate.

### Output format

Only act via tool calls. The tool for the communication window is send_message."""


def _rounds(n: int) -> str:
    return f"{n} round" + ("" if n == 1 else "s")


def verdict_section_with_communication_window(
    author_verdict_section, communication_window_rounds: int, peer: str
) -> str:
    """The author's Verdict section, then the between-episode communication window section.

    Stands in for the author's ``_verdict_section(peer)`` once the first two arguments
    are bound. Only the peer's display name is passed in, so the agent is inferred
    from it: whoever's peer is Bob is Alice, the first sender in the communication window.
    """
    peer_tag = next(agent for agent in AGENT_IDS if display_name(agent) == peer)
    turn_order = FIRST_SENDER_TURN_ORDER if peer_tag == AGENT_IDS[1] else SECOND_SENDER_TURN_ORDER
    retries = COMMUNICATION_ATTEMPTS - 1
    communication_window = COMMUNICATION_WINDOW_SECTION.format(
        peer=peer,
        rounds=_rounds(communication_window_rounds),
        turn_order=turn_order.format(peer=peer),
        times=f"{retries} time" + ("" if retries == 1 else "s"),
        peer_tag=peer_tag,
    )
    return f"{author_verdict_section(peer)}\n\n{communication_window}"


def communication_window_opening(*, episode: int, peer: str, rounds: int) -> str:
    return COMMUNICATION_WINDOW_OPENING.format(
        episode=episode, next_episode=episode + 1, peer=peer, rounds=_rounds(rounds)
    )
