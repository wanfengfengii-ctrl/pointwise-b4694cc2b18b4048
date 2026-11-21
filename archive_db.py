import sqlite3
from contextlib import contextmanager


class ConflictError(ValueError):
    """An identifier or terminal decision is already bound."""


class NotFound(LookupError):
    """The requested archive identity does not exist."""


class WordUnavailable(RuntimeError):
    """The available physical evidence is insufficient to confirm a word."""


class ReplyLost(RuntimeError):
    def __init__(self, event, detail):
        self.event = event
        self.detail = detail
        super().__init__(event, detail)


def require_name(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{label} must be a nonempty string')


def checkpoint(hook, event, detail):
    if hook is not None:
        hook(event, detail)


@contextmanager
def connection(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db, *, write=False):
    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
