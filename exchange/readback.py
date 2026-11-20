import sqlite3

from exchange.format import TotalsPiece, decode_totals
from intake.weighing import parse_identifier


def _decode_row(row) -> TotalsPiece | None:
    return None if row is None else decode_totals(row[0])


def read_issued_totals(db: sqlite3.Connection, piece_id: str) -> TotalsPiece | None:
    key = parse_identifier(piece_id, 'piece ID')
    row = db.execute('SELECT body FROM issued_totals WHERE piece_id = ?', (key,)).fetchone()
    return _decode_row(row)


def read_issued_totals_for_inventory(db: sqlite3.Connection, inventory_id: str) -> TotalsPiece | None:
    key = parse_identifier(inventory_id, 'inventory ID')
    row = db.execute('SELECT body FROM issued_totals WHERE inventory_id = ?', (key,)).fetchone()
    return _decode_row(row)


def read_acceptance(db: sqlite3.Connection, piece_id: str) -> tuple[int, TotalsPiece] | None:
    key = parse_identifier(piece_id, 'piece ID')
    row = db.execute(
        'SELECT acceptance_no, body FROM accepted_totals WHERE piece_id = ?', (key,),
    ).fetchone()
    return None if row is None else (row[0], decode_totals(row[1]))


def read_accepted_totals(db: sqlite3.Connection, piece_id: str) -> TotalsPiece | None:
    accepted = read_acceptance(db, piece_id)
    return None if accepted is None else accepted[1]
