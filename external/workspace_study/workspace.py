"""The shared workspace: one folder per trajectory that both agents read and write.

Two surfaces, one per run: ``Workspace`` (files) and ``Record`` (one append-only JSONL
file of notes, described on the class). Both keep the same journal and the same step
rule. The rest of this text describes the file surface.

On disk under ``root``:

    files/         the agents' files, flat, named by the agents plus a suffix
    owners.json    filename -> the agent that created it
    journal.jsonl  one row per operation, for analysis; agents never see it
    .lock          flock target

Rules:

  * Every saved name gets a four-digit suffix before its extension: the writer's
    position in AGENT_IDS (Alice 0, Bob 1), then the 1-based episode number in three
    digits. ``notes.txt`` from Alice in episode 1 is ``notes_0001.txt``; from Bob,
    ``notes_1001.txt``. So the two agents can never write the same file and no write
    is ever refused for its name. Writing the same name again in the same episode
    replaces the writer's own file.
  * Reads and listings serve the snapshot taken by ``begin_step``, plus the caller's
    own files as they are now. So within one step neither agent sees what the other
    writes in that step, whichever thread runs first.
  * Every operation holds an exclusive flock, so concurrent writes, owner updates and
    journal rows cannot be lost or interleaved.
"""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from experiments.protocol.errors import error_string
from experiments.protocol.state import AGENT_IDS


class _Store:
    """What both workspace surfaces share: the folder, the lock, the journal, the step."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._journal_path = self.root / "journal.jsonl"
        self._lock_path = self.root / ".lock"
        with self._locked():
            self._load()
            # ponytail: seq is counted in this process; one runner process per workspace.
            self._seq = (
                len(self._journal_path.read_text(encoding="utf-8").splitlines())
                if self._journal_path.exists()
                else 0
            )
            self._episode: int | None = None
            self._step: int | None = None
            self._snapshot = self._read_all()

    @contextmanager
    def _locked(self):
        # A fresh descriptor per operation, so two threads block each other.
        with open(self._lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _journal(self, *, actor: str, op: str, result: dict[str, Any], **fields: Any) -> None:
        row = {
            "seq": self._seq,
            "episode": self._episode,
            "step": self._step,
            "actor": actor,
            "op": op,
            "requested": None,
            "file": None,
            "owner": None,
            "content": None,
            "shown": [],
            **fields,
            "success": result["success"],
            "error": result.get("error"),
        }
        self._seq += 1
        with open(self._journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def journal_rows(self, episode: int) -> list[dict[str, Any]]:
        """This episode's journal rows, for the episode result."""
        with self._locked():
            if not self._journal_path.exists():
                return []
            lines = self._journal_path.read_text(encoding="utf-8").splitlines()
            return [row for row in map(json.loads, lines) if row["episode"] == episode]

    def begin_step(self, episode: int, step: int) -> None:
        """Fix what reads and listings serve until the next call."""
        with self._locked():
            self._episode, self._step = episode, step
            self._snapshot = self._read_all()


class Workspace(_Store):
    """The file surface: write_file, list_files, read_file."""

    RESULT_KEY = "workspace_files"

    def _load(self) -> None:
        self.files = self.root / "files"
        self.files.mkdir(parents=True, exist_ok=True)
        self._owners_path = self.root / "owners.json"
        self._owners: dict[str, str] = (
            json.loads(self._owners_path.read_text(encoding="utf-8"))
            if self._owners_path.exists()
            else {}
        )

    def _read_all(self) -> dict[str, str]:
        return {
            name: (self.files / name).read_text(encoding="utf-8")
            for name in sorted(self._owners)
        }

    def _visible(self, actor: str) -> dict[str, str]:
        """What ``actor`` can see now: the step snapshot, with its own files current."""
        visible = dict(self._snapshot)
        for name, owner in self._owners.items():
            if owner == actor:
                visible[name] = (self.files / name).read_text(encoding="utf-8")
        return visible

    def _listing(self, actor: str) -> list[dict[str, Any]]:
        return [
            {"name": name, "size": len(content)}
            for name, content in sorted(self._visible(actor).items())
        ]

    @staticmethod
    def _name_error(name: str) -> str | None:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return error_string(
                "InvalidArgumentError", "name must be a plain filename with no directory part"
            )
        return None

    def _saved_name(self, actor: str, name: str) -> str:
        """``name`` with the writer-and-episode suffix before its extension."""
        path = Path(name)
        episode_number = (self._episode or 0) + 1
        return f"{path.stem}_{AGENT_IDS.index(actor)}{episode_number:03d}{path.suffix}"

    def contents(self) -> dict[str, dict[str, str]]:
        """Every file as it is now, with its creator, for the episode result."""
        with self._locked():
            return {
                name: {"owner": self._owners[name], "content": content}
                for name, content in self._read_all().items()
            }

    def write(self, actor: str, name: str, content: str) -> dict[str, Any]:
        with self._locked():
            error = self._name_error(name)
            if error is not None:
                result: dict[str, Any] = {"success": False, "error": error}
                self._journal(
                    actor=actor, op="write", result=result, requested=name, content=content
                )
                return result
            saved = self._saved_name(actor, name)
            (self.files / saved).write_text(content, encoding="utf-8")
            if saved not in self._owners:
                self._owners[saved] = actor
                self._owners_path.write_text(
                    json.dumps(self._owners, ensure_ascii=False, indent=1), encoding="utf-8"
                )
            result = {"success": True, "saved_as": saved, "files": self._listing(actor)}
            self._journal(
                actor=actor,
                op="write",
                result=result,
                requested=name,
                file=saved,
                owner=actor,
                content=content,
                shown=[entry["name"] for entry in result["files"]],
            )
            return result

    def read(self, actor: str, name: str) -> dict[str, Any]:
        with self._locked():
            error = self._name_error(name)
            visible = self._visible(actor)
            if error is None and name not in visible:
                error = error_string("TaskFileError", "no file with this name")
            if error is not None:
                result: dict[str, Any] = {"success": False, "error": error}
                self._journal(actor=actor, op="read", result=result, file=name)
                return result
            result = {"success": True, "content": visible[name]}
            self._journal(
                actor=actor,
                op="read",
                result=result,
                file=name,
                owner=self._owners[name],
                content=visible[name],
                shown=[name],
            )
            return result

    def list(self, actor: str) -> dict[str, Any]:
        with self._locked():
            result = {"success": True, "files": self._listing(actor)}
            self._journal(
                actor=actor,
                op="list",
                result=result,
                shown=[entry["name"] for entry in result["files"]],
            )
            return result


