"""Child entry point: one-round, simultaneous steps, plus the shared workspace.

Both agents get workspace tools in the task phase, all acting on one folder per
trajectory (``<run dir>/workspace``, see workspace.py). The prompt never says the folder
is shared and never mentions the peer in connection with it. The surface is chosen by
``--workspace``, which the launcher passes from ``run.workspace`` in the config:

    files   write_file, list_files, read_file on plain files
    record  write_note and read_notes on one append-only JSONL record; both results
            carry every note the caller can see

Nothing in the author's files is edited. Patches, on top of simultaneous.py's:

  * ``tool_schemas.TASK_TOOL_NAMES`` and ``_tool_schemas_by_name``: the surface's tools,
    offered in the task phase of every task type, before save_final_answer;
  * ``dispatch.TOOL_HANDLERS``: their handlers. Being task tools, they obey the
    author's gates: none after save_final_answer, none outside the task phase, and
    their calls appear in the caller's raw log;
  * ``system._episodes_section`` and ``system._task_section``: prompts.py;
  * ``simultaneous.on_step_start``: fixes what reads serve for the step;
  * ``episode_runner.build_episode_result``: adds ``workspace_events`` (this episode's
    journal rows) and the workspace as it stands at episode end, under
    ``workspace_files`` or ``workspace_record``;
  * ``runner._create_output_path``: opens the workspace beside run.json.
"""

import argparse

from experiments import episode_runner, runner, tool_schemas
from experiments.prompts import system
from experiments.protocol import dispatch
from experiments.protocol.state import _log_event
from external.workspace_study import prompts, simultaneous
from external.workspace_study.workspace import Record, Workspace

CHILD_MODULE = "external.workspace_study.run"
WORKSPACE_FLAG = "--workspace"

_author_tool_schemas_by_name = tool_schemas._tool_schemas_by_name
_author_build_result = episode_runner.build_episode_result
_author_create_output_path = runner._create_output_path

# Set once per run: the surface (apply_patches) and its store
# (create_output_path_and_workspace).
_run = {"surface": None, "workspace": None}


def _function_schema(name, description, properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                **({} if properties else {"additionalProperties": False}),
            },
        },
    }


def _handler(tool_name, operation):
    def handle(state, actor, arguments):
        result = operation(_run["workspace"], actor, arguments)
        _log_event(
            state,
            {
                "actor": actor,
                "tool": tool_name,
                "success": result["success"],
                **({"error": result["error"]} if not result["success"] else {}),
            },
        )
        return result

    return handle


def _file_schemas():
    filename = {"type": "string", "description": prompts.FILENAME_DESCRIPTION}
    content = {"type": "string", "description": prompts.CONTENT_DESCRIPTION}
    return {
        "write_file": _function_schema(
            "write_file", prompts.WRITE_FILE_DESCRIPTION, {"filename": filename, "content": content}
        ),
        "list_files": _function_schema("list_files", prompts.LIST_FILES_DESCRIPTION, {}),
        "read_file": _function_schema(
            "read_file", prompts.READ_FILE_DESCRIPTION, {"filename": filename}
        ),
    }


def _record_schemas():
    content = {"type": "string", "description": prompts.NOTE_CONTENT_DESCRIPTION}
    return {
        "write_note": _function_schema(
            "write_note", prompts.WRITE_NOTE_DESCRIPTION, {"content": content}
        ),
        "read_notes": _function_schema("read_notes", prompts.READ_NOTES_DESCRIPTION, {}),
    }


# Per surface: the store, the task section, the tool schemas (in offered order) and
# their handlers.
SURFACES = {
    "files": {
        "store": Workspace,
        "task_section": prompts.task_section,
        "schemas": _file_schemas,
        "handlers": {
            "write_file": _handler(
                "write_file",
                lambda workspace, actor, arguments: workspace.write(
                    actor, str(arguments.get("filename", "")), str(arguments.get("content", ""))
                ),
            ),
            "list_files": _handler(
                "list_files", lambda workspace, actor, arguments: workspace.list(actor)
            ),
            "read_file": _handler(
                "read_file",
                lambda workspace, actor, arguments: workspace.read(
                    actor, str(arguments.get("filename", ""))
                ),
            ),
        },
    },
    "record": {
        "store": Record,
        "task_section": prompts.task_section_record,
        "schemas": _record_schemas,
        "handlers": {
            "write_note": _handler(
                "write_note",
                lambda workspace, actor, arguments: workspace.write(
                    actor, str(arguments.get("content", ""))
                ),
            ),
            "read_notes": _handler(
                "read_notes", lambda workspace, actor, arguments: workspace.read(actor)
            ),
        },
    },
}


def tool_schemas_with_workspace(peer):
    return {**_author_tool_schemas_by_name(peer), **_run["surface"]["schemas"]()}


def begin_workspace_step(episode_index, step):
    _run["workspace"].begin_step(episode_index, step)


def build_result_with_workspace(**kwargs):
    """Author's episode result, plus this episode's workspace journal and the workspace."""
    result = _author_build_result(**kwargs)
    workspace = _run["workspace"]
    result["workspace_events"] = workspace.journal_rows(kwargs["config"].episode_index)
    result[workspace.RESULT_KEY] = workspace.contents()
    return result


def create_output_path_and_workspace(args, repo_root):
    output_path = _author_create_output_path(args, repo_root)
    _run["workspace"] = _run["surface"]["store"](output_path.parent / "workspace")
    return output_path


def take_workspace_flag(argv: list[str]) -> str:
    """Read and remove --workspace, which the author's parser doesn't know."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument(WORKSPACE_FLAG, choices=sorted(SURFACES), required=True)
    known, rest = pre.parse_known_args(argv)
    argv[:] = rest
    return known.workspace


def apply_patches(surface: str) -> None:
    simultaneous.apply_patches()
    _run["surface"] = SURFACES[surface]
    tool_names = tuple(_run["surface"]["handlers"])
    for task_type, names in tool_schemas.TASK_TOOL_NAMES.items():
        cut = names.index("save_final_answer")
        tool_schemas.TASK_TOOL_NAMES[task_type] = names[:cut] + tool_names + names[cut:]
    tool_schemas._tool_schemas_by_name = tool_schemas_with_workspace
    dispatch.TOOL_HANDLERS.update(_run["surface"]["handlers"])
    system._episodes_section = prompts.episodes_section
    system._task_section = _run["surface"]["task_section"]
    simultaneous.on_step_start = begin_workspace_step
    episode_runner.build_episode_result = build_result_with_workspace
    runner._create_output_path = create_output_path_and_workspace


if __name__ == "__main__":
    import sys

    apply_patches(take_workspace_flag(sys.argv))
    runner.main()
