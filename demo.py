import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive_db import ReplyLost
from corrections.recover import resume
from corrections.request import amend
from delivery.current import current
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


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'day.sqlite3'
        initialise_archive(path)
        define(path, LAYOUT)
        _scenario(path, 'continue')
        _scenario(path, 'cancel')


if __name__ == '__main__':
    main()
