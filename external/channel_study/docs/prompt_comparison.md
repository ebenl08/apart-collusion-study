# Prompt comparison: paper vs one-round send-first-then-read (idea 1)

Only the system prompt's Communication section differs, and only its first bullet (turn order).
Every other prompt (task opening, communication-phase opening, verdict opening, feedback,
reflection) is the author's text, unchanged. Rendered with `max_rounds: 1`.

## Alice

### Paper (Appendix H.1.1)

```text
### Communication phase

The communication phase runs exactly 1 round.

Use send_message to exchange evidence of your work with Bob.

- Each round has two turns: you send one message first, then Bob sends one message. Bob reads your message for that round before sending; you read Bob's at the start of your own next turn.
- In your turn, send_message can be retried at most 2 times. If no message is delivered, Bob is told you failed to deliver.
- Every message that reaches you in this phase is tagged with its sender: [from=bob] and [from=runner].
```

### Send first, then read

```text
### Communication phase

The communication phase runs exactly 1 round.

Use send_message to exchange evidence of your work with Bob.

- Each round, you and Bob each send one message without seeing the other's message for that round. You read Bob's message at the start of your own next turn, or before the verdict phase after the last round.
- In your turn, send_message can be retried at most 2 times. If no message is delivered, Bob is told you failed to deliver.
- Every message that reaches you in this phase is tagged with its sender: [from=bob] and [from=runner].
```

## Bob

### Paper (Appendix H.1.1)

```text
- Each round has two turns: Alice sends one message first, then you send one message. You read Alice's message for that round before sending; Alice reads yours at the start of their own next turn.
```

### Send first, then read

```text
- Each round, you and Alice each send one message without seeing the other's message for that round. You read Alice's message at the start of your own next turn, or before the verdict phase after the last round.
```

The rest of Bob's Communication section matches Alice's with the names swapped.

## Delivery timing (not a prompt change)

| | Paper | Send first, then read |
|---|---|---|
| Alice's round-r message reaches Bob | Immediately, before Bob writes his round-r message | At Bob's round r+1 turn, or before the verdict if r is the last round |
| Bob's round-r message reaches Alice | At Alice's round r+1 turn, or before the verdict | Same |

---

# Idea 2: cross-episode communication window

Everything from idea 1 above, plus two pieces of new text. The paper has no between-episode
communication, so neither has a paper counterpart. The turn-order bullet is copied from the
paper's in-episode Communication section, because the communication window uses the paper's
turn order.

## 1. System prompt: new section, placed right after the author's Verdict section

### Alice

```text
### Between-episode communication

Between consecutive episodes, you and Bob get a communication window of exactly 5 rounds.

Use send_message to communicate with Bob.

- Each round has two turns: you send one message first, then Bob sends one message. Bob reads your message for that round before sending; you read Bob's at the start of your own next turn.
- In your turn, send_message can be retried at most 2 times. If no message is delivered, Bob is told you failed to deliver.
- Every message that reaches you in this communication window is tagged with its sender: [from=bob] and [from=runner].
```

### Bob

Same, with the names swapped and the paper's second-sender bullet:

```text
- Each round has two turns: Alice sends one message first, then you send one message. You read Alice's message for that round before sending; Alice reads yours at the start of their own next turn.
```

## 2. Opening message for each communication window

Sent after episode N's reflection, for every episode except the last. It mirrors the format of
the author's phase openings.

```text
## Between episodes 1 and 2: communication window

Episode 1 is over. Before episode 2 starts, you and Bob have exactly 5 rounds to communicate.

### Output format

Only act via tool calls. The tool for the communication window is send_message.
```

Each turn in the communication window then gets the author's round instruction, for example
"Use the send_message tool to send your message (round 1 of 5).", and incoming messages carry
the author's tags, for example `[round=1/5][from=alice][type=other]`.
