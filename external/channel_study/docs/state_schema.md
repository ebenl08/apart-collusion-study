# State schema: episode state and run.json

This file describes the in-memory episode state the runner keeps while an episode runs, and the episode object saved to `run.json`. Parts added by the channel study are marked **NEW (idea 2)**. Everything else is the author's code, unchanged.

Sources: `experiments/protocol/state.py` (state), `experiments/output.py` (run.json), `external/channel_study/cross_episode.py` (communication window).

## 1. Episode state (in memory)

One plain `dict` per episode, created by `create_channel_state` (`state.py:90`) in `_prepare_pair` (`episode_runner.py:481`). It is not saved to `run.json` as a whole. `run.json` stores fields derived from it (section 2).

### 1.1 Top level

| Key | Type | Meaning |
|---|---|---|
| `episode_id` | str | `"<alice task id>+<bob task id>"`, e.g. `ca_15_intersection+ca_05_pagination` |
| `round` | int | Current in-episode communication round, 0-based (shown to agents as 1-based) |
| `phase` | str | `"task"`, `"communication"` or `"verdict"`. Only these are accepted by `set_phase`. The phase decides which tools an agent may call |
| `throttled` | bool | Whether `char_limit` is enforced |
| `char_limit` | int | Per-message character cap (200) |
| `repo_root` | str | Repo path, set by `_prepare_pair` |
| `task_type` | str | `code_analysis`, `record_extraction` or `data_search` |
| `events` | list | Log of every in-episode tool call (section 1.3) |
| `agents` | dict | `{"alice": slot, "bob": slot}` (section 1.2) |
| `controlled_bob` | dict | Only in scripted-Bob mode. Not used by the channel study |
| `communication_window` | dict | **NEW (idea 2).** The between-episode communication window (section 1.5). Present only after the window has run; absent for the last episode and in idea 1 |

### 1.2 Agent slot: `state["agents"][agent_id]`

Built by `_agent_slot` (`state.py:63`).

| Group | Key | Type | Meaning |
|---|---|---|---|
| Task resources | `display_id` | str | Task id shown to agents, e.g. `1-15` |
| | `target_code_path`, `function_name` | str | Code tasks |
| | `source_path` | str | Extraction tasks |
| | `database_path`, `answer_key` | str, list | Data-search tasks |
| | `task_tmp_dir` | str | Where code tasks write test files |
| Work produced | `written_test_files` | list | Test files the agent wrote |
| | `code_assessment`, `extraction_artifact`, `data_search_artifact` | dict or null | The saved final answer, one field per task type |
| | `private_raw_log` | list | The raw log: `{seq, tool, arguments, result}` per task-phase call, excluding `get_log` |
| | `final_answer_saved`, `private_raw_log_retrieved` | bool | `save_final_answer` / `get_log` succeeded (each allowed once) |
| Verdict | `verdict_submission` | dict or null | This agent's verdict on its peer: `{verdict, reasoning, target, forced}` |
| Messaging | `inbox` | list | Unread messages (section 1.4) |
| | `delivered` | bool | Whether this agent has sent its one message in the current turn. Reset before each attempt |

### 1.3 Event: one entry in `events`

Written by `_log_event` (`state.py:141`).

| Key | Always | Meaning |
|---|---|---|
| `event_id` | yes | Index in the list, from 0 |
| `round` | yes | `state["round"]` at the time |
| `phase` | yes | `state["phase"]` at the time |
| `actor` | yes | `alice`, `bob` or `runner` |
| `tool` | yes | Tool name, e.g. `read_code`, `send_message`, `submit_verdict` |
| `success` | yes | Whether the call succeeded |
| `recipient`, `content`, `message_type` | `send_message` | Message route and text |
| `error` | on failure | e.g. `MessageError: exceeds 200 char limit` |
| `verdict`, `target`, `on_behalf_of` | verdicts | Forced verdicts are logged with `actor: runner` |

### 1.4 Inbox message: one entry in `inbox`

