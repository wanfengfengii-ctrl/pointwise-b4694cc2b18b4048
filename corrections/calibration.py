"""Immutable lower/upper pair checks for calibration layouts."""
from dataclasses import dataclass

from delivery.current import read_current_fields
from delivery.provenance import FieldObservation
from delivery.selection import ObservationKey
from layout.pairs import INVERTED, classify_pair, pair_fields


@dataclass(frozen=True)
class PairProjection:
    row_id: str
    status: str
    lower: FieldObservation
    upper: FieldObservation


def pair_target_rows(targets, lower_name, upper_name):
    """Rows touched by the request on the pair fields, with the requested values."""
    overlay = {}
    for row_id, field_name, value in targets:
        if field_name == lower_name or field_name == upper_name:
            overlay.setdefault(row_id, {})[field_name] = value
    return overlay


def project_pairs(db, original, layout, row_ids, overlay=None):
    """Read one published snapshot of both sides and overlay the request's targets."""
    pair = pair_fields(layout)
    if pair is None:
        return ()
    overlay = overlay or {}
    lower_field, upper_field = pair
    keys = []
    for row_id in row_ids:
        keys.append(ObservationKey(row_id, lower_field.name))
        keys.append(ObservationKey(row_id, upper_field.name))
    observations = read_current_fields(db, original, layout, tuple(keys))
    readings = {(item.row_id, item.field_name): item for item in observations}
    projected = []
    for row_id in row_ids:
        lower_obs = readings[(row_id, lower_field.name)]
        upper_obs = readings[(row_id, upper_field.name)]
        lower_value = overlay.get(row_id, {}).get(lower_field.name, lower_obs.value)
        upper_value = overlay.get(row_id, {}).get(upper_field.name, upper_obs.value)
        projected.append(PairProjection(
            row_id, classify_pair(lower_value, upper_value), lower_obs, upper_obs,
        ))
    return tuple(projected)


def evaluate_request(db, original, layout, targets):
    """Project every pair row the request touches; empty when the layout has no pair."""
    pair = pair_fields(layout)
    if pair is None:
        return ()
    lower_field, upper_field = pair
    overlay = pair_target_rows(targets, lower_field.name, upper_field.name)
    if not overlay:
        return ()
    return project_pairs(db, original, layout, tuple(overlay), overlay)


def inverted_rows(db, original, layout, targets):
    return tuple(item.row_id for item in evaluate_request(db, original, layout, targets)
                 if item.status == INVERTED)
