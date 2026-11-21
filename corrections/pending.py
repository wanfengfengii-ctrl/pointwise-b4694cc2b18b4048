from archive_db import ConflictError


class FieldsBusy(ConflictError):
    def __init__(self, address, field_name, holder):
        self.address = address
        self.field_name = field_name
        self.holder = holder
        super().__init__(f'{address.row_id}/{field_name} is pending with {holder}')


def initialise_reservations(db):
    db.execute('''CREATE TABLE IF NOT EXISTS field_reservations (
        volume_id TEXT NOT NULL REFERENCES originals(volume_id),
        row_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        holder TEXT NOT NULL REFERENCES correction_requests(request_id),
        PRIMARY KEY (volume_id, row_id, field_name)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS reservations_by_holder ON field_reservations(holder)')


def reserve_fields(db, request_id, fields):
    fields = tuple(fields)
    for item in fields:
        holder = check_field_holder(db, item.address, item.field_name)
        if holder is not None:
            raise FieldsBusy(item.address, item.field_name, holder)
    db.executemany('INSERT INTO field_reservations VALUES (?, ?, ?, ?)',
                   ((item.address.volume_id, item.address.row_id, item.field_name, request_id) for item in fields))


def check_field_holder(db, address, field_name):
    entry = db.execute('''SELECT holder FROM field_reservations
        WHERE volume_id = ? AND row_id = ? AND field_name = ?''',
        (address.volume_id, address.row_id, field_name)).fetchone()
    return None if entry is None else entry['holder']


def release_fields(db, request_id):
    db.execute('DELETE FROM field_reservations WHERE holder = ?', (request_id,))
