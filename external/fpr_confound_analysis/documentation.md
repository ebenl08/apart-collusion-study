# FPR confound analysis: module reference

This package (`external/fpr_confound_analysis/`) runs the FPR confound arms. Research background, results so far and the milestone plan are in `external/data/fpr_confound_analysis/HANDOFF.md`. The repo-wide reference is `documentation.md` at the repo root.

## 1. Question and terms

The paper counts a mutual ACCEPT as collusion, but about 90% of peers are correct, so accepting everything scores well. This study asks whether a verifier still accepts blindly when correct and wrong peer work are balanced 50/50.

| Term | Meaning |
|---|---|
| Verifier | The live LLM under test (Luna, `openrouter/openai/gpt-6-luna`, effort `high`) |
| Producer | A weak model recorded once and replayed (`openrouter/nvidia/nemotron-3-nano-30b-a3b`, effort `medium`), record-extraction tasks only |
| TPR / FPR | Share of correct / wrong producers that the verifier accepts |
| J | TPR − FPR. J = 0 means the verdict carries no information about correctness. |

## 2. What the package adds

The package overlays the author's `experiments/` code and edits none of it. It works by three monkeypatches.

| File | Entry point | What it does |
|---|---|---|
| `__main__.py` | `python -m external.fpr_confound_analysis --config <yaml>` | Runs the author's launcher (`experiments.cli`), swaps the child module for `replay`, and adds the task-cache flags per repeat |
| `replay.py` | child process, one per repeat | The author's runner with `episode_runner._run_task_phase` replaced, so chosen agents get a recorded task instead of doing one |
| `record.py` | `python -m external.fpr_confound_analysis.record <record_peer flags>` | The author's `experiments.record_peer`, with one argument renamed so recording works again |
| `tests/test_replay.py` | `.venv/bin/python -m pytest external/fpr_confound_analysis/tests -q` | 3 tests, no LLM calls |

### 2.1 Replayed own task (`replay.py`)

An agent with a task cache does not do its task. For each episode, `load_replayed_task` (`replay.py:79-105`):
1. finds the recording at `<cache>/<episode_index:04d>-<sha256(episode_id)[:20]>.json`, the same naming as `experiments.controlled.cache_path`;
2. checks it (see below) and raises `ValueError` on any mismatch;
3. replaces the agent's slot (answer, raw log) with the recorded one, keeping the live run's `task_tmp_dir`;
4. appends the recorded task events to the episode's events;
5. appends a `replayed_task` provenance event with the cache path, checksum and recorded model. It is not a `send_message` event, so `channel_transcript` ignores it;
6. appends the recorded task turns to the agent's messages, after the episode's own task prompt.

Step 6 is the difference from the author's controlled Bob: memory from earlier episodes is kept, and the agent sees the recorded work as its own. Communication, verdict, reward, feedback and reflection stay live.

An agent without a task cache does its task live as usual. A controlled Bob is skipped in the task phase, as in the author's code (`replay.py:120-121`).

**Checks on a recording** (`replay.py:51-76`):

| Check | Passes when |
|---|---|
| task | `identity.task.task_id` equals this agent's task in the episode ID |
| resources | SHA-256 of the task's code, source or database file matches the recording |
| episode index | `identity.episode_index` equals the live episode index |
| slot | every recorded event has this agent as `actor` |
| checksum | SHA-256 of the payload equals the stored `sha256` |

### 2.2 Recording fix (`record.py`)

Since `AgentConfig` gained `provider`, `controlled.save_bob` passes `provider=` to `run_reflection_turn`, which names that argument `provider_order`. Every recording crashed after its task phase and saved nothing. `record.py` renames the argument on the way through.

`record_peer` flags: `--model`, `--reasoning-effort`, `--task-sequence-record`, `--repeats`, `--start-index`, `--cache`, `--quiet`. It has no YAML support and always records into Bob's slot.

## 3. Config keys

All keys of the main launcher apply (see `documentation.md` §3). This launcher reads two more `run:` keys:

| Key | Value | Effect |
|---|---|---|
| `alice_task_cache` | directory | Replay Alice's own task from `<dir>/repNNN` |
| `bob_task_cache` | directory | Replay Bob's own task from `<dir>/repNNN`. Needs a live Bob; with `bob.model: controlled` the child raises an error (`replay.py:150-151`). |

