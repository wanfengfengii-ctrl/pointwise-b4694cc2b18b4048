from dataclasses import replace

from archive_db import ConflictError, NotFound, connection
from delivery.current import current
from demo import LAYOUT, reading_group
from layout.registry import define, get_layout
from layout.spec import FieldSpec, LayoutSpec
from tests.support import ArchiveTestCase


class LayoutTests(ArchiveTestCase):
    def test_partial_overlap(self):
        self.accept()
        overlap = LayoutSpec('overlap', 8, 1, (FieldSpec('a', 0, 0, 3), FieldSpec('b', 0, 2, 3)))
        with self.assertRaises(ValueError):
            define(self.path, overlap)
        with connection(self.path) as db:
            with self.assertRaises(NotFound):
                get_layout(db, overlap.layout_id)
            self.assertEqual(get_layout(db, LAYOUT.layout_id), LAYOUT)
        self.assertEqual(reading_group(current(self.path, 'day')), (1, 3, 2))

    def test_conflicting_definition(self):
        self.accept()
        self.assertEqual(define(self.path, LAYOUT), LAYOUT.layout_id)
        changes = (replace(LAYOUT, fields=LAYOUT.fields[::-1]),
                   replace(LAYOUT, fields=(replace(LAYOUT.fields[0], missing_code=6), *LAYOUT.fields[1:])),
                   replace(LAYOUT, fields=(replace(LAYOUT.fields[0], offset=6), *LAYOUT.fields[1:])))
        for changed in changes[:2]:
            with self.subTest(changed=changed), self.assertRaises(ConflictError):
                define(self.path, changed)
        with self.assertRaises(ValueError):
            define(self.path, changes[-1])
        self.assertEqual(tuple(item.field_name for item in current(self.path, 'day')[:3]), ('x', 'y', 'z'))

    def test_wide_word_is_not_limited_by_sqlite_integer_width(self):
        layout = LayoutSpec('wide', 96, 1, (FieldSpec('tail', 0, 80, 8, 255),))
        self.assertEqual(define(self.path, layout), 'wide')
        with connection(self.path) as db:
            self.assertEqual(get_layout(db, 'wide'), layout)
