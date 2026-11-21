"""Business assertions for the immutable differential calibration pair."""
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from archive_db import ConflictError, NotFound, ReplyLost, connection
from calibration_case import AUXILIARY, LOWER, MANIFEST, MIXED_ROWS, PAIR, ROWS, UPPER, VOLUME
from corrections.journal import load_request
from corrections.pending import FieldsBusy
from corrections.recover import CalibrationRejection, resume
from corrections.request import amend
from delivery.current import read_calibration
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from demo import LAYOUT, lose_at
from intake.register import initialise_archive, ingest
from layout.registry import define, get_layout
from layout.values import MISSING
from words.address import word_address
from words.store import read_word


class CalibrationTestCase:
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'calibration.sqlite3'
        initialise_archive(self.path)
        self.layout = replace(LAYOUT, calibration_pair=PAIR)
        define(self.path, self.layout)
        self.receipt = ingest(self.path, VOLUME, self.layout.layout_id, ROWS, MANIFEST)

    def r20(self):
        observations, _ = read_calibration(self.path, VOLUME)
        return tuple(None if item.value is MISSING else item.value
                     for item in observations if item.row_id == 'R-20')

    def r20_sources(self):
        observations, _ = read_calibration(self.path, VOLUME)
        return tuple(item.provenance.request_id
                     for item in observations if item.row_id == 'R-20')

    def words(self):
        with connection(self.path) as db:
            return (read_word(db, word_address(VOLUME, 'R-20', 0)),
                    read_word(db, word_address(VOLUME, 'R-20', 1)))

    def statuses(self, fields=('x',)):
        _, evidence = read_calibration(self.path, VOLUME, fields)
        return tuple((item.row_id, item.status) for item in evidence)


