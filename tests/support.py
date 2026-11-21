from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from archive_db import ReplyLost, connection
from corrections.request import amend
from demo import A_CHANGES, LAYOUT, MANIFEST, ROWS, lose_at
from intake.register import ingest, initialise_archive
from layout.registry import define
from words.address import word_address
from words.store import read_word


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'archive.sqlite3'
        initialise_archive(self.path)
        define(self.path, LAYOUT)

    def accept(self, volume='day'):
        return ingest(self.path, volume, LAYOUT.layout_id, ROWS, MANIFEST)

    def pause_alpha(self, event='after_word_commit'):
        with self.assertRaises(ReplyLost) as lost:
            amend(self.path, 'day', 'alpha', A_CHANGES, hook=lose_at(event))
        self.assertEqual(lost.exception.event, event)
        return lost.exception.detail

    def word(self, slot=0, row='R-20', volume='day'):
        with connection(self.path) as db:
            return read_word(db, word_address(volume, row, slot))
