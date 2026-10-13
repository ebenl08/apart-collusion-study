"""Record producer episodes: the author's ``experiments.record_peer``, made to run again.

    python -m external.fpr_confound_analysis.record <record_peer flags>

Since the author's AgentConfig gained ``provider``, ``controlled.save_bob`` passes it to
``run_reflection_turn``, which names that argument ``provider_order``, so every
recording crashes after its task phase and saves nothing. This renames the argument on
the way through. Nothing in the author's files is edited.
"""

from experiments import controlled, record_peer

_author_run_reflection_turn = controlled.run_reflection_turn


def run_reflection_turn(*, provider="", **kwargs):
    return _author_run_reflection_turn(provider_order=provider, **kwargs)


if __name__ == "__main__":
    controlled.run_reflection_turn = run_reflection_turn
    record_peer.main()
