import json
from dataclasses import asdict

from archive_db import ConflictError, NotFound, connection, transaction
from layout.spec import FieldSpec, LayoutSpec, validate_layout


def initialise_layouts(db):
    db.execute('''CREATE TABLE IF NOT EXISTS layouts (
        layout_id TEXT PRIMARY KEY,
        definition TEXT NOT NULL
    )''')


def _definition(spec):
    fields = []
    for field in spec.fields:
        item = asdict(field)
        if field.missing_code is not None:
            item['missing_code'] = format(field.missing_code, 'x')
        fields.append(item)
    return json.dumps([spec.word_bits, spec.words_per_row, fields], separators=(',', ':'), sort_keys=True)


def define(path, spec):
    spec = validate_layout(spec)
    definition = _definition(spec)
    with connection(path) as db, transaction(db, write=True):
        prior = db.execute('SELECT definition FROM layouts WHERE layout_id = ?', (spec.layout_id,)).fetchone()
        if prior is None:
            db.execute('INSERT INTO layouts VALUES (?, ?)', (spec.layout_id, definition))
        elif prior['definition'] != definition:
            raise ConflictError(f'layout already bound: {spec.layout_id}')
    return spec.layout_id


def get_layout(db, layout_id):
    row = db.execute('SELECT definition FROM layouts WHERE layout_id = ?', (layout_id,)).fetchone()
    if row is None:
        raise NotFound(f'unknown layout {layout_id}')
    word_bits, words_per_row, fields = json.loads(row['definition'])
    for field in fields:
        if field['missing_code'] is not None:
            field['missing_code'] = int(field['missing_code'], 16)
    return LayoutSpec(layout_id, word_bits, words_per_row, tuple(FieldSpec(**field) for field in fields))
