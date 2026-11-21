from dataclasses import dataclass

from archive_db import WordUnavailable
from layout.codec import decode_field
from layout.fields import fields_for_word
from layout.values import Reading
from words.address import WordAddress
from words.attempt import WordAttempt, latest_attempt
from words.store import read_word


@dataclass(frozen=True)
class FieldInspection:
    field_name: str
    expected: Reading
    actual: Reading | None
    status: str
    pending_request: str | None


@dataclass(frozen=True)
class WordInspection:
    address: WordAddress
    expected_word: int
    actual_word: int | None
    fields: tuple[FieldInspection, ...]
    unassigned_difference: int | None
    last_attempt: WordAttempt | None

    @property
    def settled(self):
        return (self.actual_word is not None and self.unassigned_difference == 0
                and all(item.status == 'settled' for item in self.fields))


def compare_fields(layout, slot, expected_word, actual_word, pending):
    fields = []
    assigned_mask = 0
    for field in fields_for_word(layout, slot):
        assigned_mask |= field.mask
        expected = decode_field(expected_word, field)
        pending_request = pending.get(field.name)
        if actual_word is None:
            actual, status = None, 'unknown'
        else:
            actual = decode_field(actual_word, field)
            if pending_request is not None:
                status = 'pending'
            elif actual == expected:
                status = 'settled'
            else:
                status = 'mismatch'
        fields.append(FieldInspection(field.name, expected, actual, status, pending_request))
    unassigned = None if actual_word is None else (actual_word ^ expected_word) & ~assigned_mask
    return tuple(fields), unassigned


def inspect_word(db, layout, address, expected_word, pending, *, hook=None):
    try:
        actual_word = read_word(db, address, hook=hook)
    except WordUnavailable:
        actual_word = None
    fields, unassigned = compare_fields(layout, address.slot, expected_word, actual_word, pending)
    return WordInspection(address, expected_word, actual_word, fields, unassigned, latest_attempt(db, address))


def fields_match(db, layout, address, expected):
    word = read_word(db, address)
    return all(decode_field(word, field) == expected[field.name]
               for field in fields_for_word(layout, address.slot) if field.name in expected)
