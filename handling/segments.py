from dataclasses import dataclass
import sqlite3

from intake.weighing import parse_identifier
from storage import require_transaction, write_transaction


@dataclass(frozen=True)
class OperationSegment:
    segment_id: str
    closed_sequence: int | None

    @property
    def is_open(self) -> bool:
        return self.closed_sequence is None


def get_segment(db: sqlite3.Connection, segment_id: str) -> OperationSegment | None:
    key = parse_identifier(segment_id, 'segment ID')
    row = db.execute(
        'SELECT segment_id, closed_sequence FROM operation_segments WHERE segment_id = ?', (key,),
    ).fetchone()
    return None if row is None else OperationSegment(*row)


def require_open_segment(db: sqlite3.Connection, segment_id: str) -> OperationSegment:
    segment = get_segment(db, segment_id)
    if segment is None:
        raise LookupError(f'unknown segment {segment_id!r}')
    if not segment.is_open:
        raise ValueError(f'segment {segment_id!r} is closed')
    return segment


def open_segment(db: sqlite3.Connection, segment_id: str) -> OperationSegment:
    key = parse_identifier(segment_id, 'segment ID')
    with write_transaction(db):
        db.execute(
            'INSERT INTO operation_segments(segment_id) VALUES (?) ON CONFLICT(segment_id) DO NOTHING',
            (key,),
        )
        return get_segment(db, key)


def seal_segment(db: sqlite3.Connection, segment_id: str, through_sequence: int) -> None:
    require_transaction(db)
    segment = require_open_segment(db, segment_id)
    db.execute(
        'UPDATE operation_segments SET closed_sequence = ? WHERE segment_id = ?',
        (through_sequence, segment.segment_id),
    )