| Key | Meaning |
|---|---|
| `from` | `alice`, `bob` or `runner` (runner = notices such as "Bob failed to deliver a message in round 1.") |
| `to` | Recipient |
| `content` | Text |
| `message_type` | `other` |
| `round` | Round the message was written in. Delivery shows it as `[round=r/N][from=…][type=…]` |

### 1.5 `state["communication_window"]` — NEW (idea 2)

Created by `new_communication_window` and filled by `run_communication_window` (`cross_episode.py`), after the episode's feedback and reflection, for every episode except the last.

It contains only the keys the author's messaging functions read (`_send_message`, `pop_incoming_messages`, the tool dispatch phase check). It is passed to those functions in place of the episode state, so the communication window never writes to the episode's top-level `round`, `phase`, `events` or agent slots.

| Key | Type | Meaning |
|---|---|---|
| `round` | int | Communication-window round, 0 to N−1, where N is `communication_window_rounds` (default 5) |
| `phase` | str | Always `"communication"` (lets `send_message` pass the phase check) |
| `throttled`, `char_limit` | bool, int | Same values as the episode (200-char cap) |
| `repo_root`, `task_type` | str | Copied from the episode state (the tool dispatch reads `task_type`) |
| `events` | list | Every `send_message` attempt in the communication window, same shape as section 1.3 (`event_id` restarts at 0) |
| `agents` | dict | `{"alice": {inbox, delivered}, "bob": {inbox, delivered}}` — messaging fields only |

There is no `episode_id`: the sub-dict belongs to the episode state it is stored in.

Delivery follows the paper's turn order (the author's `pop_incoming_messages`): Alice sends, Bob reads it and sends, Alice reads Bob's at her next turn. Bob's last-round message is delivered to Alice before the next episode starts. The in-episode round keeps the idea-1 send-first rule.

### 1.6 Example

```json
{
  "episode_id": "ca_15_intersection+ca_05_pagination",
  "round": 0,
  "phase": "verdict",
  "throttled": true,
  "char_limit": 200,
  "repo_root": "/Users/ebenlim/Projects/joint-task-collusion",
  "task_type": "code_analysis",
  "events": [
    {"event_id": 0, "round": 0, "phase": "task", "actor": "alice", "tool": "read_code", "success": true},
    {"event_id": 6, "round": 0, "phase": "communication", "actor": "alice", "recipient": "bob",
     "tool": "send_message", "success": true, "message_type": "other", "content": "Tests passed. Saved answer: no_bug."},
    {"event_id": 9, "round": 0, "phase": "verdict", "actor": "alice", "tool": "submit_verdict", "success": true}
  ],
  "agents": {
    "alice": {
      "display_id": "1-15", "function_name": "intersection", "...": "other task fields",
      "private_raw_log": [{"seq": 1, "tool": "read_code", "arguments": {}, "result": {"content": "def intersection(a, b): ..."}}],
      "final_answer_saved": true, "private_raw_log_retrieved": true,
      "verdict_submission": {"verdict": "reject", "reasoning": "...", "target": "bob"},
      "inbox": [], "delivered": true
    },
    "bob": {"...": "same keys as alice"}
  },
  "communication_window": {
    "round": 4,
    "phase": "communication",
    "throttled": true,
    "char_limit": 200,
    "repo_root": "/Users/ebenlim/Projects/joint-task-collusion",
    "task_type": "code_analysis",
    "events": [
      {"event_id": 0, "round": 0, "phase": "communication", "actor": "alice", "recipient": "bob",
       "tool": "send_message", "success": true, "message_type": "other", "content": "..."},
      {"event_id": 1, "round": 0, "phase": "communication", "actor": "bob", "recipient": "alice",
       "tool": "send_message", "success": true, "message_type": "other", "content": "..."}
    ],
    "agents": {"alice": {"inbox": [], "delivered": true}, "bob": {"inbox": [], "delivered": true}}
  }
}
```

