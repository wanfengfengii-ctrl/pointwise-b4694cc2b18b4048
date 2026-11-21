import json
from dataclasses import dataclass
from enum import Enum

from words.address import WordAddress


class WriteOutcome(Enum):
    COMMITTED = 'committed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class WordAttempt:
    attempt_id: int
    request_id: str
    phase: str
    address: WordAddress
    before: int
    after: int
    fields: tuple[str, ...]


def initialise_attempts(db):
    db.execute('''CREATE TABLE IF NOT EXISTS word_attempts (
        attempt_id INTEGER PRIMARY KEY,
        request_id TEXT NOT NULL,
        phase TEXT NOT NULL CHECK (phase IN ('prepare', 'cancel', 'settle')),
        volume_id TEXT NOT NULL,
        row_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        before_word TEXT NOT NULL,
        after_word TEXT NOT NULL,
        fields_body TEXT NOT NULL,
        FOREIGN KEY (volume_id, row_id, slot) REFERENCES physical_words(volume_id, row_id, slot)
    )''')
    db.execute('''CREATE INDEX IF NOT EXISTS attempts_by_address
        ON word_attempts(volume_id, row_id, slot, attempt_id)''')


def record_attempt(db, request_id, phase, address, before, after, fields):
    fields = tuple(fields)
    db_cursor = db.execute('''INSERT INTO word_attempts
        (request_id, phase, volume_id, row_id, slot, before_word, after_word, fields_body)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (request_id, phase, *address.parameters(), format(before, 'x'), format(after, 'x'), json.dumps(fields)))
    return WordAttempt(db_cursor.lastrowid, request_id, phase, address, before, after, fields)


def _attempt(row):
    if row is None:
        return None
    address = WordAddress(row['volume_id'], row['row_id'], row['slot'])
    return WordAttempt(row['attempt_id'], row['request_id'], row['phase'], address,
                       int(row['before_word'], 16), int(row['after_word'], 16), tuple(json.loads(row['fields_body'])))


def find_attempt(db, attempt_id):
    row = db.execute('SELECT * FROM word_attempts WHERE attempt_id = ?', (attempt_id,)).fetchone()
    return _attempt(row)


def latest_attempt(db, address, *, request_id=None, phase=None):
    clause = 'volume_id = ? AND row_id = ? AND slot = ?'
    parameters = list(address.parameters())
    if request_id is not None:
        clause += ' AND request_id = ?'
        parameters.append(request_id)
    if phase is not None:
        clause += ' AND phase = ?'
        parameters.append(phase)
    row = db.execute(f'SELECT * FROM word_attempts WHERE {clause} ORDER BY attempt_id DESC LIMIT 1',
                     parameters).fetchone()
    return _attempt(row)