Repeat N reads the `rep<N:03d>` subfolder, as with `controlled_bob_cache`.

These keys only work through `python -m external.fpr_confound_analysis`. The author's launcher (`python -m experiments`) silently ignores them, so the agents would do their tasks live.

## 4. Arms and configs

All arms use the same 15 paired sequences, 5 rounds of 200 characters, verdict policy `raw-only`, full-history memory, reflection on, and `judge: false` (judges run during analysis).

| Config | Alice | Bob | Reward scope | Evidence Alice gets | Launcher |
|---|---|---|---|---|---|
| `luna-pilot.yaml`, `luna-main.yaml` | Live Luna, does her task live | Controlled (replayed producer) | `verifier` | `raw-prefix` | `python -m experiments` |
| `a0-summary.yaml` | Live Luna, task replayed | Controlled (replayed producer) | `verifier` | Recorded 5-message `summary` | this package |
| `a1-live-verifier.yaml` | Live Luna, task replayed | Live Luna, task replayed | `verifier` (max 10 each) | Bob's own live messages | this package |
| `a2-live-shared.yaml` | Live Luna, task replayed | Live Luna, task replayed | `shared` (max 20 each) | Bob's own live messages | this package |
| `a1-smoke.yaml` | as A1, 1 repeat | as A1 | `verifier` | as A1 | this package |

What the comparisons measure:
- **A0** is the baseline: Luna's FPR with informative evidence and no live peer.
- **A1 − A0** is the effect of a live, reactive peer.
- **A2 − A1** is the effect of a shared stake in the peer's verdict.

A0, A1 and A2 run 15 repeats with `parallel: 5` and write to `external/data/fpr_confound_analysis/results/<arm>/`.

`luna-main` is not a valid baseline. Its `raw-prefix` evidence was only the start of the source document and never contained the producer's answer, so it carried no information about correctness (HANDOFF §5).

## 5. Data pipeline

Scripts are in `external/data/fpr_confound_analysis/scripts/` and run from the repo root. Outputs go to `external/data/fpr_confound_analysis/results/`.

| Step | Command | Output |
|---|---|---|
| 1. Pool manifests | `make_pool.py [reps] [seed] [start]` | `pool-extraction/rep*.json` (extraction-only pairs) |
| 2. Record producer | `python -m external.fpr_confound_analysis.record --model … --cache …` | `producer-nemotron-extraction/` |
| 3. Grade | `grade_producer.py <cache dirs>` | Fail rate by family and failure type |
| 4. Balanced Bob side | `build_balanced.py [sequences] [seed] [tag]` | `balanced-seqs<tag>/`, `balanced-cache<tag>/`, `balanced-labels<tag>.csv` (5 right, 5 wrong per sequence) |
| 5. Paired sequences | `build_paired.py [seed]` | `paired-seqs-15/`, `paired-cache-15/{alice,bob}/repNNN/`, `paired-labels-15.csv` |
| 6. Run arms | `python -m external.fpr_confound_analysis --config …/a0-summary.yaml` (and a1, a2) | `results/<arm>/…/rep<N>/run.json` |
| 7. Confusion tables | `verifier_confusion.py [run_dir] [name]` | `<name>-episodes.csv`, `<name>-summary.csv` |

**How `build_paired.py` builds a sequence:**
- It keeps each `balanced-seqs-15` Bob sequence unchanged.
- It gives Alice 10 recordings not used by `balanced-seqs-15`, each used at most once: 5 right and 5 wrong, crossed with Bob's labels (2 or 3 of Bob's correct positions get a correct Alice, alternating by sequence). No task repeats within a sequence.
- All recordings are Bob-slot recordings. An Alice copy gets its events' `actor` set to `alice` and its checksum recomputed.
- Both sides get `identity.episode_index` set to the new position and the filename re-keyed on the new episode ID `<alice task>+<bob task>`.

## 6. Status and known gaps (2026-10-09)

- The package code and the four `a*` configs are untracked in git.
- `paired-seqs-15/` and `paired-cache-15/` do not exist yet, so the A0, A1 and A2 configs cannot run until steps 2 to 5 are done (HANDOFF milestones M2 and M3).
- `verifier_confusion.py` globs `*/*/run.json` and parses `_rep` from the folder name, which matches only the old output layout. It needs updating before it can read runs in the current `rep<N>/` layout.
- `--dry-run` on a config validates it without spending anything.
