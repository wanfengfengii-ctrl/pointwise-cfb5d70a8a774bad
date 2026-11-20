from dataclasses import dataclass
import sqlite3

from intake.receipts import IntakeReceipt, load_intake_receipt, store_intake_receipt
from intake.weighing import Weighing, parse_identifier, parse_weighing
from storage import integer_text, write_transaction


class BatchConflict(ValueError):
    pass


@dataclass(frozen=True)
class RawBatch:
    batch_id: str
    net_grams: int
    ticket_id: str
    receipt: IntakeReceipt


def _from_receipt(receipt: IntakeReceipt) -> RawBatch:
    return RawBatch(receipt.batch_id, receipt.net_grams, receipt.ticket_id, receipt)


def get_batch(db: sqlite3.Connection, batch_id: str) -> RawBatch | None:
    key = parse_identifier(batch_id, 'batch ID')
    receipt = load_intake_receipt(db, key)
    return None if receipt is None else _from_receipt(receipt)


def accept_weighing(
    db: sqlite3.Connection,
    weighing: Weighing,
    *,
    source: str | None = None,
    source_line: int | None = None,
) -> RawBatch:
    if not isinstance(weighing, Weighing):
        raise ValueError('expected a weighing record')
    weighing = parse_weighing(weighing.batch_id, weighing.net_grams, weighing.ticket_id)
    if source is not None or source_line is not None:
        source = parse_identifier(source, 'weighing source')
        if type(source_line) is not int or source_line < 1:
            raise ValueError('source line must be a positive integer')

    with write_transaction(db):
        existing = get_batch(db, weighing.batch_id)
        if existing is None:
            db.execute(
                'INSERT INTO raw_batches(batch_id, net_grams, ticket_id) VALUES (?, ?, ?)',
                (weighing.batch_id, integer_text(weighing.net_grams), weighing.ticket_id),
            )
            receipt = store_intake_receipt(db, weighing, source, source_line)
            return _from_receipt(receipt)
        if (existing.net_grams, existing.ticket_id) == (weighing.net_grams, weighing.ticket_id):
            return existing
        db.execute(
            '''INSERT INTO intake_conflicts
               (batch_id, incoming_grams, incoming_ticket, source, source_line)
               VALUES (?, ?, ?, ?, ?)''',
            (weighing.batch_id, integer_text(weighing.net_grams), weighing.ticket_id,
             source, None if source_line is None else integer_text(source_line)),
        )
    raise BatchConflict(f'batch {weighing.batch_id!r} conflicts with its first receipt')


def receive_batch(db: sqlite3.Connection, batch_id, net_grams, ticket_id) -> RawBatch:
    return accept_weighing(db, parse_weighing(batch_id, net_grams, ticket_id))
