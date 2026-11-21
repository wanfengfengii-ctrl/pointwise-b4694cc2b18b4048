import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from archive_db import ReplyLost
from corrections.recover import CalibrationRejection, resume
from corrections.request import amend
from delivery.current import current, read_calibration
from delivery.reconcile import reconcile
from delivery.snapshot import frozen
from intake.manifest import ManifestEntry
from intake.register import ingest, initialise_archive
from intake.validate import InputRow
from layout.registry import define
from layout.spec import FieldSpec, LayoutSpec
from layout.values import MISSING


LAYOUT = LayoutSpec('calibration-8', 8, 2, (
    FieldSpec('x', 0, 0, 3, 7), FieldSpec('y', 1, 0, 3, 7), FieldSpec('z', 0, 3, 3, 7),
))
ROWS = (InputRow('R-20', 4, 2, (17, 3)), InputRow('R-02', 5, 1, (184, 128)))
MANIFEST = (ManifestEntry('R-20', 2, 4, 2), ManifestEntry('R-02', 2, 5, 1))
A_CHANGES = (('R-20', 'x', 4), ('R-20', 'y', 5))
B_CHANGES = (('R-20', 'z', 6),)


def lose_at(event_name):
    def lose(event, detail):
        if event == event_name:
            raise ReplyLost(event, detail)
    return lose


def reading_group(observations):
    return tuple(None if item.value is MISSING else item.value
                 for item in observations if item.row_id == 'R-20')


def source_group(observations):
    return tuple(item.provenance.request_id for item in observations if item.row_id == 'R-20')


