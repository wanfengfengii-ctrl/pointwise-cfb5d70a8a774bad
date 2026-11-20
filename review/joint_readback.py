import json
import sqlite3

from exchange.joint_readback import read_joint_acceptance
from storage import decimal_integer


def read_joint_review(db: sqlite3.Connection, review_id):
    """Return the signed joint review as a dict, ``None`` for an unknown number.

    Non-integer, non-positive or oversized identifiers raise ``ValueError``;
    a positive number with no stored review returns ``None``.  Reopening
    reproduces the original signed body.
    """
    if type(review_id) is not int or review_id < 1:
        raise ValueError('joint review ID must be a positive integer')
    if review_id > 2**63 - 1:
        return None
    row = db.execute(
        '''SELECT piece_id, acceptance_no, inventory_id, status
           FROM joint_reviews WHERE review_id = ?''', (review_id,),
    ).fetchone()
    if row is None:
        return None
    piece_id, acceptance_no, inventory_id, status = row
    accepted = read_joint_acceptance(db, piece_id)
    if accepted is None:
        raise sqlite3.DatabaseError(f'joint review {review_id} has no accepted piece')
    requests = []
    for position, allowed, code, grams in db.execute(
        '''SELECT position, allowed_bags, batch_code, required_grams
           FROM joint_review_requests WHERE review_id = ? ORDER BY position''',
        (review_id,),
    ):
        requests.append({
            'allowed_bags': json.loads(allowed),
            'batch_code': code,
            'required_grams': decimal_integer(grams),
        })
    uses = []
    for index in (0, 1):
        uses.append([
            [bag, decimal_integer(grams)]
            for bag, grams in db.execute(
                '''SELECT bag_id, grams FROM joint_review_uses
                   WHERE review_id = ? AND request_position = ? ORDER BY position''',
                (review_id, index),
            )
        ])
    return {
        'review_id': review_id,
        'piece_id': piece_id,
        'inventory_id': inventory_id,
        'acceptance_no': acceptance_no,
        'requests': requests,
        'status': status,
        'uses': uses,
    }
