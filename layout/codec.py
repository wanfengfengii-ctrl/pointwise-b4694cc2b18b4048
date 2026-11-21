from layout.fields import fields_for_word
from layout.values import decode_value, encode_value


def validate_word(layout, word):
    if type(word) is not int or word < 0 or word.bit_length() > layout.word_bits:
        raise ValueError(f'word does not fit {layout.word_bits} unsigned bits')
    return word


def decode_field(word, field):
    return decode_value(field, (word & field.mask) >> field.offset)


def merge_fields(layout, slot, word, changes):
    result = validate_word(layout, word)
    fields = {field.name: field for field in fields_for_word(layout, slot)}
    for name, value in changes.items():
        if name not in fields:
            raise ValueError(f'{name} does not belong to word slot {slot}')
        field = fields[name]
        result = (result & ~field.mask) | (encode_value(field, value) << field.offset)
    return result
