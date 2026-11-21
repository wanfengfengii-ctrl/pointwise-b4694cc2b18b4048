from archive_db import checkpoint, connection, transaction
from layout.codec import merge_fields
from words.attempt import WriteOutcome, find_attempt, latest_attempt
from words.store import commit_word_update, read_word


def apply_field_write(path, layout, address, request_id, phase, qualify, record_step, *, hook=None):
    """Evaluate the field grant, merge one word and record its fact under one write lock."""
    checkpoint(hook, 'before_word_commit', (request_id, phase, address))
    with connection(path) as db, transaction(db, write=True):
        changes = qualify(db)
        if not changes:
            return None
        before = read_word(db, address)
        after = merge_fields(layout, address.slot, before, changes)
        if before == after:
            if phase != 'prepare':
                return None
            prior = latest_attempt(db, address, request_id=request_id, phase=phase)
            if prior is not None:
                return prior
        attempt = commit_word_update(db, address, request_id, phase, before, after, changes)
        record_step(db, attempt)
    checkpoint(hook, 'after_word_commit', attempt)
    return attempt


def check_write_outcome(db, attempt_id):
    if find_attempt(db, attempt_id) is not None:
        return WriteOutcome.COMMITTED
    return WriteOutcome.UNKNOWN
