"""Launch an arm: ``python -m external.main.mesh_always_accept --config ...``.

Copied from ``external.fpr_confound_analysis.__main__`` so this experiment folder is closed:
it imports nothing from other ``external/`` experiments, only the author's ``experiments``.

Reuses the author's launcher (experiments.cli) and swaps its child process for
``replay`` in this folder. Two extra ``run:`` keys, read here only
(the author's launcher ignores keys it has no flag for):

    alice_task_cache: <dir>   replay Alice's own task from <dir>/repNNN
    bob_task_cache:   <dir>   replay Bob's own task from <dir>/repNNN (needs a live Bob)

Each repeat N gets the rep<N:03d> subfolder, as with controlled_bob_cache.

Two more optional keys pick another child and pass it extra flags:

    child_module: <dotted module>   instead of the replay child (e.g. ...persuader)
    child_args:   [--flag, value]   appended to the child's command line
"""

import argparse
from pathlib import Path

import yaml

from experiments import cli
from external.main.mesh_always_accept.replay import CHILD_MODULE, TASK_CACHE_KEYS


def _run_config() -> dict:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    config = pre.parse_known_args()[0].config
    document = yaml.safe_load(Path(config).read_text(encoding="utf-8")) if config else {}
    return (document or {}).get("run") or {}


def task_cache_flags(settings: dict, run_index: int) -> list[str]:
    """The child's task-cache flags for one repeat."""
    flags = []
    for key in TASK_CACHE_KEYS:
        if settings.get(key):
            flags += ["--" + key.replace("_", "-"), str(Path(settings[key]) / f"rep{run_index:03d}")]
    return flags


# Copied from external.fpr_confound_analysis.bob_prompt.
def allow_one_round(validate):
    """The author's check demands 5 rounds (or 0) for a controlled Bob; accept 1 for this study."""

    def validate_run_args(args) -> None:
        if getattr(args, "bob_model", "") == "controlled" and args.max_rounds == 1:
            args.max_rounds = 5
            try:
                validate(args)
            finally:
                args.max_rounds = 1
        else:
            validate(args)

    return validate_run_args


if __name__ == "__main__":
    settings = _run_config()
    build = cli._build_runner_command
    child = settings.get("child_module", CHILD_MODULE)
    if "child_module" in settings:
        cli.validate_run_args = allow_one_round(cli.validate_run_args)
    child_args = [str(a) for a in settings.get("child_args", [])]
    cli._build_runner_command = lambda **kw: [
        child if part == "experiments.runner" else part for part in build(**kw)
    ] + task_cache_flags(settings, kw["run_index"]) + child_args
    cli.main()
