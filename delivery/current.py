from archive_db import WordUnavailable, checkpoint, connection, require_name, transaction
from corrections.journal import read_field_evidence
from delivery.provenance import select_field_observation
from delivery.selection import resolve_selection
from intake.archive import get_original
from intake.origin import build_origin_index, locate_original_field
from layout.codec import decode_field
from layout.registry import get_layout
from words.store import read_word


def read_current_fields(db, original, layout, keys=None, *, hook=None):
    """Read within the caller's SQLite transaction, in the order of the supplied keys."""
    if keys is None:
        keys = resolve_selection(original, layout)
    origins = build_origin_index(original.volume_id, layout, original.rows)
    rows = {row.row_id: row for row in original.rows}
    fields = {field.name: field for field in layout.fields}
    packed = {}
    result = []
    for key in keys:
        origin = locate_original_field(origins, key.row_id, key.field_name)
        address = origin.address
        field = fields[key.field_name]
        if address not in packed:
            try:
                packed[address] = read_word(db, address)
            except WordUnavailable:
                packed[address] = None
        word = packed[address]
        physical = None if word is None else decode_field(word, field)
        original_value = decode_field(rows[key.row_id].words[address.slot], field)
        evidence = read_field_evidence(db, address, key.field_name)
        observation = select_field_observation(origin, physical, original_value, evidence)
        result.append(observation)
        checkpoint(hook, 'after_observation', observation)
    return tuple(result)


def current(path, volume_id, fields=None, *, hook=None):
    require_name(volume_id, 'volume id')
    with connection(path) as db, transaction(db):
        original = get_original(db, volume_id)
        layout = get_layout(db, original.layout_id)
        keys = resolve_selection(original, layout, fields)
        return read_current_fields(db, original, layout, keys, hook=hook)
