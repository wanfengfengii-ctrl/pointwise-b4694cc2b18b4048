from dataclasses import dataclass

from archive_db import ConflictError, WordUnavailable, connection, require_name, transaction
from corrections.journal import (group_field_evidence, load_request, published_receipt, read_field_evidence,
                                 record_field_step, record_terminal, request_fields)
from corrections.pending import check_field_holder, release_fields
from corrections.publish import publish_correction
from intake.archive import get_original
from layout.registry import get_layout
from words.check import fields_match
from words.write import apply_field_write


@dataclass(frozen=True)
class CancelledCorrection:
    request_id: str
    volume_id: str


def _load_work(db, request):
    original = get_original(db, request.volume_id)
    return get_layout(db, original.layout_id), request_fields(db, request.request_id)


def _eligible_changes(db, request_id, address, fields, phase):
    expected_state = {'prepare': 'pending', 'cancel': 'cancelling', 'settle': 'published'}[phase]
    if load_request(db, request_id).state != expected_state:
        return {}
    changes = {}
    for item in fields:
        holder = check_field_holder(db, address, item.field_name)
        if phase == 'settle':
            if holder is not None:
                continue
            published = read_field_evidence(db, address, item.field_name, published_only=True)
            if published is not None and published.request_id == request_id:
                changes[item.field_name] = item.target
        elif holder == request_id:
            changes[item.field_name] = item.before if phase == 'cancel' else item.target
    return changes


def _drive_words(path, request, layout, facts, phase, hook):
    for address, fields in group_field_evidence(facts):
        def qualify(db):
            return _eligible_changes(db, request.request_id, address, fields, phase)

        try:
            apply_field_write(path, layout, address, request.request_id, phase, qualify, record_field_step, hook=hook)
        except WordUnavailable:
            if phase != 'settle':
                raise
            # The signed receipt remains available while this address needs inspection.


def settle_published(path, request_id, *, hook=None):
    with connection(path) as db, transaction(db):
        request = load_request(db, request_id)
        receipt = published_receipt(request)
        layout, facts = _load_work(db, request)
    _drive_words(path, request, layout, facts, 'settle', hook)
    return receipt


def cancel_pending(path, request_id, *, hook=None):
    with connection(path) as db, transaction(db, write=True):
        request = load_request(db, request_id)
        result = CancelledCorrection(request_id, request.volume_id)
        if request.state == 'published':
            raise ConflictError(f'published request cannot be cancelled: {request_id}')
        if request.state == 'cancelled':
            return result
        if request.state == 'pending':
            record_terminal(db, request_id, 'cancelling')
        layout, facts = _load_work(db, request)
    _drive_words(path, request, layout, facts, 'cancel', hook)
    with connection(path) as db, transaction(db, write=True):
        if load_request(db, request_id).state == 'cancelled':
            return result
        facts = request_fields(db, request_id)
        for address, fields in group_field_evidence(facts):
            if any(check_field_holder(db, address, item.field_name) != request_id for item in fields):
                raise WordUnavailable(f'cleanup ownership not confirmed at {address}')
            expected = {item.field_name: item.before for item in fields}
            if not fields_match(db, layout, address, expected):
                raise WordUnavailable(f'cleanup readings differ at {address}')
        record_terminal(db, request_id, 'cancelled')
        release_fields(db, request_id)
    return result


def advance_correction(path, request_id, *, hook=None):
    with connection(path) as db, transaction(db):
        request = load_request(db, request_id)
        if request.state == 'pending':
            layout, facts = _load_work(db, request)
    if request.state == 'published':
        return settle_published(path, request_id, hook=hook)
    if request.state == 'cancelled':
        return CancelledCorrection(request_id, request.volume_id)
    if request.state == 'pending':
        _drive_words(path, request, layout, facts, 'prepare', hook)
        receipt = publish_correction(path, request_id, hook=hook)
        if receipt is not None:
            return receipt
    return cancel_pending(path, request_id, hook=hook)


def resume(path, request_id, *, action='continue', hook=None):
    require_name(request_id, 'request id')
    if action == 'continue':
        return advance_correction(path, request_id, hook=hook)
    if action == 'cancel':
        return cancel_pending(path, request_id, hook=hook)
    raise ValueError(f'unknown recovery action {action}')
