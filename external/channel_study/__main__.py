"""Launch a channel-study condition: ``python -m external.channel_study --config ...``.

Reuses the author's launcher (experiments.cli) and swaps its child process for
``external.channel_study.run`` so the study's patches apply in every run.
"""

from experiments import cli
from external.channel_study.run import CHILD_MODULE

if __name__ == "__main__":
    build = cli._build_runner_command
    cli._build_runner_command = lambda **kw: [
        CHILD_MODULE if part == "experiments.runner" else part for part in build(**kw)
    ]
    cli.main()
