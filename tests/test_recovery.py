from archive_db import ConflictError, NotFound, connection
from corrections.journal import load_request, request_fields
from corrections.recover import resume
from corrections.request import amend
from delivery.current import current
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from demo import A_CHANGES, B_CHANGES, reading_group, source_group
from intake.register import initialise_archive
from tests.support import ArchiveTestCase
from words.attempt import WriteOutcome, find_attempt
from words.write import check_write_outcome


class RecoveryTests(ArchiveTestCase):
    def test_persisted_attempt(self):
        self.accept()
        attempt = self.pause_alpha()
        initialise_archive(self.path)
        with connection(self.path) as db:
            self.assertEqual(find_attempt(db, attempt.attempt_id), attempt)
            self.assertIs(check_write_outcome(db, attempt.attempt_id), WriteOutcome.COMMITTED)
            self.assertIs(check_write_outcome(db, attempt.attempt_id + 1), WriteOutcome.UNKNOWN)
            self.assertEqual(load_request(db, 'alpha').state, 'pending')
            self.assertEqual(tuple(item.prepared_attempt for item in request_fields(db, 'alpha')),
                             (attempt.attempt_id, None))
        self.assertEqual((self.word(), self.word(1)), (20, 3))
        pending = current(self.path, 'day')
        self.assertEqual((reading_group(pending), source_group(pending)), ((1, 3, 2), (None, None, None)))
        self.assertEqual(reconcile(self.path, 'day').words[0].last_attempt, attempt)
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:alpha')
        self.assertEqual(resume(self.path, 'alpha').publication, 1)
        self.assertEqual((self.word(), self.word(1)), (20, 5))
        self.assertTrue(reconcile(self.path, 'day').settled)

    def test_interleaved_disjoint(self):
        accepted = self.accept()
        self.pause_alpha()
        beta = amend(self.path, 'day', 'beta', B_CHANGES)
        during = current(self.path, 'day')
        values_and_source = (reading_group(during), source_group(during))
        self.assertEqual(values_and_source, ((1, 3, 6), (None, None, 'beta')),
                         f'PACKED_CORRECTION_MIXED {values_and_source!r}')
        self.assertEqual((self.word(), self.word(1)), (52, 3))
        initialise_archive(self.path)
        alpha = resume(self.path, 'alpha')
        final = current(self.path, 'day')
        self.assertEqual((reading_group(final), source_group(final)), ((4, 5, 6), ('alpha', 'alpha', 'beta')))
        self.assertEqual((beta.publication, alpha.publication), (1, 2))
        self.assertEqual(amend(self.path, 'day', 'alpha', tuple(reversed(A_CHANGES))), alpha)
        self.assertEqual(resume(self.path, 'beta'), beta)
        self.assertEqual((self.word(), self.word(1)), (52, 5))
        self.assertEqual(reading_group(frozen(self.path, accepted.report_id).observations), (1, 3, 2))

    def test_before_publication(self):
        self.accept()
        self.pause_alpha('before_publish')
        self.assertEqual((self.word(), self.word(1)), (20, 5))
        paused = current(self.path, 'day')
        self.assertEqual((reading_group(paused), source_group(paused)), ((1, 3, 2), (None, None, None)))
        with self.assertRaises(NotFound):
            frozen(self.path, 'correction:alpha')
        initialise_archive(self.path)
        alpha = resume(self.path, 'alpha')
        self.assertEqual(frozen(self.path, alpha.report_id).receipt, alpha)
        self.assertEqual(reading_group(current(self.path, 'day')), (4, 5, 2))

    def test_query_spans_publish(self):
        self.accept()
        self.pause_alpha('before_publish')
        signed = []

        def publish_between_fields(event, detail):
            if event == 'after_observation' and not signed:
                self.assertEqual((detail.row_id, detail.field_name, detail.value), ('R-20', 'x', 1))
                signed.append(resume(self.path, 'alpha'))

        overlapping = current(self.path, 'day', hook=publish_between_fields)
        self.assertEqual(len(signed), 1)
        self.assertEqual((reading_group(overlapping), source_group(overlapping)), ((1, 3, 2), (None, None, None)))
        later = current(self.path, 'day')
        self.assertEqual((reading_group(later), source_group(later)), ((4, 5, 2), ('alpha', 'alpha', None)))
        self.assertEqual(frozen(self.path, signed[0].report_id).receipt, signed[0])

    def test_changed_argument(self):
        self.accept()
        self.accept('other')
        first = amend(self.path, 'day', 'alpha', A_CHANGES)
        report = frozen(self.path, first.report_id)
        initialise_archive(self.path)
        with self.assertRaises(ConflictError):
            amend(self.path, 'day', 'alpha', (A_CHANGES[0], ('R-20', 'y', 6)))
        with self.assertRaises(ConflictError):
            amend(self.path, 'other', 'alpha', A_CHANGES)
        self.assertEqual(resume(self.path, 'alpha'), first)
        self.assertEqual(frozen(self.path, first.report_id), report)
        self.assertEqual(reading_group(current(self.path, 'day')), (4, 5, 2))
        self.assertEqual(reading_group(current(self.path, 'other')), (1, 3, 2))

    def test_unknown_request(self):
        for action in ('continue', 'cancel'):
            with self.subTest(action=action), self.assertRaises(NotFound):
                resume(self.path, 'absent', action=action)

    def test_before_word_commit_lost_reply(self):
        self.accept()
        self.pause_alpha('before_word_commit')
        with connection(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM word_attempts').fetchone()[0], 0)
            self.assertEqual(load_request(db, 'alpha').state, 'pending')
        self.assertEqual((self.word(), self.word(1)), (17, 3))
        resume(self.path, 'alpha')
        self.assertEqual((self.word(), self.word(1)), (20, 5))
