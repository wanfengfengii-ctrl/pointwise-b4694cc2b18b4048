from dataclasses import dataclass

from archive_db import ConflictError, NotFound, require_name
from layout.values import MISSING, Reading, dump_reading, load_reading
from words.address import WordAddress


ACTIVE_STATES = ('pending', 'cancelling')


@dataclass(frozen=True)
class CorrectionIdentity:
    request_id: str
    volume_id: str
    state: str
    publication: int | None
    report_id: str | None
    targets: tuple[tuple[str, str, Reading], ...]


@dataclass(frozen=True)
class CorrectionReceipt:
    request_id: str
    volume_id: str
    publication: int
    report_id: str


@dataclass(frozen=True)
class FieldEvidence:
    request_id: str
    address: WordAddress
    field_name: str
    before: Reading
    target: Reading
    before_request: str | None
    before_publication: int | None
    state: str = 'pending'
    publication: int | None = None
    prepared_attempt: int | None = None


def _create_correction_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS correction_requests (
        request_id TEXT PRIMARY KEY,
        volume_id TEXT NOT NULL REFERENCES originals(volume_id),
        state TEXT NOT NULL CHECK (state IN ('pending', 'cancelling', 'cancelled', 'rejected', 'published')),
        publication INTEGER UNIQUE,
        report_id TEXT UNIQUE,
        CHECK ((state = 'published' AND publication IS NOT NULL AND report_id IS NOT NULL)
            OR (state <> 'published' AND publication IS NULL AND report_id IS NULL))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS correction_fields (
        request_id TEXT NOT NULL REFERENCES correction_requests(request_id),
        row_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        field_name TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        before_value TEXT,
        target_value TEXT,
        before_request TEXT,
        before_publication INTEGER,
        prepared_attempt INTEGER REFERENCES word_attempts(attempt_id),
        PRIMARY KEY (request_id, row_id, field_name)
    )''')
    db.execute('''CREATE INDEX IF NOT EXISTS evidence_by_field
        ON correction_fields(row_id, field_name, request_id)''')
    db.execute('''CREATE TABLE IF NOT EXISTS correction_steps (
        request_id TEXT NOT NULL,
        row_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        phase TEXT NOT NULL,
        attempt_id INTEGER NOT NULL REFERENCES word_attempts(attempt_id),
        PRIMARY KEY (request_id, row_id, field_name, phase),
        FOREIGN KEY (request_id, row_id, field_name) REFERENCES correction_fields(request_id, row_id, field_name)
    )''')


def initialise_corrections(db):
    _create_correction_tables(db)


def migrate_rejection_state(db):
    """Upgrade archives created before calibration rejections so the new state is legal."""
    table = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'correction_requests'").fetchone()
    if table is None:
        return
    check = db.execute("SELECT sql FROM sqlite_master WHERE name = 'correction_requests'").fetchone()[0]
    if "'rejected'" in check:
        return
    # PRAGMA foreign_keys cannot change inside a transaction; the connection is in autocommit here.
    # Every table referencing correction_requests must be rebuilt so its foreign key follows the
    # new parent table rather than the renamed legacy one.
    db.execute('PRAGMA foreign_keys = OFF')
    try:
        db.execute('ALTER TABLE correction_requests RENAME TO correction_requests_legacy')
        db.execute('ALTER TABLE correction_fields RENAME TO correction_fields_legacy')
        db.execute('ALTER TABLE correction_steps RENAME TO correction_steps_legacy')
        reservations = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'field_reservations'").fetchone()
        if reservations is not None:
            db.execute('ALTER TABLE field_reservations RENAME TO field_reservations_legacy')
            db.execute('DROP INDEX IF EXISTS reservations_by_holder')
        _create_correction_tables(db)
        db.execute('''INSERT INTO correction_requests
            (request_id, volume_id, state, publication, report_id)
            SELECT request_id, volume_id, state, publication, report_id FROM correction_requests_legacy''')
        db.execute('''INSERT INTO correction_fields
            (request_id, row_id, slot, field_name, ordinal, before_value, target_value,
             before_request, before_publication, prepared_attempt)
            SELECT request_id, row_id, slot, field_name, ordinal, before_value, target_value,
                   before_request, before_publication, prepared_attempt FROM correction_fields_legacy''')
        db.execute('''INSERT INTO correction_steps
            (request_id, row_id, field_name, phase, attempt_id)
            SELECT request_id, row_id, field_name, phase, attempt_id FROM correction_steps_legacy''')
        if reservations is not None:
            db.execute('''CREATE TABLE field_reservations (
                volume_id TEXT NOT NULL REFERENCES originals(volume_id),
                row_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                holder TEXT NOT NULL REFERENCES correction_requests(request_id),
                PRIMARY KEY (volume_id, row_id, field_name))''')
            db.execute('''INSERT INTO field_reservations (volume_id, row_id, field_name, holder)
                SELECT volume_id, row_id, field_name, holder FROM field_reservations_legacy''')
            db.execute('CREATE INDEX reservations_by_holder ON field_reservations(holder)')
        db.execute('DROP TABLE correction_steps_legacy')
        db.execute('DROP TABLE correction_fields_legacy')
        db.execute('DROP TABLE correction_requests_legacy')
        if reservations is not None:
            db.execute('DROP TABLE field_reservations_legacy')
    finally:
        db.execute('PRAGMA foreign_keys = ON')


def canonical_request(changes):
    targets = {}
    for item in changes:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError('every change must contain a row, field and reading')
        row, field, value = item
        require_name(row, 'row id')
        require_name(field, 'field name')
        if value is not MISSING and (type(value) is not int or value < 0):
            raise ValueError('expected a nonnegative integer or MISSING')
        if (row, field) in targets:
            raise ValueError(f'repeated correction target {row}/{field}')
        targets[(row, field)] = value
    if not targets:
        raise ValueError('a correction needs at least one target')
    return tuple((row, field, value) for (row, field), value in sorted(targets.items()))


def match_request(request, volume_id, targets):
    if request.volume_id != volume_id or request.targets != targets:
        raise ConflictError(f'request already bound: {request.request_id}')


def load_request(db, request_id):
    row = db.execute('SELECT * FROM correction_requests WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        raise NotFound(f'unknown request {request_id}')
    targets = db.execute('SELECT row_id, field_name, target_value FROM correction_fields WHERE request_id = ?',
                         (request_id,))
    canonical = tuple(sorted((item['row_id'], item['field_name'], load_reading(item['target_value']))
                             for item in targets))
    return CorrectionIdentity(request_id, row['volume_id'], row['state'], row['publication'], row['report_id'], canonical)


def record_pending(db, request_id, volume_id, evidence):
    db.execute("INSERT INTO correction_requests (request_id, volume_id, state) VALUES (?, ?, 'pending')",
               (request_id, volume_id))
    parameters = ((request_id, item.address.row_id, item.address.slot, item.field_name, number,
                   dump_reading(item.before), dump_reading(item.target), item.before_request, item.before_publication)
                  for number, item in enumerate(evidence))
    db.executemany('''INSERT INTO correction_fields
        (request_id, row_id, slot, field_name, ordinal, before_value, target_value, before_request, before_publication)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', parameters)


def record_field_step(db, attempt):
    for field in attempt.fields:
        key = (attempt.request_id, attempt.address.row_id, field)
        db.execute('''INSERT INTO correction_steps VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(request_id, row_id, field_name, phase) DO UPDATE SET attempt_id = excluded.attempt_id''',
            (*key, attempt.phase, attempt.attempt_id))
        if attempt.phase == 'prepare':
            db.execute('''UPDATE correction_fields SET prepared_attempt = ?
                WHERE request_id = ? AND row_id = ? AND field_name = ?''', (attempt.attempt_id, *key))


def record_terminal(db, request_id, state, *, publication=None, report_id=None):
    predecessor = {
        'cancelling': 'pending',
        'cancelled': 'cancelling',
        'rejected': 'pending',
        'published': 'pending',
    }[state]
    changed = db.execute('''UPDATE correction_requests SET state = ?, publication = ?, report_id = ?
        WHERE request_id = ? AND state = ?''', (state, publication, report_id, request_id, predecessor))
    if changed.rowcount != 1:
        raise ConflictError(f'cannot move {request_id} from {predecessor} to {state}')


def _field_evidence(row):
    return FieldEvidence(row['request_id'], WordAddress(row['volume_id'], row['row_id'], row['slot']),
                         row['field_name'], load_reading(row['before_value']), load_reading(row['target_value']),
                         row['before_request'], row['before_publication'], row['state'], row['publication'],
                         row['prepared_attempt'])


def read_field_evidence(db, address, field_name, *, published_only=False):
    states = ('published',) if published_only else (*ACTIVE_STATES, 'published')
    placeholders = ', '.join('?' for state in states)
    row = db.execute(f'''SELECT f.*, r.volume_id, r.state, r.publication
        FROM correction_fields f JOIN correction_requests r USING (request_id)
        WHERE r.volume_id = ? AND f.row_id = ? AND f.slot = ? AND f.field_name = ?
            AND r.state IN ({placeholders})
        ORDER BY (r.publication IS NULL) DESC, r.publication DESC LIMIT 1''',
        (*address.parameters(), field_name, *states)).fetchone()
    return None if row is None else _field_evidence(row)


def request_fields(db, request_id):
    rows = db.execute('''SELECT f.*, r.volume_id, r.state, r.publication
        FROM correction_fields f JOIN correction_requests r USING (request_id)
        WHERE f.request_id = ? ORDER BY f.ordinal''', (request_id,))
    return tuple(_field_evidence(row) for row in rows)


def group_field_evidence(fields):
    groups = {}
    for item in fields:
        groups.setdefault(item.address, []).append(item)
    return groups.items()


def published_receipt(request):
    if request.state != 'published':
        raise ConflictError(f'request not published: {request.request_id}')
    return CorrectionReceipt(request.request_id, request.volume_id, request.publication, request.report_id)
