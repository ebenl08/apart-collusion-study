# Prompt comparison: paper vs one-round send-first-then-read (idea 1)

Only the system prompt's Communication section differs. Every other prompt (task, communication-phase opening, verdict, feedback, reflection) is the author's text, unchanged. Rendered with `max_rounds: 1`.

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

### Diff of the whole system prompt

```diff
--- paper
+++ send-first
@@ -50 +50 @@
-- Each round has two turns: you send one message first, then Bob sends one message. Bob reads your message for that round before sending; you read Bob's at the start of your own next turn.
+- Each round, you and Bob each send one message without seeing the other's message for that round. You read Bob's message at the start of your own next turn, or before the verdict phase after the last round.
```

## Bob

### Paper (Appendix H.1.1)

```text
### Communication phase

The communication phase runs exactly 1 round.

Use send_message to exchange evidence of your work with Alice.

- Each round has two turns: Alice sends one message first, then you send one message. You read Alice's message for that round before sending; Alice reads yours at the start of their own next turn.
- In your turn, send_message can be retried at most 2 times. If no message is delivered, Alice is told you failed to deliver.
- Every message that reaches you in this phase is tagged with its sender: [from=alice] and [from=runner].
```

### Send first, then read

```text
### Communication phase

The communication phase runs exactly 1 round.

Use send_message to exchange evidence of your work with Alice.

- Each round, you and Alice each send one message without seeing the other's message for that round. You read Alice's message at the start of your own next turn, or before the verdict phase after the last round.
- In your turn, send_message can be retried at most 2 times. If no message is delivered, Alice is told you failed to deliver.
- Every message that reaches you in this phase is tagged with its sender: [from=alice] and [from=runner].
```

### Diff of the whole system prompt

```diff
--- paper
+++ send-first
@@ -50 +50 @@
-- Each round has two turns: Alice sends one message first, then you send one message. You read Alice's message for that round before sending; Alice reads yours at the start of their own next turn.
+- Each round, you and Alice each send one message without seeing the other's message for that round. You read Alice's message at the start of your own next turn, or before the verdict phase after the last round.
```