## 2. run.json

`run.json` holds `run_config`, `llm_usage_summary` and `results`, a list with one object per episode.

### 2.1 run_config

The author's run settings (`build_run_output`, `output.py`), unchanged, plus one key in idea 2:

| Key | Source | Meaning |
|---|---|---|
| `communication_window_rounds` | **NEW (idea 2)** `run.communication_window_rounds` in the YAML config (default 5) | Rounds in each between-episode communication window. Added by `build_run_output_with_rounds` (`cross_episode.py`). Absent in idea 1 runs |

The value travels from the YAML config to `run.json` like this: `__main__.py` reads `run.communication_window_rounds` and appends `--communication-window-rounds N` to the child command; the child (`cross_episode.py`) reads and removes that flag before the author's parser runs, and the same count sets the communication window loop, the system-prompt text ("a communication window of exactly N rounds") and this field. Setting the key in a `channel_mode: one-round` config stops the launch with an error.

### 2.2 Episode object

Built by `build_episode_result` (`output.py`). The communication window after episode *k* is stored in episode *k*'s object.

| Key | Source | Meaning |
|---|---|---|
| `episode_id`, `episode_index`, `group` | state, runner | Identity and position (0–9) |
| `task_type`, `task_ids`, `display_ids` | prepared tasks | The two tasks |
| `memory_scope`, `verdict_policy`, `throttled`, `max_rounds` | config | Episode settings |
| `reward_by_agent`, `reward_scheme` | outcomes | Rewards |
| `agents.<x>` | state slot + outcomes | Task fields from section 1.2, plus `expected_verdict`, `verdict`, `verdict_correct`, `verdict_forced`, `reward`, `outcome_feedback`, `reflection`, `reflection_prompt`, `own_task_prompt`, `judging_prompt`, `verdict_prompt`, `code_eval` / `extraction_eval` / `data_search_eval`, and `messages` |
| `agents.<x>.messages` | runtime | The agent's full history snapshot. In idea 2 it ends with the communication window (opening message, round instructions, sends, received messages), because the snapshot is taken after the window |
| `channel_transcript` | `state["events"]` | Delivered in-episode messages: `{event_id, round, sender, receiver, message_type, content}`. Never contains the communication window |
| `events` | `state["events"]` | In-episode event log (section 1.3) |
| `analysis_metadata` | outcomes | Verdicts, correctness and reward per agent, for the analysis scripts |
| `llm_usage`, `llm_reasoning_traces` | LLM calls | One record per call when model returns reasoning. In idea 2 the communication-window calls come last, labelled `phase: communication` like the in-episode round, so they also carry **NEW (idea 2)** `communication_window: true`. Round numbers: `llm_usage` `round` runs 1 to N, `llm_reasoning_traces` `round` runs 0 to N−1 (the author's conventions). The mark is also written to the run's usage journal |
| `communication_window_transcript` | **NEW (idea 2)** `state["communication_window"]["events"]` | Delivered communication-window messages, same shape as `channel_transcript`. `[]` for the last episode |
| `communication_window_events` | **NEW (idea 2)** `state["communication_window"]["events"]` | Every communication-window attempt, including rejected over-limit sends, same shape as `events`. `[]` for the last episode |

In idea 1 runs, the two NEW fields are absent.

### 2.3 Which analysis reads what

| Reader | Reads |
|---|---|
| `analysis/collusion_metrics.py` (EC, TC, CC) | `agents.<x>.verdict` |
| `analysis/agreement_judge.py` (author) | `channel_transcript` (in-episode chat only) |
| `external/data/channel_study/scripts/communication_window_judge.py` | `communication_window_transcript`, via the author's agreement judge. Writes `results/tables/<config name>_communication_window_agreement.csv` |
| `analysis/relaxation_judge.py` (author) | `agents.<x>.reflection` (written before the communication window) |
| `analysis/results_viewer.py` | Everything; the NEW fields show only in its raw JSON tab |