class LayoutPairTests(CalibrationTestCase, unittest.TestCase):
    def test_invalid_declarations_raise_value_error(self):
        for bad in (('x', 'nope'), ('x', 'x'), 'x', ('x',), ('x', 'y', 'z'), (1, 2), None):
            if bad is None:
                continue
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    define(self.path, replace(self.layout, layout_id=f'bad-{bad}', calibration_pair=bad))

    def test_same_definition_replays_and_pair_changes_conflict(self):
        self.assertEqual(define(self.path, self.layout), self.layout.layout_id)
        with self.assertRaises(ConflictError):
            define(self.path, replace(self.layout, calibration_pair=('x', 'z')))
        with self.assertRaises(ConflictError):
            define(self.path, replace(self.layout, calibration_pair=None))
        with connection(self.path) as db:
            self.assertEqual(get_layout(db, self.layout.layout_id).calibration_pair, PAIR)

    def test_legacy_layout_kept_without_pair_and_reopens(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'legacy.sqlite3'
        initialise_archive(path)
        define(path, LAYOUT)
        ingest(path, VOLUME, LAYOUT.layout_id, ROWS, MANIFEST)
        initialise_archive(path)
        with connection(path) as db:
            self.assertIsNone(get_layout(db, LAYOUT.layout_id).calibration_pair)
        observations, evidence = read_calibration(path, VOLUME)
        self.assertEqual(len(observations), 9)
        self.assertEqual(evidence, ())


class CalibrationGateTests(CalibrationTestCase, unittest.TestCase):
    def test_night_evidence_uses_original_order_and_both_sides(self):
        self.assertEqual(self.statuses(), (('R-20', 'qualified'), ('R-11', 'inverted'), ('R-03', 'missing')))
        observations, evidence = read_calibration(self.path, VOLUME, ('x',))
        self.assertEqual(tuple(item.field_name for item in observations), ('x', 'x', 'x'))
        self.assertEqual(tuple((item.lower.value, item.upper.value) for item in evidence),
                         ((1, 5), (4, 2), (MISSING, 0)))
        # The upper value comes from each row's own second-word original location.
        self.assertTrue(all(item.lower.provenance.original.address.slot == 0 for item in evidence))
        self.assertTrue(all(item.upper.provenance.original.address.slot == 1 for item in evidence))
        self.assertTrue(all(item.lower.provenance.kind == 'original' for item in evidence))

    def test_qualified_and_equal_and_missing_amends_sign(self):
        self.assertEqual(amend(self.path, VOLUME, 'lower', LOWER).publication, 1)
        self.assertEqual(amend(self.path, VOLUME, 'equal', (('R-20', 'y', 4),)).publication, 2)
        missing = amend(self.path, VOLUME, 'missing-side', (('R-03', 'y', MISSING),))
        self.assertEqual(missing.publication, 3)
        self.assertEqual(self.statuses(),
                         (('R-20', 'qualified'), ('R-11', 'inverted'), ('R-03', 'missing')))

    def test_ordinary_fields_sign_even_on_inverted_rows(self):
        receipt = amend(self.path, VOLUME, 'ordinary', (('R-11', 'z', 3),))
        self.assertEqual(receipt.publication, 1)
        self.assertEqual(self.r20_sources(), (None, None, None))

    def test_inverted_to_equal_repairs_the_row(self):
        amend(self.path, VOLUME, 'fix', (('R-11', 'y', 4),))
        self.assertEqual(self.statuses(),
                         (('R-20', 'qualified'), ('R-11', 'qualified'), ('R-03', 'missing')))

    def test_admission_rejection_is_terminal_and_replays(self):
        # Original R-20 is (1, 5); lowering y to 0 makes the pair (1, 0) inverted at admission.
        inverted_target = (('R-20', 'y', 0),)
        rejection = amend(self.path, VOLUME, 'upper', inverted_target)
        self.assertEqual(rejection, CalibrationRejection('upper', VOLUME))
        self.assertEqual(amend(self.path, VOLUME, 'upper', inverted_target), rejection)
        self.assertEqual(resume(self.path, 'upper'), rejection)
        with self.assertRaises(ConflictError):
            amend(self.path, VOLUME, 'upper', (('R-20', 'y', 3),))
        with self.assertRaises(ConflictError):
            resume(self.path, 'upper', action='cancel')
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:upper')
        with connection(self.path) as db:
            row = load_request(db, 'upper')
            self.assertEqual(row.state, 'rejected')
            self.assertIsNone(row.publication)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM field_reservations').fetchone()[0], 0)
        # The rejected request never changed the physical words.
        self.assertEqual(self.words(), (17, 5))

    def test_mixed_rows_rejects_the_whole_request(self):
        rejection = amend(self.path, VOLUME, 'mixed', MIXED_ROWS)
        self.assertEqual(rejection, CalibrationRejection('mixed', VOLUME))
        observations, _ = read_calibration(self.path, VOLUME)
        # Neither the R-11 qualified repair nor its ordinary z change was published.
        r11 = tuple(None if item.value is MISSING else item.value
                    for item in observations if item.row_id == 'R-11')
        self.assertEqual(r11, (4, 2, 2))
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:mixed')

    def test_ordinary_field_inside_an_inverted_request_does_not_sign(self):
        rejection = amend(self.path, VOLUME, 'mixed-inverted',
                          (('R-11', 'x', 6), ('R-11', 'z', 3)))
        self.assertEqual(rejection, CalibrationRejection('mixed-inverted', VOLUME))
        observations, evidence = read_calibration(self.path, VOLUME)
        r11 = tuple(None if item.value is MISSING else item.value
                    for item in observations if item.row_id == 'R-11')
        self.assertEqual(r11, (4, 2, 2))
        self.assertEqual(evidence[1].status, 'inverted')
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:mixed-inverted')

    def test_empty_projection_still_returns_two_sided_evidence(self):
        observations, evidence = read_calibration(self.path, VOLUME, ())
        self.assertEqual(observations, ())
        self.assertEqual(tuple(item.status for item in evidence),
                         ('qualified', 'inverted', 'missing'))
        self.assertTrue(all(item.lower.field_name == 'x' and item.upper.field_name == 'y'
                            for item in evidence))

    def test_pending_pair_does_not_count_as_published_fact(self):
        with self.assertRaises(ReplyLost):
            amend(self.path, VOLUME, 'lower', LOWER, hook=lose_at('after_word_commit'))
        # While lower is only prewritten, the published snapshot still shows the original (1, 5),
        # so y=2 is qualified and signs; the in-flight prewrite is not treated as published.
        upper = amend(self.path, VOLUME, 'upper', UPPER)
        self.assertEqual(upper.publication, 1)
        self.assertEqual(self.r20(), (1, 2, 2))

    def test_publish_gate_rejects_after_peer_signs_and_cleans_prewrite(self):
        with self.assertRaises(ReplyLost):
            amend(self.path, VOLUME, 'lower', LOWER, hook=lose_at('after_word_commit'))
        auxiliary = amend(self.path, VOLUME, 'auxiliary', AUXILIARY)
        amend(self.path, VOLUME, 'upper', UPPER)
        rejection = resume(self.path, 'lower')
        self.assertEqual(rejection, CalibrationRejection('lower', VOLUME))
        # Only one calibration request actually signed; the ordinary z provenance is preserved.
        self.assertEqual(self.r20(), (1, 2, 6))
        self.assertEqual(self.r20_sources(), (None, 'upper', 'auxiliary'))
        # The shared physical word is settled from 52 back to 49.
        self.assertEqual(self.words(), (49, 2))
        self.assertEqual(amend(self.path, VOLUME, 'lower', LOWER), rejection)
        self.assertEqual(resume(self.path, 'lower'), rejection)
        self.assertEqual(auxiliary.publication, 1)

    def test_busy_does_not_consume_request_id_and_retry_succeeds_then_rejects(self):
        with self.assertRaises(ReplyLost):
            amend(self.path, VOLUME, 'lower', LOWER, hook=lose_at('after_word_commit'))
        amend(self.path, VOLUME, 'auxiliary', AUXILIARY)
        with self.assertRaises(FieldsBusy) as busy:
            amend(self.path, VOLUME, 'blocker', (('R-20', 'x', 2),))
        self.assertEqual((busy.exception.holder, busy.exception.field_name), ('lower', 'x'))
        with connection(self.path) as db:
            with self.assertRaises(NotFound):
                load_request(db, 'blocker')
        lower = resume(self.path, 'lower')
        self.assertEqual(lower.publication, 2)
        self.assertEqual(amend(self.path, VOLUME, 'upper', UPPER),
                         CalibrationRejection('upper', VOLUME))
        self.assertEqual(self.r20(), (4, 5, 6))
        self.assertEqual(self.words(), (52, 5))

    def test_lost_reply_during_rejection_cleanup_resumes_by_original_id(self):
        with self.assertRaises(ReplyLost):
            amend(self.path, VOLUME, 'lower', LOWER, hook=lose_at('after_word_commit'))
        amend(self.path, VOLUME, 'upper', UPPER)
        with self.assertRaises(ReplyLost) as lost:
            resume(self.path, 'lower', hook=lose_at('after_word_commit'))
        self.assertEqual(lost.exception.detail.phase, 'cancel')
        with connection(self.path) as db:
            self.assertEqual(load_request(db, 'lower').state, 'rejected')
        rejection = resume(self.path, 'lower')
        self.assertEqual(rejection, CalibrationRejection('lower', VOLUME))
        self.assertEqual(self.words(), (17, 2))
        self.assertEqual(self.r20(), (1, 2, 2))

    def test_decision_is_fixed_even_when_readings_change_afterward(self):
        # y=0 makes the original (1, 5) inverted at admission and is rejected outright.
        rejection = amend(self.path, VOLUME, 'upper', (('R-20', 'y', 0),))
        self.assertEqual(rejection, CalibrationRejection('upper', VOLUME))
        # A later change makes the row qualified; the rejection must still be handed back.
        amend(self.path, VOLUME, 'lower', LOWER)
        self.assertEqual(resume(self.path, 'upper'), rejection)
        self.assertEqual(amend(self.path, VOLUME, 'upper', (('R-20', 'y', 0),)), rejection)

    def test_query_spanning_publish_keeps_one_snapshot(self):
        signed = []

        def interleave(event, detail):
            if event == 'after_observation' and detail.row_id == 'R-11' and detail.field_name == 'x' \
                    and not signed:
                signed.append(amend(self.path, VOLUME, 'fix', (('R-11', 'y', 4),)))

        _, evidence = read_calibration(self.path, VOLUME, ('x',), hook=interleave)
        self.assertEqual(len(signed), 1)
        self.assertEqual(tuple(item.status for item in evidence),
                         ('qualified', 'inverted', 'missing'))
        self.assertEqual(evidence[1].upper.provenance.request_id, None)
        _, later = read_calibration(self.path, VOLUME, ('x',))
        self.assertEqual(tuple(item.status for item in later),
                         ('qualified', 'qualified', 'missing'))
        self.assertEqual(later[1].upper.provenance.request_id, 'fix')
        self.assertEqual(later[1].upper.value, 4)

    def test_reopen_archive_keeps_rejections_and_published_values(self):
        amend(self.path, VOLUME, 'lower', LOWER)
        rejection = amend(self.path, VOLUME, 'upper', UPPER)
        initialise_archive(self.path)
        self.assertEqual(resume(self.path, 'upper'), rejection)
        self.assertEqual(self.r20(), (4, 5, 2))
        self.assertEqual(self.statuses(),
                         (('R-20', 'qualified'), ('R-11', 'inverted'), ('R-03', 'missing')))

    def test_rejection_cleanup_settles_the_prepared_word(self):
        with self.assertRaises(ReplyLost):
            amend(self.path, VOLUME, 'lower', LOWER, hook=lose_at('after_word_commit'))
        amend(self.path, VOLUME, 'upper', UPPER)
        address = word_address(VOLUME, 'R-20', 0)
        with connection(self.path) as db:
            self.assertEqual(read_word(db, address), 20)
        rejection = resume(self.path, 'lower')
        self.assertEqual(rejection, CalibrationRejection('lower', VOLUME))
        with connection(self.path) as db:
            self.assertEqual(load_request(db, 'lower').state, 'rejected')
            self.assertEqual(read_word(db, address), 17)
        self.assertEqual(self.words(), (17, 2))
        self.assertTrue(reconcile(self.path, VOLUME).settled)
        self.assertEqual(self.r20(), (1, 2, 2))


class LegacySchemaMigrationTests(unittest.TestCase):
    def test_old_requests_table_is_upgraded_and_data_kept(self):
        import sqlite3

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'migrated.sqlite3'
        initialise_archive(path)
        define(path, LAYOUT)
        ingest(path, VOLUME, LAYOUT.layout_id, ROWS, MANIFEST)
        receipt = amend(path, VOLUME, 'edit', (('R-20', 'y', 4),))
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('ALTER TABLE correction_requests RENAME TO requests_old')
            db.execute('''CREATE TABLE correction_requests (
                request_id TEXT PRIMARY KEY, volume_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('pending','cancelling','cancelled','published')),
                publication INTEGER UNIQUE, report_id TEXT UNIQUE,
                CHECK ((state='published' AND publication IS NOT NULL AND report_id IS NOT NULL)
                    OR (state<>'published' AND publication IS NULL AND report_id IS NULL)))''')
            db.execute('INSERT INTO correction_requests SELECT * FROM requests_old')
            db.execute('DROP TABLE requests_old')
            db.execute('PRAGMA foreign_keys=ON')
        initialise_archive(path)
        with connection(path) as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='correction_requests'").fetchone()[0]
            self.assertIn("'rejected'", sql)
            self.assertEqual(load_request(db, 'edit').state, 'published')
        self.assertEqual(resume(path, 'edit'), receipt)
