from archive_db import ConflictError, NotFound, WordUnavailable, connection, transaction
from corrections.recover import resume
from corrections.request import amend
from delivery.current import current
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from demo import A_CHANGES, B_CHANGES, reading_group, source_group
from intake.register import initialise_archive
from tests.support import ArchiveTestCase
from words.address import word_address


class DeliveryTests(ArchiveTestCase):
    def test_after_publication_reply_lost(self):
        self.accept()
        first = self.pause_alpha('after_publish')
        self.assertEqual((self.word(), self.word(1)), (20, 5))
        self.assertEqual(reading_group(current(self.path, 'day')), (4, 5, 2))
        initialise_archive(self.path)
        self.assertEqual(frozen(self.path, first.report_id).receipt, first)
        self.assertEqual(amend(self.path, 'day', 'alpha', A_CHANGES), first)
        self.assertEqual(resume(self.path, 'alpha'), first)
        with self.assertRaises(ConflictError):
            resume(self.path, 'alpha', action='cancel')
        with connection(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM word_attempts').fetchone()[0], 2)
        self.assertTrue(reconcile(self.path, 'day').settled)

    def test_historical_source(self):
        accepted = self.accept()
        initial = frozen(self.path, accepted.report_id)
        alpha = amend(self.path, 'day', 'alpha', A_CHANGES)
        old = frozen(self.path, alpha.report_id)
        latest = amend(self.path, 'day', 'next', (('R-20', 'x', 6),))
        self.assertTrue(reconcile(self.path, 'day').settled)
        initialise_archive(self.path)
        self.assertEqual(frozen(self.path, accepted.report_id), initial)
        self.assertEqual(frozen(self.path, alpha.report_id), old)
        self.assertEqual(tuple((item.value, item.provenance.request_id, item.provenance.publication)
                               for item in old.observations), ((4, 'alpha', 1), (5, 'alpha', 1)))
        self.assertEqual(reading_group(initial.observations), (1, 3, 2))
        live = current(self.path, 'day')
        self.assertEqual((reading_group(live), source_group(live)), ((6, 5, 2), ('next', 'alpha', None)))
        self.assertEqual(live[0].provenance.publication, latest.publication)

    def test_physical_mismatch(self):
        self.accept()
        self.pause_alpha()
        amend(self.path, 'day', 'beta', B_CHANGES)
        result = reconcile(self.path, 'day')
        self.assertFalse(result.settled)
        shared = result.words[0]
        self.assertEqual((shared.actual_word, shared.expected_word), (52, 49))
        self.assertEqual(shared.last_attempt.request_id, 'beta')
        fields = {item.field_name: item for item in shared.fields}
        x, z = fields['x'], fields['z']
        self.assertEqual((x.expected, x.actual, x.status, x.pending_request), (1, 4, 'pending', 'alpha'))
        self.assertEqual((z.expected, z.actual, z.status, z.pending_request), (6, 6, 'settled', None))
        self.assertEqual(result.words[1].fields[0].status, 'pending')
        resume(self.path, 'alpha')
        self.assertTrue(reconcile(self.path, 'day').settled)

    def test_unconfirmed_read(self):
        self.accept()
        self.pause_alpha()
        amend(self.path, 'day', 'beta', B_CHANGES)
        address = word_address('day', 'R-20', 0)

        def unavailable(event, detail):
            if event == 'before_word_read' and detail == address:
                raise WordUnavailable('现场读取失答')

        inspection = reconcile(self.path, 'day', hook=unavailable)
        word = inspection.words[0]
        self.assertFalse(inspection.settled)
        self.assertEqual(word.address, address)
        self.assertIsNone(word.actual_word)
        self.assertIsNone(word.unassigned_difference)
        self.assertEqual(word.last_attempt.request_id, 'beta')
        self.assertEqual(tuple((item.field_name, item.expected, item.actual, item.status) for item in word.fields),
                         (('x', 1, None, 'unknown'), ('z', 6, None, 'unknown')))
        resume(self.path, 'alpha')
        self.assertTrue(reconcile(self.path, 'day').settled)

    def test_unknown_frozen(self):
        self.accept()
        with self.assertRaises(NotFound):
            frozen(self.path, 'absent')

    def test_published_replay_repairs_only_fields_it_still_owns(self):
        self.accept()
        alpha = amend(self.path, 'day', 'alpha', A_CHANGES)
        successor = amend(self.path, 'day', 'successor', (('R-20', 'x', 6),))
        with connection(self.path) as db, transaction(db, write=True):
            # Model a discrepant physical readout of y while the published records are intact.
            db.execute('UPDATE physical_words SET packed = ? WHERE volume_id = ? AND row_id = ? AND slot = ?',
                       ('2', 'day', 'R-20', 1))
        discrepancy = reconcile(self.path, 'day').words[1]
        self.assertEqual((discrepancy.fields[0].status, discrepancy.actual_word, discrepancy.expected_word),
                         ('mismatch', 2, 5))
        self.assertEqual(reading_group(current(self.path, 'day')), (6, 5, 2))
        self.assertEqual(resume(self.path, 'alpha'), alpha)
        self.assertEqual((self.word(), self.word(1)), (22, 5))
        self.assertEqual(source_group(current(self.path, 'day')), ('successor', 'alpha', None))
        self.assertEqual(frozen(self.path, successor.report_id).receipt, successor)
        self.assertTrue(reconcile(self.path, 'day').settled)

    def test_published_replay_leaves_successor_prewrite_untouched(self):
        self.accept()
        alpha = amend(self.path, 'day', 'alpha', (A_CHANGES[0],))
        from archive_db import ReplyLost
        from demo import lose_at
        with self.assertRaises(ReplyLost):
            amend(self.path, 'day', 'successor', (('R-20', 'x', 6),), hook=lose_at('after_word_commit'))
        self.assertEqual(self.word(), 22)
        self.assertEqual(resume(self.path, 'alpha'), alpha)
        self.assertEqual(self.word(), 22)
        now = current(self.path, 'day')
        self.assertEqual((reading_group(now), source_group(now)), ((4, 3, 2), ('alpha', None, None)))
        resume(self.path, 'successor')
        self.assertEqual(reading_group(current(self.path, 'day')), (6, 3, 2))
