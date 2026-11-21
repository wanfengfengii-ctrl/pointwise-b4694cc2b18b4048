from dataclasses import replace

from archive_db import ConflictError, NotFound
from corrections.request import amend
from delivery.current import current
from delivery.snapshot import frozen
from demo import LAYOUT, MANIFEST, ROWS, reading_group, source_group
from intake.register import ingest, initialise_archive
from layout.registry import define
from layout.values import MISSING
from tests.support import ArchiveTestCase


class IntakeTests(ArchiveTestCase):
    def test_zero_and_missing(self):
        self.accept()
        initialise_archive(self.path)
        readings = current(self.path, 'day', ('z', 'x'))
        self.assertEqual(tuple((item.row_id, item.field_name) for item in readings),
                         (('R-20', 'x'), ('R-20', 'z'), ('R-02', 'x'), ('R-02', 'z')))
        self.assertEqual(tuple(item.value for item in readings), (1, 2, 0, MISSING))
        self.assertIs(type(readings[2].value), int)
        self.assertIs(readings[3].value, MISSING)
        self.assertEqual(tuple((item.provenance.original.page, item.provenance.original.position)
                               for item in readings), ((4, 2), (4, 2), (5, 1), (5, 1)))
        self.assertTrue(all(item.provenance.kind == 'original' for item in readings))
        with self.assertRaises(NotFound):
            current(self.path, 'day', ('no-field',))

    def test_initial_report(self):
        receipt = self.accept()
        self.assertEqual(receipt.row_count, 2)
        self.assertEqual(receipt.report_id, 'original:day')
        report = frozen(self.path, receipt.report_id)
        self.assertEqual((report.kind, report.receipt), ('original', receipt))
        self.assertEqual(tuple(item.value for item in report.observations), (1, 3, 2, 0, 0, MISSING))
        self.assertEqual((report.observations[4].provenance.original.row_number,
                          report.observations[4].provenance.original.address.slot), (2, 1))
        self.assertEqual(report.observations, current(self.path, 'day'))

    def test_reopen_keeps_edits(self):
        accepted = self.accept()
        receipt = amend(self.path, 'day', 'user-edit', (('R-20', 'y', 4),))
        initialise_archive(self.path)
        self.assertEqual(define(self.path, LAYOUT), LAYOUT.layout_id)
        self.assertEqual(self.accept(), accepted)
        result = current(self.path, 'day')
        self.assertEqual((reading_group(result), source_group(result)), ((1, 4, 2), (None, 'user-edit', None)))
        self.assertEqual(frozen(self.path, receipt.report_id).receipt, receipt)
        self.assertEqual(reading_group(frozen(self.path, accepted.report_id).observations), (1, 3, 2))
        self.assertEqual(self.word(1), 4)

    def test_same_count_wrong_order(self):
        prior = self.accept('prior')
        for manifest in (MANIFEST[::-1], (replace(MANIFEST[0], position=9), MANIFEST[1])):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                ingest(self.path, 'day', LAYOUT.layout_id, ROWS, manifest)
            with self.assertRaises(NotFound):
                current(self.path, 'day')
            with self.assertRaises(NotFound):
                frozen(self.path, 'original:day')
        self.assertEqual(frozen(self.path, prior.report_id).receipt, prior)
        self.assertEqual(self.accept().volume_id, 'day')
        self.assertEqual(tuple(item.row_id for item in current(self.path, 'day')[::3]), ('R-20', 'R-02'))

    def test_original_number_cannot_be_rebound(self):
        original = self.accept()
        altered = (replace(ROWS[0], words=(18, 3)), ROWS[1])
        with self.assertRaises(ConflictError):
            ingest(self.path, 'day', LAYOUT.layout_id, altered, MANIFEST)
        self.assertEqual(frozen(self.path, original.report_id).receipt, original)
        self.assertEqual(self.word(), 17)

    def test_invalid_word_rejects_intake(self):
        for invalid in (-1, 256, True):
            rows = (ROWS[0], replace(ROWS[1], words=(184, invalid)))
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ingest(self.path, 'day', LAYOUT.layout_id, rows, MANIFEST)
            with self.assertRaises(NotFound):
                current(self.path, 'day')
        self.assertEqual(self.accept().row_count, 2)
