import json
from dataclasses import asdict, dataclass

from archive_db import NotFound, connection, require_name, transaction
from corrections.journal import CorrectionReceipt
from delivery.provenance import FieldObservation, FieldProvenance
from intake.archive import AcceptanceReceipt
from intake.origin import OriginalFieldOrigin
from layout.values import dump_reading, load_reading
from words.address import WordAddress


@dataclass(frozen=True)
class FixedReport:
    report_id: str
    kind: str
    volume_id: str
    observations: tuple[FieldObservation, ...]
    receipt: AcceptanceReceipt | CorrectionReceipt


def initialise_reports(db):
    db.execute('''CREATE TABLE IF NOT EXISTS fixed_reports (
        report_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('original', 'correction')),
        volume_id TEXT NOT NULL REFERENCES originals(volume_id),
        observations TEXT NOT NULL,
        receipt TEXT NOT NULL
    )''')


def _observation_body(observation):
    return {'row_id': observation.row_id, 'field_name': observation.field_name,
            'value': dump_reading(observation.value), 'provenance': asdict(observation.provenance)}


def save_fixed_report(db, report):
    body = [_observation_body(observation) for observation in report.observations]
    db.execute('INSERT INTO fixed_reports VALUES (?, ?, ?, ?, ?)',
               (report.report_id, report.kind, report.volume_id, json.dumps(body), json.dumps(asdict(report.receipt))))


def _load_observation(item):
    provenance = item['provenance']
    origin = provenance['original']
    address = WordAddress(**origin['address'])
    locator = OriginalFieldOrigin(address, origin['field_name'], origin['row_number'], origin['page'], origin['position'])
    source = FieldProvenance(locator, provenance['request_id'], provenance['publication'])
    return FieldObservation(item['row_id'], item['field_name'], load_reading(item['value']), source)


def frozen(path, report_id):
    require_name(report_id, 'report id')
    with connection(path) as db, transaction(db):
        row = db.execute('SELECT * FROM fixed_reports WHERE report_id = ?', (report_id,)).fetchone()
        if row is None:
            raise NotFound(f'unknown report {report_id}')
        receipt_type = AcceptanceReceipt if row['kind'] == 'original' else CorrectionReceipt
        receipt = receipt_type(**json.loads(row['receipt']))
        observations = tuple(_load_observation(item) for item in json.loads(row['observations']))
        return FixedReport(report_id, row['kind'], row['volume_id'], observations, receipt)
