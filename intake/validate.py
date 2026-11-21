from dataclasses import dataclass

from archive_db import require_name
from intake.manifest import verify_manifest
from layout.codec import validate_word


@dataclass(frozen=True)
class InputRow:
    row_id: str
    page: int
    position: int
    words: tuple[int, ...]


@dataclass(frozen=True)
class ValidatedVolume:
    volume_id: str
    layout_id: str
    rows: tuple[InputRow, ...]


def validate_volume(volume_id, layout, rows, manifest):
    require_name(volume_id, 'volume id')
    accepted = []
    names = set()
    positions = set()
    for row in rows:
        if not isinstance(row, InputRow):
            raise ValueError('expected an InputRow')
        require_name(row.row_id, 'row id')
        if any(type(value) is not int or value < 1 for value in (row.page, row.position)):
            raise ValueError(f'invalid page position for {row.row_id}')
        page_position = (row.page, row.position)
        if row.row_id in names or page_position in positions:
            raise ValueError(f'repeated original identity or page position for {row.row_id}')
        words = tuple(row.words)
        if len(words) != layout.words_per_row:
            raise ValueError(f'incorrect word count for {row.row_id}')
        for word in words:
            validate_word(layout, word)
        accepted.append(InputRow(row.row_id, row.page, row.position, words))
        names.add(row.row_id)
        positions.add(page_position)
    if not accepted:
        raise ValueError('a volume needs at least one original row')
    accepted = tuple(accepted)
    verify_manifest(accepted, manifest)
    return ValidatedVolume(volume_id, layout.layout_id, accepted)
