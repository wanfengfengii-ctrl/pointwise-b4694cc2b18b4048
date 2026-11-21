from dataclasses import dataclass

from layout.fields import ordered_fields


@dataclass(frozen=True)
class ObservationKey:
    row_id: str
    field_name: str


def resolve_selection(original, layout, fields=None):
    selected = ordered_fields(layout, fields)
    return tuple(ObservationKey(row.row_id, field.name) for row in original.rows for field in selected)


def order_observations(original, layout, observations):
    row_order = {row.row_id: index for index, row in enumerate(original.rows)}
    field_order = {field.name: index for index, field in enumerate(layout.fields)}
    return tuple(sorted(observations, key=lambda item: (row_order[item.row_id], field_order[item.field_name])))
