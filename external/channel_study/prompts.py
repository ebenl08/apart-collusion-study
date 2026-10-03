"""Prompt text for the send-first-then-read channel.

One change from the paper's system prompt (Appendix H.1.1): the communication
section's turn order. In the paper Alice sends first and Bob reads her message
before replying. Here both agents send without seeing the other's message for that
round, and read it at their next turn. Everything else is the author's text.
"""

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
