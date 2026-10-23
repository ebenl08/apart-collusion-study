"""Launch a workspace-study condition: ``python -m external.workspace_study --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for the
study's entry point, chosen by ``run.workspace`` in the config:

    false (default)  external.workspace_study.simultaneous  one-round, simultaneous steps
    files            external.workspace_study.run           plus the shared workspace, as files
    record           external.workspace_study.run           plus the shared workspace, as one JSONL record

With ``workspace: record``, two more keys, each false by default:

    read_notes_first        the task phase starts with a step telling the agent to call read_notes
    allow_reflection_notes  reflections are saved to the record, and the prompt says so
    record_new_rows_only    read and write return only rows not yet returned to the caller

The author's launcher ignores config keys it has no flag for, so these are read here only.
"""

from experiments import cli
from external.channel_study.__main__ import _run_config
from external.workspace_study import run, simultaneous

if __name__ == "__main__":
    settings = _run_config()
    surface = settings.get("workspace", False)
    if surface is not False and surface not in run.SURFACES:
        raise ValueError(
            f"run.workspace must be false or one of {sorted(run.SURFACES)}, not {surface!r}."
        )
    child = run.CHILD_MODULE if surface else simultaneous.CHILD_MODULE
    extra = [run.WORKSPACE_FLAG, surface] if surface else []
    for key, flag in (
        ("read_notes_first", run.READ_FIRST_FLAG),
        ("allow_reflection_notes", run.REFLECTION_NOTES_FLAG),
        ("record_new_rows_only", run.NEW_ROWS_FLAG),
    ):
        value = settings.get(key, False)
        if type(value) is not bool:
            raise ValueError(f"run.{key} must be true or false, not {value!r}.")
        if value and surface != "record":
            raise ValueError(f"run.{key} is set, but run.workspace is not record.")
        if value:
            extra.append(flag)
    nudge = settings.get("inject_nudge")
    if nudge:
        if surface != "record":
            raise ValueError("run.inject_nudge is set, but run.workspace is not record.")
        extra += [
            run.INJECT_NUDGE_FLAG,
            str(nudge),
            run.INJECT_EPISODE_FLAG,
            str(settings.get("inject_episode", 5)),
        ]
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        child if part == "experiments.runner" else part for part in build(**kw)
    ] + extra
    cli.main()
