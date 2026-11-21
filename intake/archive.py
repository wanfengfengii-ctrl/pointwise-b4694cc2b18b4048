import json
from dataclasses import asdict, dataclass

from archive_db import ConflictError, NotFound
from intake.validate import InputRow


@dataclass(frozen=True)
class AcceptanceReceipt:
    volume_id: str
    layout_id: str
    report_id: str
    row_count: int


@dataclass(frozen=True)
class OriginalVolume:
    receipt: AcceptanceReceipt
    rows: tuple[InputRow, ...]

    @property
    def volume_id(self):
        return self.receipt.volume_id

    @property
    def layout_id(self):
        return self.receipt.layout_id


def initialise_originals(db):
    db.execute('''CREATE TABLE IF NOT EXISTS originals (
        volume_id TEXT PRIMARY KEY,
        layout_id TEXT NOT NULL REFERENCES layouts(layout_id),
        rows_body TEXT NOT NULL,
        receipt_body TEXT NOT NULL
    )''')


def save_original(db, validated):
    receipt = AcceptanceReceipt(validated.volume_id, validated.layout_id,
                                f'original:{validated.volume_id}', len(validated.rows))
    body = [(row.row_id, row.page, row.position, [format(word, 'x') for word in row.words])
            for row in validated.rows]
    db.execute('INSERT INTO originals VALUES (?, ?, ?, ?)',
               (validated.volume_id, validated.layout_id, json.dumps(body), json.dumps(asdict(receipt))))
    return OriginalVolume(receipt, validated.rows)


def get_original(db, volume_id):
    row = db.execute('SELECT rows_body, receipt_body FROM originals WHERE volume_id = ?', (volume_id,)).fetchone()
    if row is None:
        raise NotFound(f'unknown volume {volume_id}')
    rows = tuple(InputRow(name, page, position, tuple(int(word, 16) for word in words))
                 for name, page, position, words in json.loads(row['rows_body']))
    return OriginalVolume(AcceptanceReceipt(**json.loads(row['receipt_body'])), rows)


def match_original(original, validated):
    if (original.volume_id, original.layout_id, original.rows) != (
        validated.volume_id, validated.layout_id, validated.rows
    ):
        raise ConflictError(f'volume already bound: {validated.volume_id}')
    return original.receipt
