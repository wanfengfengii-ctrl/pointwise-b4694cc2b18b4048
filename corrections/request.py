from archive_db import NotFound, connection, require_name, transaction
from corrections.calibration import evaluate_request, pair_fields
from corrections.journal import FieldEvidence, canonical_request, load_request, match_request, record_pending, record_terminal
from corrections.pending import reserve_fields
from corrections.recover import CalibrationRejection, advance_correction, finish_rejection
from delivery.current import read_current_fields
from delivery.selection import ObservationKey
from intake.archive import get_original
from intake.origin import build_origin_index, locate_original_field
from layout.fields import resolve_field
from layout.registry import get_layout
from layout.values import encode_value


def validate_targets(original, layout, targets):
    origins = build_origin_index(original.volume_id, layout, original.rows)
    located = []
    for row_id, name, value in targets:
        field = resolve_field(layout, name)
        origin = locate_original_field(origins, row_id, name)
        encode_value(field, value)
        located.append((origin, value))
    return tuple(sorted(located, key=lambda item: (item[0].row_number, item[0].address.slot)))


def _admit(db, request_id, original, layout, targets):
    located = validate_targets(original, layout, targets)
    keys = tuple(ObservationKey(origin.address.row_id, origin.field_name) for origin, value in located)
    observations = read_current_fields(db, original, layout, keys)
    evidence = tuple(FieldEvidence(request_id, origin.address, origin.field_name, observation.value,
                                   value, observation.provenance.request_id, observation.provenance.publication)
                     for (origin, value), observation in zip(located, observations, strict=True))
    record_pending(db, request_id, original.volume_id, evidence)
    # Ordinary-field-only requests follow the legacy path even when the original row itself is inverted.
    if pair_fields(layout) is None:
        reserve_fields(db, request_id, evidence)
        return 'pending'
    projection = evaluate_request(db, original, layout, targets)
    if any(item.status == 'inverted' for item in projection):
        # No physical segment has been written and no field is reserved; the rejection is already final.
        record_terminal(db, request_id, 'rejected')
        return 'rejected'
    reserve_fields(db, request_id, evidence)
    return 'pending'


def amend(path, volume_id, request_id, changes, *, hook=None):
    require_name(volume_id, 'volume id')
    require_name(request_id, 'request id')
    targets = canonical_request(changes)
    with connection(path) as db, transaction(db, write=True):
        try:
            prior = load_request(db, request_id)
        except NotFound:
            original = get_original(db, volume_id)
            layout = get_layout(db, original.layout_id)
            admitted = _admit(db, request_id, original, layout, targets)
        else:
            match_request(prior, volume_id, targets)
            admitted = prior.state
    if admitted == 'rejected':
        return CalibrationRejection(request_id, volume_id)
    result = advance_correction(path, request_id, hook=hook)
    if isinstance(result, CalibrationRejection):
        return finish_rejection(path, request_id, hook=hook)
    return result
