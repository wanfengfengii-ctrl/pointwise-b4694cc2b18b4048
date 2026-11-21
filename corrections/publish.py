from archive_db import WordUnavailable, checkpoint, connection, transaction
from corrections.journal import CorrectionReceipt as CorrectionReceipt
from corrections.journal import group_field_evidence, load_request, published_receipt, record_terminal, request_fields
from corrections.pending import check_field_holder, release_fields
from delivery.provenance import FieldObservation, published_provenance
from delivery.selection import order_observations
from delivery.snapshot import FixedReport, save_fixed_report
from intake.archive import get_original
from intake.origin import build_origin_index, locate_original_field
from layout.registry import get_layout
from words.attempt import WriteOutcome
from words.check import fields_match
from words.write import check_write_outcome


def _check_ready(db, request, layout, facts):
    for address, fields in group_field_evidence(facts):
        for item in fields:
            holder = check_field_holder(db, address, item.field_name)
            outcome = check_write_outcome(db, item.prepared_attempt)
            if holder != request.request_id or outcome is not WriteOutcome.COMMITTED:
                raise WordUnavailable(f'preparation not confirmed for {address.row_id}/{item.field_name}')
        if not fields_match(db, layout, address, {item.field_name: item.target for item in fields}):
            raise WordUnavailable(f'prepared readings differ at {address}')


def publish_correction(path, request_id, *, hook=None):
    checkpoint(hook, 'before_publish', request_id)
    with connection(path) as db, transaction(db, write=True):
        request = load_request(db, request_id)
        if request.state == 'published':
            return published_receipt(request)
        if request.state != 'pending':
            return None
        original = get_original(db, request.volume_id)
        layout = get_layout(db, original.layout_id)
        facts = request_fields(db, request_id)
        _check_ready(db, request, layout, facts)
        publication = db.execute('SELECT COALESCE(MAX(publication), 0) + 1 FROM correction_requests').fetchone()[0]
        report_id = f'correction:{request_id}'
        receipt = CorrectionReceipt(request_id, request.volume_id, publication, report_id)
        origins = build_origin_index(original.volume_id, layout, original.rows)
        observations = []
        for item in facts:
            origin = locate_original_field(origins, item.address.row_id, item.field_name)
            source = published_provenance(origin, request_id, publication)
            observations.append(FieldObservation(item.address.row_id, item.field_name, item.target, source))
        ordered = order_observations(original, layout, observations)
        save_fixed_report(db, FixedReport(report_id, 'correction', request.volume_id, ordered, receipt))
        record_terminal(db, request_id, 'published', publication=publication, report_id=report_id)
        release_fields(db, request_id)
    checkpoint(hook, 'after_publish', receipt)
    return receipt
