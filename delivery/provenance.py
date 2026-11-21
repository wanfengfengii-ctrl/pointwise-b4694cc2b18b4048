from dataclasses import dataclass

from corrections.journal import ACTIVE_STATES
from intake.origin import OriginalFieldOrigin
from layout.values import Reading


@dataclass(frozen=True)
class FieldProvenance:
    original: OriginalFieldOrigin
    request_id: str | None = None
    publication: int | None = None

    @property
    def kind(self):
        return 'original' if self.request_id is None else 'correction'


@dataclass(frozen=True)
class FieldObservation:
    row_id: str
    field_name: str
    value: Reading
    provenance: FieldProvenance


def published_provenance(origin, request_id, publication):
    return FieldProvenance(origin, request_id, publication)


def select_field_observation(origin, packed_reading, original_reading, evidence):
    if evidence is not None and evidence.state in ACTIVE_STATES:
        value = evidence.before
        source = FieldProvenance(origin, evidence.before_request, evidence.before_publication)
    else:
        if evidence is None:
            expected = original_reading
            source = FieldProvenance(origin)
        else:
            expected = evidence.target
            source = published_provenance(origin, evidence.request_id, evidence.publication)
        # A missing or discrepant physical read cannot change the published value.
        value = packed_reading if packed_reading == expected else expected
    return FieldObservation(origin.address.row_id, origin.field_name, value, source)
