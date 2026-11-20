import json
import sqlite3

from exchange.joint_readback import read_joint_acceptance
from intake.weighing import parse_identifier
from review.joint_allocate import allocate_joint
from review.joint_readback import read_joint_review
from review.joint_requests import validate_joint_requests
from storage import integer_text, write_transaction


def _store(db: sqlite3.Connection, acceptance, requests, allocation) -> int:
    piece_id, acceptance_no, inventory_id = acceptance
    result = db.execute(
        '''INSERT INTO joint_reviews(piece_id, acceptance_no, inventory_id, status)
           VALUES (?, ?, ?, ?)''',
        (piece_id, acceptance_no, inventory_id, allocation.status),
    )
    review_id = result.lastrowid
    db.executemany(
        '''INSERT INTO joint_review_requests
           (review_id, position, allowed_bags, batch_code, required_grams)
           VALUES (?, ?, ?, ?, ?)''',
        [
            (review_id, position, json.dumps(request.allowed_bags, ensure_ascii=False),
             request.batch_code, integer_text(request.required_grams))
            for position, request in enumerate(requests)
        ],
    )
    rows = []
    for index in (0, 1):
        for position, use in enumerate(allocation.uses[index]):
            rows.append((review_id, index, position, use.bag_id, integer_text(use.grams)))
    db.executemany(
        '''INSERT INTO joint_review_uses
           (review_id, request_position, position, bag_id, grams)
           VALUES (?, ?, ?, ?, ?)''',
        rows,
    )
    return review_id


def review_joint(db: sqlite3.Connection, piece_id, requests) -> dict:
    """Judge two留样单 together against one already-accepted V2 piece.

    Signing keeps the actual accepted piece, both requests and the conclusion.
    A failed write rolls the whole review back; the caller may retry.
    """
    key = parse_identifier(piece_id, 'piece ID')
    with write_transaction(db):
        accepted = read_joint_acceptance(db, key)
        if accepted is None:
            raise LookupError(f'no accepted joint piece {key!r}')
        acceptance_no, body, piece = accepted
        parsed = validate_joint_requests(piece, requests)
        allocation = allocate_joint(piece, parsed)
        review_id = _store(
            db,
            (piece.piece_id, acceptance_no, piece.inventory_id),
            parsed,
            allocation,
        )
        return read_joint_review(db, review_id)
