from archive_db import NotFound


def resolve_field(layout, name):
    for field in layout.fields:
        if field.name == name:
            return field
    raise NotFound(f'unknown field {name}')


def ordered_fields(layout, names=None):
    if names is None:
        return layout.fields
    if isinstance(names, str):
        raise ValueError('field selection must be a sequence of names')
    selected = set()
    for name in names:
        selected.add(resolve_field(layout, name).name)
    return tuple(field for field in layout.fields if field.name in selected)


def fields_for_word(layout, slot):
    if type(slot) is not int or not 0 <= slot < layout.words_per_row:
        raise ValueError(f'unknown word slot {slot}')
    return tuple(field for field in layout.fields if field.slot == slot)
