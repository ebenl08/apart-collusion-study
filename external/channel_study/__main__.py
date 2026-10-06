"""Launch a channel-study condition: ``python -m external.channel_study --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for the
study's entry point, chosen by ``run.channel_mode`` in the config:

    one-round      external.channel_study.run            (idea 1, the default)
    cross-episode  external.channel_study.cross_episode  (idea 2)

Idea 2 also reads ``run.communication_window_rounds`` (default 5) and passes it to the
child as ``--communication-window-rounds``. Setting it in a one-round config is an error.
When the author's judges run, idea 2 then also runs the agreement judge on the
communication windows (external/data/channel_study/scripts/communication_window_judge.py).

The author's launcher ignores config keys it has no flag for, so both keys are read
here only.
"""

import argparse
import subprocess
import sys
from functools import partial
from pathlib import Path

import yaml

from experiments import cli
from external.channel_study import cross_episode, run

CHILD_MODULES = {"one-round": run.CHILD_MODULE, "cross-episode": cross_episode.CHILD_MODULE}
COMMUNICATION_WINDOW_JUDGE = "external/data/channel_study/scripts/communication_window_judge.py"


def _run_config() -> dict:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    config = pre.parse_known_args()[0].config
    document = yaml.safe_load(Path(config).read_text(encoding="utf-8")) if config else {}
    return (document or {}).get("run") or {}


def _run_judges_with_communication_window(author_run_judges, config: str, repo_root: Path) -> None:
    """The author's judges, then the agreement judge on the communication windows."""
    author_run_judges(config, repo_root)
    command = [sys.executable, COMMUNICATION_WINDOW_JUDGE, "--config", config]
    print("$ " + " ".join(command), flush=True)
    if subprocess.run(command, cwd=repo_root, check=False).returncode:
        print(f"communication window judge failed; rerun it with --config {config}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    settings = _run_config()
    mode = settings.get("channel_mode", "one-round")
    if mode not in CHILD_MODULES:
        raise ValueError(f"channel_mode must be one of {sorted(CHILD_MODULES)}, not {mode!r}.")
    child = CHILD_MODULES[mode]
    extra = []
    if "communication_window_rounds" in settings:
        if mode != "cross-episode":
            raise ValueError(
                "communication_window_rounds is set, but channel_mode is not "
                "cross-episode, so there is no communication window."
            )
        rounds = settings["communication_window_rounds"]
        if type(rounds) is not int or rounds < 1:
            raise ValueError(f"communication_window_rounds must be an integer >= 1, not {rounds!r}.")
        extra = [cross_episode.ROUNDS_FLAG, str(rounds)]
    if mode == "cross-episode":
        cli._run_judges = partial(_run_judges_with_communication_window, cli._run_judges)
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        child if part == "experiments.runner" else part for part in build(**kw)
    ] + extra
    cli.main()
