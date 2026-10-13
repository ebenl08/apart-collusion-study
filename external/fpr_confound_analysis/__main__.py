"""Launch an FPR-confound arm: ``python -m external.fpr_confound_analysis --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for
``external.fpr_confound_analysis.replay``. Two extra ``run:`` keys, read here only
(the author's launcher ignores keys it has no flag for):

    alice_task_cache: <dir>   replay Alice's own task from <dir>/repNNN
    bob_task_cache:   <dir>   replay Bob's own task from <dir>/repNNN (needs a live Bob)

Each repeat N gets the rep<N:03d> subfolder, as with controlled_bob_cache.
"""

import argparse
from pathlib import Path

import yaml

from experiments import cli
from external.fpr_confound_analysis.replay import CHILD_MODULE, TASK_CACHE_KEYS


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


if __name__ == "__main__":
    settings = _run_config()
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        CHILD_MODULE if part == "experiments.runner" else part for part in build(**kw)
    ] + task_cache_flags(settings, kw["run_index"])
    cli.main()
