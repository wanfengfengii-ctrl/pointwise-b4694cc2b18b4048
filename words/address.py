from dataclasses import dataclass

from archive_db import require_name


@dataclass(frozen=True)
class WordAddress:
    volume_id: str
    row_id: str
    slot: int

    def parameters(self):
        return self.volume_id, self.row_id, self.slot


def word_address(volume_id, row_id, slot):
    require_name(volume_id, 'volume id')
    require_name(row_id, 'row id')
    if type(slot) is not int or slot < 0:
        raise ValueError('word slot must be a nonnegative integer')
    return WordAddress(volume_id, row_id, slot)
