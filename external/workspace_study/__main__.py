"""Launch a workspace-study condition: ``python -m external.workspace_study --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for the
study's entry point, chosen by ``run.workspace`` in the config:

    false (default)  external.workspace_study.simultaneous  one-round, simultaneous steps
    files            external.workspace_study.run           plus the shared workspace, as files
    record           external.workspace_study.run           plus the shared workspace, as one JSONL record

The author's launcher ignores config keys it has no flag for, so the key is read here only.
"""

from experiments import cli
from external.channel_study.__main__ import _run_config
from external.workspace_study import run, simultaneous

if __name__ == "__main__":
    surface = _run_config().get("workspace", False)
    if surface is not False and surface not in run.SURFACES:
        raise ValueError(
            f"run.workspace must be false or one of {sorted(run.SURFACES)}, not {surface!r}."
        )
    child = run.CHILD_MODULE if surface else simultaneous.CHILD_MODULE
    extra = [run.WORKSPACE_FLAG, surface] if surface else []
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        child if part == "experiments.runner" else part for part in build(**kw)
    ] + extra
    cli.main()
