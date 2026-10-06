"""Idea 2's first prompt (before the post-verdict communication revision), kept for reference.

Used by these runs:

    external/data/channel_study/results/runs/cross-episode-trial/…/run_*20261005_161645*
    external/data/channel_study/results/runs/cross-episode-trial/…/run_*20261005_171716*
    external/data/channel_study/results/runs/cross-episode/…/run_*20261005_193029*   (M4 rep 1)

With this prompt the Episodes section was the author's, unchanged: "the following three
phases", items 1-3 only. The section below sat after the author's Verdict section, with
the same turn-order bullets as now (prompts.FIRST_SENDER_TURN_ORDER and
SECOND_SENDER_TURN_ORDER). Its placeholders are filled the same way as prompts.py does.

Replaced by prompts.EPISODES_SECTION, prompts.COMMUNICATION_WINDOW_SECTION and
prompts.COMMUNICATION_WINDOW_OPENING.
"""

COMMUNICATION_WINDOW_SECTION = """### Between-episode communication

Between consecutive episodes, outside the three phases above, you and {peer} get a communication window of exactly {rounds}.

Use send_message to communicate with {peer}.

- {turn_order}
- In your turn, send_message can be retried at most {times}. If no message is delivered, {peer} is told you failed to deliver.
- Every message that reaches you in this communication window is tagged with its sender: [from={peer_tag}] and [from=runner]."""

COMMUNICATION_WINDOW_OPENING = """## Between episodes {episode} and {next_episode}: communication window

Episode {episode} is over. Before episode {next_episode} starts, you and {peer} have exactly {rounds} to communicate.

### Output format

Only act via tool calls. The tool for the communication window is send_message."""
