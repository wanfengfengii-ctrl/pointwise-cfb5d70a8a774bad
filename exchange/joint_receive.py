import sqlite3

from exchange.joint import decode_joint, encode_joint
from exchange.joint_readback import read_joint_acceptance
from exchange.receive import PieceConflict
from intake.weighing import parse_identifier
from storage import write_transaction


def receive_joint(db: sqlite3.Connection, piece_id, inventory_id, body) -> int:
    """Accept a V2 joint text (or UTF-8 bytes) at the external station.

    Returns the positive acceptance number.  Replaying the same piece ID with
    the same content returns the first acceptance number; different valid
    content under the same piece ID raises ``PieceConflict`` and keeps the
    first piece.  Malformed pieces and V1 bodies raise ``ValueError`` and leave
    nothing behind.
    """
    piece_id = parse_identifier(piece_id, 'received piece ID')
    inventory_id = parse_identifier(inventory_id, 'received inventory ID')
    piece = decode_joint(body)
    if (piece.piece_id, piece.inventory_id) != (piece_id, inventory_id):
        raise ValueError('received identifiers do not match the joint body')
    canonical = encode_joint(piece)
    with write_transaction(db):
        accepted = read_joint_acceptance(db, piece_id)
        if accepted is not None:
            number, prior_body, prior_piece = accepted
            if prior_piece == piece:
                return number
            raise PieceConflict(f'joint piece {piece_id!r} conflicts with its first reception')
        result = db.execute(
            '''INSERT INTO accepted_joint(piece_id, inventory_id, body)
               VALUES (?, ?, ?)''',
            (piece_id, inventory_id, canonical),
        )
        return result.lastrowid
