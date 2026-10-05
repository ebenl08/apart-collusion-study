"""Launch a channel-study condition: ``python -m external.channel_study --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for the
study's entry point, chosen by ``run.channel_mode`` in the config:

    one-round      external.channel_study.run            (idea 1, the default)
    cross-episode  external.channel_study.cross_episode  (idea 2)

Idea 2 also reads ``run.communication_window_rounds`` (default 5) and passes it to the
child as ``--communication-window-rounds``. Setting it in a one-round config is an error.

The author's launcher ignores config keys it has no flag for, so both keys are read
here only.
"""

import argparse
from pathlib import Path

import yaml

from experiments import cli
from external.channel_study import cross_episode, run

CHILD_MODULES = {"one-round": run.CHILD_MODULE, "cross-episode": cross_episode.CHILD_MODULE}


def _run_config() -> dict:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    config = pre.parse_known_args()[0].config
    document = yaml.safe_load(Path(config).read_text(encoding="utf-8")) if config else {}
    return (document or {}).get("run") or {}


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
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        child if part == "experiments.runner" else part for part in build(**kw)
    ] + extra
    cli.main()
