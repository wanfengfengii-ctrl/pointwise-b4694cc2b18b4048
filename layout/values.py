from enum import Enum


class MissingReading(Enum):
    MISSING = 'missing'


MISSING = MissingReading.MISSING
Reading = int | MissingReading


def decode_value(field, code):
    return MISSING if code == field.missing_code else code


def encode_value(field, value):
    if value is MISSING:
        if field.missing_code is None:
            raise ValueError(f'{field.name} has no missing code')
        return field.missing_code
    if type(value) is not int or value < 0 or value.bit_length() > field.width:
        raise ValueError(f'reading out of range for {field.name}')
    if value == field.missing_code:
        raise ValueError(f'use MISSING for the reserved code of {field.name}')
    return value


def dump_reading(value):
    return None if value is MISSING else format(value, 'x')


def load_reading(stored):
    return MISSING if stored is None else int(stored, 16)
