from archive_db import WordUnavailable, checkpoint
from words.attempt import record_attempt


def initialise_words(db):
    db.execute('''CREATE TABLE IF NOT EXISTS physical_words (
        volume_id TEXT NOT NULL REFERENCES originals(volume_id),
        row_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        packed TEXT NOT NULL,
        PRIMARY KEY (volume_id, row_id, slot)
    )''')


def install_initial_words(db, original):
    entries = ((original.volume_id, row.row_id, slot, format(word, 'x'))
               for row in original.rows for slot, word in enumerate(row.words))
    db.executemany('INSERT INTO physical_words VALUES (?, ?, ?, ?)', entries)


def read_word(db, address, *, hook=None):
    checkpoint(hook, 'before_word_read', address)
    row = db.execute('SELECT packed FROM physical_words WHERE volume_id = ? AND row_id = ? AND slot = ?',
                     address.parameters()).fetchone()
    if row is None:
        raise WordUnavailable(f'word unavailable at {address}')
    return int(row['packed'], 16)


def commit_word_update(db, address, request_id, phase, before, after, fields):
    """Update exactly one word inside the caller's immediate transaction."""
    result = db.execute('''UPDATE physical_words SET packed = ?
        WHERE volume_id = ? AND row_id = ? AND slot = ? AND packed = ?''',
        (format(after, 'x'), *address.parameters(), format(before, 'x')))
    if result.rowcount != 1:
        raise WordUnavailable(f'word changed before update at {address}')
    return record_attempt(db, request_id, phase, address, before, after, fields)
