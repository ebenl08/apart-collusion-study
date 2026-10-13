"""The shared workspace store: lock, name suffix, step visibility, journal, persistence."""

import json
import threading

from external.workspace_study.workspace import Workspace


def _journal(workspace):
    lines = (workspace.root / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _names(result):
    return [entry["name"] for entry in result["files"]]


def test_concurrent_writers_lose_nothing(tmp_path):
    workspace = Workspace(tmp_path)

    def worker(actor):
        for index in range(50):
            assert workspace.write(actor, f"file{index}.md", f"{actor} {index}")["success"]
            assert workspace.list(actor)["success"]

    threads = [threading.Thread(target=worker, args=(actor,)) for actor in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Both agents asked for the same 50 names; each kept its own 50 files.
    for digit, actor in enumerate(("alice", "bob")):
        for index in range(50):
            assert (workspace.files / f"file{index}_{digit}001.md").read_text() == f"{actor} {index}"
    rows = _journal(workspace)  # every line parsed, so no row was torn
    assert [row["seq"] for row in rows] == list(range(200))
    assert len(json.loads((tmp_path / "owners.json").read_text())) == 100


def test_saved_name_carries_writer_and_episode(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.begin_step(episode=0, step=0)
    assert workspace.write("alice", "notes.txt", "a1")["saved_as"] == "notes_0001.txt"
    # The same name from the other agent in the same step is a different file, not a refusal.
    assert workspace.write("bob", "notes.txt", "b1")["saved_as"] == "notes_1001.txt"
    assert workspace.write("bob", "notes", "no extension")["saved_as"] == "notes_1001"
    # Writing the same name again in the same episode replaces the writer's own file.
    assert workspace.write("alice", "notes.txt", "a1 v2")["saved_as"] == "notes_0001.txt"
    assert (workspace.files / "notes_0001.txt").read_text() == "a1 v2"
    assert (workspace.files / "notes_1001.txt").read_text() == "b1"

    workspace.begin_step(episode=11, step=0)
    assert workspace.write("alice", "notes.txt", "a12")["saved_as"] == "notes_0012.txt"
    assert (workspace.files / "notes_0001.txt").read_text() == "a1 v2"
    # An agent cannot reach the other agent's file by asking for its saved name.
    assert workspace.write("bob", "notes_0001.txt", "x")["saved_as"] == "notes_0001_1012.txt"

    row = _journal(workspace)[1]
    assert (row["actor"], row["requested"], row["file"], row["owner"]) == (
        "bob", "notes.txt", "notes_1001.txt", "bob",
    )


def test_a_steps_writes_reach_the_other_agent_only_next_step(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.begin_step(episode=0, step=0)
    written = workspace.write("alice", "a.md", "from alice")
    assert _names(written) == ["a_0001.md"]  # the author sees its own write at once
    assert workspace.read("alice", "a_0001.md")["content"] == "from alice"
    assert _names(workspace.list("bob")) == []
    assert workspace.read("bob", "a_0001.md")["success"] is False

    workspace.begin_step(episode=0, step=1)
    assert _names(workspace.list("bob")) == ["a_0001.md"]
    assert workspace.read("bob", "a_0001.md")["content"] == "from alice"
    # Alice's rewrite in step 1 is again hidden from Bob until step 2.
    workspace.write("alice", "a.md", "rewritten")
    assert workspace.read("bob", "a_0001.md")["content"] == "from alice"
    assert _names(workspace.write("bob", "b.md", "from bob")) == ["a_0001.md", "b_1001.md"]

    exposure = [row for row in _journal(workspace) if row["actor"] == "bob" and row["op"] == "read"]
    assert [(row["step"], row["owner"], row["success"]) for row in exposure] == [
        (0, None, False), (1, "alice", True), (1, "alice", True),
    ]


def test_names_with_a_directory_part_are_refused(tmp_path):
    workspace = Workspace(tmp_path)
    for name in ("", ".", "..", "../owners.json", "sub/notes.md", "..\\x"):
        assert workspace.write("alice", name, "x")["success"] is False
        assert workspace.read("alice", name)["success"] is False
    assert list(workspace.files.iterdir()) == []
    assert not (tmp_path / "owners.json").exists()


def test_workspace_persists_across_instances(tmp_path):
    first = Workspace(tmp_path)
    first.begin_step(episode=0, step=0)
    first.write("alice", "a.md", "episode 1")

    second = Workspace(tmp_path)  # a later episode
    assert _names(second.list("bob")) == ["a_0001.md"]
    assert second.contents() =={"a_0001.md": {"owner": "alice", "content": "episode 1"}}
    assert [row["seq"] for row in _journal(second)] == [0, 1]
