"""Inputs and a runnable legacy comparison for the calibration handoff."""
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from archive_db import ReplyLost
from corrections.recover import resume
from corrections.request import amend
from delivery.current import current
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from demo import LAYOUT as DEMO_LAYOUT
from demo import lose_at, reading_group, source_group
from intake.manifest import ManifestEntry
from intake.register import ingest, initialise_archive
from intake.validate import InputRow
from layout.registry import define
from layout.values import MISSING


VOLUME = "shift-17"
LAYOUT = replace(DEMO_LAYOUT, layout_id="differential-8")
PAIR = ("x", "y")
ROWS = (
    InputRow("R-20", 4, 2, (17, 5)),
    InputRow("R-11", 5, 1, (20, 2)),
    InputRow("R-03", 5, 3, (23, 0)),
)
MANIFEST = tuple(ManifestEntry(row.row_id, len(row.words), row.page, row.position) for row in ROWS)
LOWER = (("R-20", "x", 4),)
UPPER = (("R-20", "y", 2),)
AUXILIARY = (("R-20", "z", 6),)
MIXED_ROWS = (("R-20", "y", 0), ("R-11", "y", 4), ("R-11", "z", 3))


def install(path, layout=LAYOUT, volume_id=VOLUME):
    define(path, layout)
    return ingest(path, volume_id, layout.layout_id, ROWS, MANIFEST)


def exercise_legacy(path):
    accepted = install(path)
    original = frozen(path, accepted.report_id)
    assert tuple(item.value for item in original.observations) == (1, 5, 2, 4, 2, 2, MISSING, 0, 2)

    try:
        amend(path, VOLUME, "lower", LOWER, hook=lose_at("after_word_commit"))
    except ReplyLost as loss:
        assert loss.event == "after_word_commit"
        assert (loss.detail.phase, loss.detail.before, loss.detail.after) == ("prepare", 17, 20)
    else:
        raise AssertionError("Expected a lost reply after preparing the lower reading")

    auxiliary = amend(path, VOLUME, "auxiliary", AUXILIARY)
    upper = amend(path, VOLUME, "upper", UPPER)
    paused = current(path, VOLUME)
    assert (reading_group(paused), source_group(paused)) == ((1, 2, 6), (None, "upper", "auxiliary"))
    assert reconcile(path, VOLUME).words[0].actual_word == 52

    lower = resume(path, "lower")
    live = current(path, VOLUME)
    ledger = reconcile(path, VOLUME)
    assert reading_group(live) == (4, 2, 6)
    assert source_group(live) == ("lower", "upper", "auxiliary")
    assert (auxiliary.publication, upper.publication, lower.publication) == (1, 2, 3)
    assert ledger.settled and tuple(word.actual_word for word in ledger.words[:2]) == (52, 2)
    assert frozen(path, accepted.report_id) == original
    assert all(frozen(path, item.report_id).receipt == item for item in (lower, upper, auxiliary))
    return {
        "layout_id": LAYOUT.layout_id,
        "row": ROWS[0].row_id,
        "original": reading_group(original.observations),
        "while_lower_pending": reading_group(paused),
        "published": reading_group(live),
        "publication_order": (auxiliary.request_id, upper.request_id, lower.request_id),
        "sources": source_group(live),
        "physical_words": tuple(word.actual_word for word in ledger.words[:2]),
    }


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "legacy.sqlite3"
        initialise_archive(path)
        print(json.dumps(exercise_legacy(path), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
