# Docs index

Experiment logs and analyses. Each study has one `<study>.md` (list of runs with EC/TC/CC and a TLDR) and, where a write-up exists, an analysis under `<study>/<sub_experiment>_analysis.md`. Data, plots and scripts stay in `external/data/<study>/`.

| Study | Log | Analyses | Last updated | TLDR |
| --- | --- | --- | --- | --- |
| Channel study | [channel_study.md](channel_study.md) | [no reward / no verdict review](channel_study/noreward-noreview_analysis.md) | 2026-10-19 | Without reward, accepting still happens when the verdict review is on; with the review off, DeepSeek (10 trajectories) never accepts, even with a colluding Bob. Luna and GLM runs in progress. |
| Workspace study | [workspace_study.md](workspace_study.md) | (earlier results: `external/data/workspace_study/ANALYSIS.md`) | 2026-10-19 | A peer's note inviting acceptance was read and refused as "social engineering". |

The FPR confound study keeps its analysis and handoff in `external/data/fpr_confound_analysis/` and is not in this index yet.
