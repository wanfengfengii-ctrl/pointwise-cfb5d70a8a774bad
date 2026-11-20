from dataclasses import dataclass
import sqlite3

from intake.weighing import Weighing
from storage import decimal_integer, integer_text, require_transaction


@dataclass(frozen=True)
class IntakeReceipt:
    receipt_no: int
    batch_id: str
    net_grams: int
    ticket_id: str
    source: str | None
    source_line: int | None


def store_intake_receipt(
    db: sqlite3.Connection,
    weighing: Weighing,
    source: str | None,
    source_line: int | None,
) -> IntakeReceipt:
    require_transaction(db)
    result = db.execute(
        'INSERT INTO intake_receipts(batch_id, source, source_line) VALUES (?, ?, ?)',
        (weighing.batch_id, source, None if source_line is None else integer_text(source_line)),
    )
    return IntakeReceipt(
        result.lastrowid, weighing.batch_id, weighing.net_grams,
        weighing.ticket_id, source, source_line,
    )


def load_intake_receipt(db: sqlite3.Connection, batch_id: str) -> IntakeReceipt | None:
    row = db.execute(
        '''SELECT r.receipt_no, b.batch_id, b.net_grams, b.ticket_id, r.source, r.source_line
           FROM intake_receipts AS r JOIN raw_batches AS b USING (batch_id)
           WHERE b.batch_id = ?''',
        (batch_id,),
    ).fetchone()
    if row is None:
        return None
    number, key, grams, ticket, source, line = row
    return IntakeReceipt(
        number, key, decimal_integer(grams), ticket, source,
        None if line is None else decimal_integer(line),
    )
