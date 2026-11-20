import sqlite3

from exchange.joint import JointPiece, decode_joint
from intake.weighing import parse_identifier


def read_joint_acceptance(db: sqlite3.Connection, piece_id: str):
    """Return ``(acceptance_no, body, piece)`` for an accepted V2 piece, else ``None``."""
    key = parse_identifier(piece_id, 'piece ID')
    row = db.execute(
        'SELECT acceptance_no, body FROM accepted_joint WHERE piece_id = ?', (key,),
    ).fetchone()
    if row is None:
        return None
    return row[0], row[1], decode_joint(row[1])


def read_accepted_joint(db: sqlite3.Connection, piece_id: str) -> JointPiece | None:
    accepted = read_joint_acceptance(db, piece_id)
    return None if accepted is None else accepted[2]
