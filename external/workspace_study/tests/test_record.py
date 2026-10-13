"""The shared record store: append-only notes, lock, step visibility, journal, persistence."""

import json
import threading

from external.workspace_study.workspace import Record


def _stored(record):
    lines = (record.root / "record.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_concurrent_appends_lose_nothing(tmp_path):
    record = Record(tmp_path)

    def worker(actor):
        for index in range(50):
            assert record.write(actor, f"{actor} {index}")["success"]

    threads = [threading.Thread(target=worker, args=(actor,)) for actor in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = _stored(record)  # every line parsed, so no row was torn
    assert [row["id"] for row in rows] == list(range(100))
    for digit, actor in enumerate(("alice", "bob")):
        assert [r["content"] for r in rows if r["agent"] == digit] == [
            f"{actor} {index}" for index in range(50)
        ]
    journal = (tmp_path / "journal.jsonl").read_text().splitlines()
    assert [json.loads(line)["seq"] for line in journal] == list(range(100))


def test_a_steps_notes_reach_the_other_agent_only_next_step(tmp_path):
    record = Record(tmp_path)
    record.begin_step(episode=0, step=0)
    # Bob writes first in wall-clock time; the shown order does not depend on that.
    assert record.write("bob", "b0")["notes"] == [{"episode": 1, "agent": 1, "content": "b0"}]
    assert record.write("alice", "a0")["notes"] == [{"episode": 1, "agent": 0, "content": "a0"}]

    record.begin_step(episode=0, step=1)
    assert [n["content"] for n in record.write("alice", "a1")["notes"]] == ["a0", "b0", "a1"]

    record.begin_step(episode=1, step=0)
    notes = record.write("bob", "b-ep2")["notes"]
    assert [(n["episode"], n["agent"], n["content"]) for n in notes] == [
        (1, 0, "a0"), (1, 1, "b0"), (1, 0, "a1"), (2, 1, "b-ep2"),
    ]
    assert set(notes[0]) == {"episode", "agent", "content"}  # no id or step shown

    last = json.loads((tmp_path / "journal.jsonl").read_text().splitlines()[-1])
    assert (last["actor"], last["file"], last["shown"]) == ("bob", 3, [1, 0, 2, 3])


def test_empty_note_is_refused(tmp_path):
    record = Record(tmp_path)
    assert record.write("alice", "  \n")["success"] is False
    assert not (tmp_path / "record.jsonl").exists()


def test_record_persists_across_instances(tmp_path):
    first = Record(tmp_path)
    first.begin_step(episode=0, step=0)
    first.write("alice", "episode 1")

    second = Record(tmp_path)  # a later episode
    second.begin_step(episode=1, step=0)
    assert [n["content"] for n in second.write("bob", "episode 2")["notes"]] == [
        "episode 1", "episode 2",
    ]
    assert [row["id"] for row in second.contents()] == [0, 1]
