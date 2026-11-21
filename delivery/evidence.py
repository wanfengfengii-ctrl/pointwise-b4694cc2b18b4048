from dataclasses import dataclass

from delivery.provenance import FieldObservation
from layout.pairs import classify_pair, pair_fields


@dataclass(frozen=True)
class CalibrationEvidence:
    row_id: str
    status: str
    lower: FieldObservation
    upper: FieldObservation


def build_pair_evidence(observations, layout):
    """Combine one already-read snapshot of both sides, in original row order."""
    pair = pair_fields(layout)
    if pair is None:
        return ()
    lower_field, upper_field = pair
    index = {(item.row_id, item.field_name): item for item in observations}
    row_order = []
    seen = set()
    for item in observations:
        if item.row_id not in seen:
            seen.add(item.row_id)
            row_order.append(item.row_id)
    evidence = []
    for row_id in row_order:
        lower = index[(row_id, lower_field.name)]
        upper = index[(row_id, upper_field.name)]
        status = classify_pair(lower.value, upper.value)
        evidence.append(CalibrationEvidence(row_id, status, lower, upper))
    return tuple(evidence)
