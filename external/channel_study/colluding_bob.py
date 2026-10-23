"""Child entry point: the one-round channel, with Bob (only) told in his system prompt to accept
summaries. Alice's prompt, the tools and everything else are the one-round condition's.

Nothing in the author's files is edited. Bob's section is appended to the author's
``agent_system_prompt``; ``initial_agent_messages`` looks that name up at call time.
"""

from experiments import runner
from experiments.prompts import system
from external.channel_study import run
from external.channel_study.prompts import COLLUDING_BOB_SECTION

CHILD_MODULE = "external.channel_study.colluding_bob"

_author_agent_system_prompt = system.agent_system_prompt


def agent_system_prompt_with_colluding_bob(*args, **kwargs) -> str:
    text = _author_agent_system_prompt(*args, **kwargs)
    agent_id = kwargs.get("agent_id", args[0] if args else None)
    return f"{text}\n{COLLUDING_BOB_SECTION}\n" if agent_id == "bob" else text


def apply_patches() -> None:
    run.apply_patches()
    system.agent_system_prompt = agent_system_prompt_with_colluding_bob


if __name__ == "__main__":
    apply_patches()
    runner.main()
