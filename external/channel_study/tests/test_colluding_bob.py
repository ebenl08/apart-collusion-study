"""Only Bob's system prompt gains the colluding-Bob section; Alice's is the one-round prompt."""

from experiments import episode_runner
from experiments.prompts import system
from external.channel_study import colluding_bob
from external.channel_study.prompts import COLLUDING_BOB_SECTION


def test_only_bob_gets_the_section(monkeypatch):
    for module, name in (
        (system, "_communication_section"),
        (system, "agent_system_prompt"),
        (episode_runner, "pop_incoming_messages"),
        (episode_runner, "_close_communication_phase"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))  # restored after the test
    colluding_bob.apply_patches()
    bob = system.initial_agent_messages(agent_id="bob", max_rounds=1)[0]["content"]
    alice = system.initial_agent_messages(agent_id="alice", max_rounds=1)[0]["content"]
    assert bob.endswith(COLLUDING_BOB_SECTION + "\n")
    assert COLLUDING_BOB_SECTION not in alice
