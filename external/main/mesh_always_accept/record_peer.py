"""The author's record_peer, with one argument renamed so it runs.

The author's controlled.save_bob passes AgentConfig's ``provider`` to run_reflection_turn, which
now takes ``provider_order`` (commit cca7bdb). Used to record Bob's tasks for reps 16 to 25 into
data/peer-cache-gemini; no author file is edited.

    .venv/bin/python -m external.main.mesh_always_accept.record_peer \
        --model openrouter/google/gemini-3.1-flash-lite --reasoning-effort high \
        --task-sequence-record task/task_sequences_50x10 --start-index 16 --repeats 10 \
        --cache external/data/main/results/mesh_always_accept/data/peer-cache-gemini --quiet
"""

import sys

from experiments import agents, controlled, record_peer

_run_reflection_turn = controlled.run_reflection_turn


def run_reflection_turn(*, provider="", **kwargs):
    return _run_reflection_turn(provider_order=provider, **kwargs)


controlled.run_reflection_turn = run_reflection_turn

# Rep 19 episode 6: Gemini answered the message-writing step with finish_reason "tool_calls" and
# no content 27 times in a row (the author discards tool calls there, so each reply counts as
# empty). With --no-tools the step sends tool_choice "none", so the model can only write text.
# Same model, effort and prompt; used for the stuck rep only.
if "--no-tools" in sys.argv:
    sys.argv.remove("--no-tools")
    _complete_with_retries = agents._complete_with_retries

    def complete_text_only(*, completion_kwargs, accept_tool_calls=True, **kwargs):
        if not accept_tool_calls:
            completion_kwargs = {**completion_kwargs, "tool_choice": "none"}
        return _complete_with_retries(completion_kwargs=completion_kwargs, accept_tool_calls=accept_tool_calls, **kwargs)

    agents._complete_with_retries = complete_text_only

if __name__ == "__main__":
    record_peer.main()
