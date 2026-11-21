from dataclasses import dataclass

from archive_db import require_name


@dataclass(frozen=True)
class ManifestEntry:
    row_id: str
    word_count: int
    page: int
    position: int


def verify_manifest(rows, manifest):
    entries = tuple(manifest)
    if len(entries) != len(rows):
        raise ValueError('manifest row count differs from payload')
    for number, (row, entry) in enumerate(zip(rows, entries), start=1):
        if not isinstance(entry, ManifestEntry):
            raise ValueError(f'invalid manifest entry at row {number}')
        require_name(entry.row_id, 'manifest row id')
        if any(type(value) is not int or value < 1 for value in (entry.word_count, entry.page, entry.position)):
            raise ValueError(f'invalid manifest count or page position at row {number}')
        expected = ManifestEntry(row.row_id, len(row.words), row.page, row.position)
        if entry != expected:
            raise ValueError(f'manifest differs at original row {number}')
    return entries
