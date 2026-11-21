from dataclasses import dataclass

from archive_db import NotFound
from words.address import WordAddress, word_address


@dataclass(frozen=True)
class OriginalFieldOrigin:
    address: WordAddress
    field_name: str
    row_number: int
    page: int
    position: int


def build_origin_index(volume_id, layout, rows):
    index = {}
    for number, row in enumerate(rows, start=1):
        for field in layout.fields:
            index[(row.row_id, field.name)] = OriginalFieldOrigin(
                word_address(volume_id, row.row_id, field.slot), field.name, number, row.page, row.position
            )
    return index


def locate_original_field(index, row_id, field_name):
    try:
        return index[(row_id, field_name)]
    except KeyError as exc:
        raise NotFound(f'unknown original field {row_id}/{field_name}') from exc
