import sqlite3

from exchange.format import TotalsPiece, encode_totals
from exchange.readback import read_issued_totals_for_inventory
from intake.weighing import parse_identifier
from inventory.readback import read_inventory
from storage import write_transaction


def issue_totals(db: sqlite3.Connection, inventory_id: str) -> TotalsPiece:
    key = parse_identifier(inventory_id, 'inventory ID')
    with write_transaction(db):
        existing = read_issued_totals_for_inventory(db, key)
        if existing is not None:
            return existing
        snapshot = read_inventory(db, key)
        if snapshot is None:
            raise LookupError(f'no sealed inventory {key!r}')
        piece = TotalsPiece(f'totals:{key}', key, snapshot.bags)
        db.execute(
            'INSERT INTO issued_totals(piece_id, inventory_id, body) VALUES (?, ?, ?)',
            (piece.piece_id, piece.inventory_id, encode_totals(piece)),
        )
        return piece
