from dataclasses import dataclass

from archive_db import connection, require_name, transaction
from corrections.pending import check_field_holder
from delivery.current import read_current_fields
from intake.archive import get_original
from layout.codec import merge_fields
from layout.registry import get_layout
from words.address import word_address
from words.check import WordInspection, inspect_word


@dataclass(frozen=True)
class ReconciliationResult:
    volume_id: str
    words: tuple[WordInspection, ...]

    @property
    def settled(self):
        return all(word.settled for word in self.words)


def reconcile(path, volume_id, *, hook=None):
    require_name(volume_id, 'volume id')
    with connection(path) as db, transaction(db):
        original = get_original(db, volume_id)
        layout = get_layout(db, original.layout_id)
        readings = {}
        for observation in read_current_fields(db, original, layout):
            address = observation.provenance.original.address
            readings.setdefault(address, {})[observation.field_name] = observation.value
        checks = []
        for row in original.rows:
            for slot, original_word in enumerate(row.words):
                address = word_address(volume_id, row.row_id, slot)
                expected = readings.get(address, {})
                packed = merge_fields(layout, slot, original_word, expected)
                pending = {name: check_field_holder(db, address, name) for name in expected}
                checks.append(inspect_word(db, layout, address, packed, pending, hook=hook))
        return ReconciliationResult(volume_id, tuple(checks))
