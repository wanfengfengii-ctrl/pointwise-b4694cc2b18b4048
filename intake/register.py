from archive_db import NotFound, connection, require_name, transaction
from corrections.journal import initialise_corrections, migrate_rejection_state
from corrections.pending import initialise_reservations
from delivery.current import read_current_fields
from delivery.snapshot import FixedReport, initialise_reports, save_fixed_report
from intake.archive import get_original, initialise_originals, match_original, save_original
from intake.validate import validate_volume
from layout.registry import get_layout, initialise_layouts
from words.attempt import initialise_attempts
from words.store import initialise_words, install_initial_words


def initialise_archive(path):
    with connection(path) as db:
        mode = db.execute('PRAGMA journal_mode = WAL').fetchone()[0]
        if mode.lower() != 'wal':
            raise ValueError('archive requires a SQLite file supporting WAL')
        # Table rebuilds must run outside a transaction so the foreign_key pragma takes effect.
        migrate_rejection_state(db)
        with transaction(db, write=True):
            initialise_layouts(db)
            initialise_originals(db)
            initialise_words(db)
            initialise_attempts(db)
            initialise_corrections(db)
            initialise_reservations(db)
            initialise_reports(db)


def ingest(path, volume_id, layout_id, rows, manifest):
    require_name(volume_id, 'volume id')
    require_name(layout_id, 'layout id')
    with connection(path) as db, transaction(db, write=True):
        layout = get_layout(db, layout_id)
        validated = validate_volume(volume_id, layout, rows, manifest)
        try:
            original = get_original(db, volume_id)
        except NotFound:
            original = save_original(db, validated)
        else:
            return match_original(original, validated)
        install_initial_words(db, original)
        receipt = original.receipt
        observations = read_current_fields(db, original, layout)
        save_fixed_report(db, FixedReport(receipt.report_id, 'original', volume_id, observations, receipt))
        return receipt
