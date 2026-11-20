from dataclasses import dataclass
import sqlite3

from exchange.format import TotalsPiece, decode_totals, encode_totals
from exchange.readback import read_acceptance
from intake.weighing import parse_identifier
from storage import write_transaction


class PieceConflict(ValueError):
    pass


@dataclass(frozen=True)
class TotalsReception:
    acceptance_no: int
    piece: TotalsPiece

    @property
    def piece_id(self) -> str:
        return self.piece.piece_id


def receive_totals(db: sqlite3.Connection, piece_id, inventory_id, body) -> TotalsReception:
    piece_id = parse_identifier(piece_id, 'received piece ID')
    inventory_id = parse_identifier(inventory_id, 'received inventory ID')
    piece = decode_totals(body)
    if (piece.piece_id, piece.inventory_id) != (piece_id, inventory_id):
        raise ValueError('received identifiers do not match the totals body')
    with write_transaction(db):
        accepted = read_acceptance(db, piece_id)
        if accepted is not None:
            acceptance_no, prior_piece = accepted
            if prior_piece != piece:
                raise PieceConflict(f'piece {piece_id!r} conflicts with its first reception')
            return TotalsReception(acceptance_no, prior_piece)
        result = db.execute(
            '''INSERT INTO accepted_totals(piece_id, inventory_id, body)
               VALUES (?, ?, ?)''',
            (piece_id, inventory_id, encode_totals(piece)),
        )
        return TotalsReception(result.lastrowid, piece)
