from archive_db import NotFound, ReplyLost, connection
from corrections.pending import FieldsBusy
from corrections.recover import CancelledCorrection, resume
from corrections.request import amend
from delivery.current import current
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from demo import A_CHANGES, B_CHANGES, lose_at, reading_group, source_group
from intake.register import initialise_archive
from layout.values import MISSING
from tests.support import ArchiveTestCase


class CorrectionTests(ArchiveTestCase):
    def test_published_batch(self):
        accepted = self.accept()
        changes = (('R-02', 'y', MISSING), *reversed(A_CHANGES))
        receipt = amend(self.path, 'day', 'alpha', changes)
        self.assertEqual((receipt.request_id, receipt.volume_id, receipt.publication), ('alpha', 'day', 1))
        report = frozen(self.path, receipt.report_id)
        self.assertEqual(report.receipt, receipt)
        self.assertEqual(tuple((item.row_id, item.field_name, item.value) for item in report.observations),
                         (('R-20', 'x', 4), ('R-20', 'y', 5), ('R-02', 'y', MISSING)))
        self.assertEqual(tuple(item.provenance.publication for item in report.observations), (1, 1, 1))
        now = current(self.path, 'day')
        self.assertEqual((reading_group(now), source_group(now)), ((4, 5, 2), ('alpha', 'alpha', None)))
        self.assertEqual((self.word(), self.word(1), self.word(1, 'R-02')), (20, 5, 135))
        self.assertTrue(reconcile(self.path, 'day').settled)
        self.assertEqual(frozen(self.path, accepted.report_id).observations[-2].value, 0)

    def test_invalid_value_or_field(self):
        self.accept()
        invalid = (('R-20', 'y', 8), ('R-20', 'y', 7), ('R-20', 'y', True),
                   ('R-20', 'y', -1), ('R-20', 'absent', 0), ('no-row', 'y', 0), ('R-20', 'x', 3))
        for target in invalid:
            with self.subTest(target=target), self.assertRaises((ValueError, NotFound)):
                amend(self.path, 'day', 'alpha', (A_CHANGES[0], target))
            with self.assertRaises(NotFound):
                resume(self.path, 'alpha')
            self.assertEqual((self.word(), self.word(1)), (17, 3))
        self.assertEqual(amend(self.path, 'day', 'alpha', A_CHANGES).publication, 1)

    def test_overlap_waits(self):
        self.accept()
        self.pause_alpha()
        with self.assertRaises(FieldsBusy) as busy:
            amend(self.path, 'day', 'blocked', (*B_CHANGES, ('R-20', 'y', 2)))
        self.assertEqual((busy.exception.holder, busy.exception.field_name), ('alpha', 'y'))
        with self.assertRaises(NotFound):
            resume(self.path, 'blocked')
        beta = amend(self.path, 'day', 'beta', B_CHANGES)
        self.assertEqual(source_group(current(self.path, 'day')), (None, None, 'beta'))
        self.assertEqual(beta.publication, 1)

    def test_masked_cancel(self):
        self.accept()
        self.pause_alpha()
        beta = amend(self.path, 'day', 'beta', B_CHANGES)
        original_beta_report = frozen(self.path, beta.report_id)
        initialise_archive(self.path)
        cancelled = resume(self.path, 'alpha', action='cancel')
        self.assertEqual(cancelled, CancelledCorrection('alpha', 'day'))
        now = current(self.path, 'day')
        actual = (reading_group(now), source_group(now), self.word(), self.word(1))
        self.assertEqual(actual, ((1, 3, 6), (None, None, 'beta'), 49, 3), f'PACKED_CORRECTION_MIXED {actual!r}')
        self.assertTrue(reconcile(self.path, 'day').settled)
        self.assertEqual(amend(self.path, 'day', 'alpha', A_CHANGES), cancelled)
        self.assertEqual(amend(self.path, 'day', 'beta', B_CHANGES), beta)
        self.assertEqual(frozen(self.path, beta.report_id), original_beta_report)
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:alpha')

    def test_cancellation_cleanup_retains_reservations_after_loss(self):
        self.accept()
        self.pause_alpha()
        with self.assertRaises(ReplyLost):
            resume(self.path, 'alpha', action='cancel', hook=lose_at('after_word_commit'))
        self.assertEqual(self.word(), 17)
        self.assertEqual(reading_group(current(self.path, 'day')), (1, 3, 2))
        with self.assertRaises(FieldsBusy):
            amend(self.path, 'day', 'next', (('R-20', 'y', 2),))
        self.assertEqual(resume(self.path, 'alpha'), CancelledCorrection('alpha', 'day'))
        self.assertEqual(amend(self.path, 'day', 'next', (('R-20', 'y', 2),)).publication, 1)

    def test_cancellation_can_win_at_publish_boundary(self):
        self.accept()

        def cancel_at_boundary(event, detail):
            if event == 'before_publish':
                self.assertEqual(resume(self.path, detail, action='cancel'), CancelledCorrection('alpha', 'day'))

        result = amend(self.path, 'day', 'alpha', A_CHANGES, hook=cancel_at_boundary)
        self.assertEqual(result, CancelledCorrection('alpha', 'day'))
        self.assertEqual((self.word(), self.word(1)), (17, 3))
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:alpha')

    def test_shared_word_fields_commit_once(self):
        self.accept()
        receipt = amend(self.path, 'day', 'together', (A_CHANGES[0], *B_CHANGES))
        self.assertEqual((self.word(), self.word(1)), (52, 3))
        self.assertEqual(tuple(item.field_name for item in frozen(self.path, receipt.report_id).observations), ('x', 'z'))
        with connection(self.path) as db:
            operations = db.execute('SELECT COUNT(*) FROM word_attempts WHERE request_id = ?', ('together',)).fetchone()[0]
        self.assertEqual(operations, 1)