def _scenario(path, action):
    volume = f'day-{action}'
    alpha = f'alpha-{action}'
    beta = f'beta-{action}'
    accepted = ingest(path, volume, LAYOUT.layout_id, ROWS, MANIFEST)
    original = frozen(path, accepted.report_id)
    assert reading_group(original.observations) == (1, 3, 2)
    assert tuple(item.value for item in original.observations[-3:]) == (0, 0, MISSING)
    try:
        amend(path, volume, alpha, A_CHANGES, hook=lose_at('after_word_commit'))
    except ReplyLost as loss:
        assert (loss.detail.before, loss.detail.after) == (17, 20)
    else:
        raise AssertionError('The first word reply was delivered')
    signed_beta = amend(path, volume, beta, B_CHANGES)
    paused = current(path, volume)
    pending = (reading_group(paused), source_group(paused))
    expected_pending = ((1, 3, 6), (None, None, beta))
    assert pending == expected_pending, ('PACKED_CORRECTION_MIXED', pending, expected_pending)
    initialise_archive(path)
    result = resume(path, alpha, action=action)
    final = current(path, volume)
    expected = (4, 5, 6) if action == 'continue' else (1, 3, 6)
    expected_sources = (alpha, alpha, beta) if action == 'continue' else (None, None, beta)
    assert (reading_group(final), source_group(final)) == (expected, expected_sources), (
        'PACKED_CORRECTION_MIXED', reading_group(final), source_group(final))
    assert resume(path, alpha) == result
    assert resume(path, beta) == signed_beta
    ledger = reconcile(path, volume)
    final_words = tuple(word.actual_word for word in ledger.words[:2])
    expected_words = (52, 5) if action == 'continue' else (49, 3)
    assert ledger.settled and final_words == expected_words, ('PACKED_CORRECTION_MIXED', final_words, expected_words)
    assert frozen(path, accepted.report_id) == original
    assert frozen(path, signed_beta.report_id).receipt == signed_beta
    record = {
        'case_id': 'v5.interleaved_disjoint' if action == 'continue' else 'v6.masked_cancel',
        'input': {'original_words': ROWS[0].words, 'alpha': A_CHANGES, 'beta': B_CHANGES, 'action': action},
        'expected': {'values': expected_pending[0], 'sources': expected_pending[1]},
        'actual': {'values': pending[0], 'sources': pending[1]},
        'downstream_expected': {'values': expected, 'sources': expected_sources, 'words': expected_words},
        'downstream_actual': {'values': reading_group(final), 'sources': source_group(final), 'words': final_words},
        'code_paths': ['corrections/recover.py', 'words/write.py', 'delivery/current.py', 'delivery/reconcile.py'],
        'oracle': '首字手算为 x + 8*z，次字低三位为 y。出处由甲乙两单的实际发布切点核对。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


def _calibration_demo(path):
    # Imported lazily so demo.py stays runnable while the fixture evolves independently.
    from calibration_case import (AUXILIARY, LOWER, PAIRED_LAYOUT, ROWS, MANIFEST, UPPER, VOLUME,
                                  install_paired, reading_group, source_group)
    from intake.register import ingest

    def value(item):
        return None if item.value is MISSING else item.value

    def night(volume, fields=('x',)):
        observations, evidence = read_calibration(path, volume, fields)
        return {
            'projected': [(item.row_id, item.field_name, value(item)) for item in observations],
            'evidence': [(item.row_id, item.status,
                          (value(item.lower), item.lower.provenance.request_id,
                           item.lower.provenance.original.address.slot),
                          (value(item.upper), item.upper.provenance.request_id,
                           item.upper.provenance.original.address.slot))
                         for item in evidence],
        }

    # Volume one: ordinary qualified signing and the night-shift, one-sided projection.
    install_paired(path)
    initial_night = night(VOLUME)
    lower = amend(path, VOLUME, 'cal-lower', LOWER)
    auxiliary = amend(path, VOLUME, 'cal-aux', AUXILIARY)
    qualified_night = night(VOLUME)
    # An inverted request is rejected at admission, replayed by the original id and signed nothing.
    admission_rejection = amend(path, VOLUME, 'cal-inverted', (('R-11', 'z', 5), ('R-11', 'x', 6),))

    # Volume two: the prewrite race that the archive must adjudicate at publish time.
    race_volume = 'shift-17-race'
    ingest(path, race_volume, PAIRED_LAYOUT.layout_id, ROWS, MANIFEST)
    try:
        amend(path, race_volume, 'cal-race', LOWER, hook=lose_at('after_word_commit'))
    except ReplyLost as loss:
        loss_event = loss.event
    else:
        raise AssertionError('Expected the in-flight calibration reply to be lost')
    race_auxiliary = amend(path, race_volume, 'race-aux', AUXILIARY)
    upper = amend(path, race_volume, 'race-upper', UPPER)
    # Resuming the original request now projects (4, 2): the gate rejects and rolls the
    # prepared segment back, preserving the ordinary z change and its provenance.
    rejection = resume(path, 'cal-race')
    final_night = night(race_volume)
    ledger = reconcile(path, race_volume)

    record = {
        'case_id': 'v7.calibration_pair_handoff',
        'layout': {'layout_id': PAIRED_LAYOUT.layout_id, 'calibration_pair': list(PAIRED_LAYOUT.calibration_pair)},
        'initial_night': initial_night,
        'signing_volume': {
            'lower': (lower.request_id, lower.publication),
            'ordinary_auxiliary': (auxiliary.request_id, auxiliary.publication),
            'admission_rejection': (admission_rejection.request_id, admission_rejection.volume_id),
            'qualified_night': qualified_night,
        },
        'race_volume': {
            'lost_reply_event': loss_event,
            'upper_signed': (upper.request_id, upper.publication),
            'ordinary_auxiliary': (race_auxiliary.request_id, race_auxiliary.publication),
            'rejection': {'request_id': rejection.request_id, 'volume_id': rejection.volume_id,
                          'replayed_same_result': amend(path, race_volume, 'cal-race', LOWER) == rejection},
            'final_night': final_night,
            'final_r20_values': reading_group(current(path, race_volume)),
            'final_r20_sources': source_group(current(path, race_volume)),
            'physical_words': tuple(word.actual_word for word in ledger.words[:2]),
            'reconcile_settled': ledger.settled,
        },
        'code_paths': ['layout/pairs.py', 'corrections/calibration.py', 'corrections/publish.py',
                       'corrections/recover.py', 'delivery/current.py', 'delivery/evidence.py'],
        'oracle': '下限大于上限即倒置整单拒签；任一侧缺测放行；拒签结清本单位段并保全别单出处，夜班按原行序给两侧值与判定。',
    }
    assert isinstance(admission_rejection, CalibrationRejection)
    assert isinstance(rejection, CalibrationRejection)
    print('POINTWISE_CALIBRATION ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'day.sqlite3'
        initialise_archive(path)
        define(path, LAYOUT)
        _scenario(path, 'continue')
        _scenario(path, 'cancel')
        _calibration_demo(path)


if __name__ == '__main__':
    main()