class Record(_Store):
    """The record surface: one append-only JSONL file of notes; write_note and read_notes.

    A row is never edited or removed, so nothing can be overwritten; the lock only keeps
    two appends in the same step from interleaving. Agents see each row as
    ``{"episode", "agent", "type", "content"}``: the 1-based episode, the writer's
    position in AGENT_IDS (Alice 0, Bob 1), and ``note`` or ``reflection``. ``id`` and
    ``step`` stay on disk for analysis; shown to agents, an id would have gaps wherever
    the other agent wrote in the same step.

    A ``note`` is written by an agent with write_note. A ``reflection`` is the agent's
    end-of-episode reflection, appended by the runner when the run saves reflections
    to the workspace (``add_reflection``).
    """

    RESULT_KEY = "workspace_record"

    def __init__(self, root: Path | str, new_rows_only: bool = False) -> None:
        # With new_rows_only, read and write return only rows not yet returned to the
        # caller, so each row reaches each agent once. The cursor is a set of row ids,
        # not a position: a row hidden by the step rule is still new when it appears.
        # ponytail: the ids live in memory; one runner process per trajectory.
        self.new_rows_only = new_rows_only
        self._returned_ids: dict[int, set[int]] = {i: set() for i in range(len(AGENT_IDS))}
        super().__init__(root)

    def _load(self) -> None:
        self._record_path = self.root / "record.jsonl"

    def _to_return(self, agent: int) -> list[dict[str, Any]]:
        """The rows a read or write hands back: all visible, or only the not-yet-returned."""
        rows = self._visible(agent)
        if self.new_rows_only:
            rows = [r for r in rows if r["id"] not in self._returned_ids[agent]]
        self._returned_ids[agent].update(r["id"] for r in rows)
        return rows

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._record_path.exists():
            return []
        lines = self._record_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def _visible(self, agent: int) -> list[dict[str, Any]]:
        """The step snapshot plus the caller's own rows since, in a timing-free order."""
        seen = len(self._snapshot)
        rows = self._snapshot + [r for r in self._read_all()[seen:] if r["agent"] == agent]
        # An episode's reflections come after its notes, whatever step the notes were in.
        return sorted(
            rows,
            key=lambda r: (r["episode"], r["type"] == "reflection", r["step"], r["agent"], r["id"]),
        )

    def _append(self, actor: str, content: str, row_type: str) -> dict[str, Any]:
        row = {
            "id": len(self._read_all()),
            "episode": (self._episode or 0) + 1,
            "step": self._step or 0,
            "agent": AGENT_IDS.index(actor),
            "type": row_type,
            "content": content,
        }
        with open(self._record_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def add_reflection(self, actor: str, content: str) -> None:
        """Append an agent's end-of-episode reflection. Called by the runner, not by a tool."""
        with self._locked():
            row = self._append(actor, content, "reflection")
            self._journal(
                actor=actor,
                op="reflection",
                result={"success": True},
                file=row["id"],
                owner=actor,
                content=content,
            )

    def write(self, actor: str, content: str) -> dict[str, Any]:
        with self._locked():
            if not content.strip():
                result: dict[str, Any] = {
                    "success": False,
                    "error": error_string("InvalidArgumentError", "content must not be empty"),
                }
                self._journal(actor=actor, op="write", result=result, content=content)
                return result
            agent = AGENT_IDS.index(actor)
            row = self._append(actor, content, "note")
            visible = self._to_return(agent)
            result = {"success": True, "notes": self._shown(visible)}
            self._journal(
                actor=actor,
                op="write",
                result=result,
                file=row["id"],
                owner=actor,
                content=content,
                shown=[r["id"] for r in visible],
            )
            return result

    @staticmethod
    def _shown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: r[k] for k in ("episode", "agent", "type", "content")} for r in rows]

    def read(self, actor: str) -> dict[str, Any]:
        with self._locked():
            visible = self._to_return(AGENT_IDS.index(actor))
            result = {"success": True, "notes": self._shown(visible)}
            self._journal(actor=actor, op="read", result=result, shown=[r["id"] for r in visible])
            return result

    def contents(self) -> list[dict[str, Any]]:
        """Every row as stored, for the episode result."""
        with self._locked():
            return self._read_all()
