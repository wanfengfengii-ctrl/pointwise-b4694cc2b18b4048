from archive_db import NotFound, connection, require_name, transaction
from corrections.journal import FieldEvidence, canonical_request, load_request, match_request, record_pending
from corrections.pending import reserve_fields
from corrections.recover import advance_correction
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
    reserve_fields(db, request_id, evidence)


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
            _admit(db, request_id, original, layout, targets)
        else:
            match_request(prior, volume_id, targets)
    return advance_correction(path, request_id, hook=hook)
