from dataclasses import dataclass

from archive_db import require_name


@dataclass(frozen=True)
class FieldSpec:
    name: str
    slot: int
    offset: int
    width: int
    missing_code: int | None = None

    @property
    def mask(self):
        return ((1 << self.width) - 1) << self.offset


@dataclass(frozen=True)
class LayoutSpec:
    layout_id: str
    word_bits: int
    words_per_row: int
    fields: tuple[FieldSpec, ...]
    calibration_pair: tuple[str, str] | None = None


def validate_pair(fields, pair):
    if pair is None:
        return None
    if not isinstance(pair, (tuple, list)) or len(pair) != 2 or any(not isinstance(name, str) for name in pair):
        raise ValueError('calibration_pair must be two field names (lower, upper)')
    lower, upper = pair
    names = {field.name for field in fields}
    if lower not in names or upper not in names:
        raise ValueError('calibration_pair must reference existing layout fields')
    if lower == upper:
        raise ValueError('calibration_pair lower and upper must be different fields')
    return lower, upper


def validate_layout(spec):
    if not isinstance(spec, LayoutSpec):
        raise ValueError('expected a LayoutSpec')
    require_name(spec.layout_id, 'layout id')
    if type(spec.word_bits) is not int or spec.word_bits < 1:
        raise ValueError('word width must be a positive integer')
    if type(spec.words_per_row) is not int or spec.words_per_row < 1:
        raise ValueError('words per row must be a positive integer')
    fields = tuple(spec.fields)
    if not fields:
        raise ValueError('a layout needs at least one field')
    names = set()
    occupied = {}
    for field in fields:
        if not isinstance(field, FieldSpec):
            raise ValueError('expected a FieldSpec')
        require_name(field.name, 'field name')
        if field.name in names:
            raise ValueError(f'duplicate field {field.name}')
        if type(field.slot) is not int or not 0 <= field.slot < spec.words_per_row:
            raise ValueError(f'invalid word slot for {field.name}')
        if type(field.offset) is not int or type(field.width) is not int:
            raise ValueError(f'invalid bit segment for {field.name}')
        if field.offset < 0 or field.width < 1 or field.offset + field.width > spec.word_bits:
            raise ValueError(f'bit segment out of range for {field.name}')
        code = field.missing_code
        if code is not None and (type(code) is not int or code < 0 or code.bit_length() > field.width):
            raise ValueError(f'missing code out of range for {field.name}')
        word_mask = occupied.get(field.slot, 0)
        if field.mask & word_mask:
            raise ValueError(f'overlapping bit segment for {field.name}')
        occupied[field.slot] = word_mask | field.mask
        names.add(field.name)
    pair = validate_pair(fields, spec.calibration_pair)
    return LayoutSpec(spec.layout_id, spec.word_bits, spec.words_per_row, fields, pair)
