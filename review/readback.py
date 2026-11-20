from dataclasses import dataclass
import json
import sqlite3

from exchange.format import TotalsPiece
from exchange.readback import read_accepted_totals
from review.allocate import Allocation, BagUse
from review.receipts import ReviewReceipt, load_review_receipt
from review.requests import ReviewRequest
from storage import decimal_integer


@dataclass(frozen=True)
class StoredReview:
    review_id: int
    piece: TotalsPiece
    request: ReviewRequest
    allocation: Allocation
    receipt: ReviewReceipt


def read_review(db: sqlite3.Connection, review_id: int) -> StoredReview | None:
    if type(review_id) is not int or review_id < 1:
        raise ValueError('review ID must be a positive integer')
    if review_id > 2**63 - 1:
        return None
    row = db.execute(
        '''SELECT piece_id, allowed_bags, requested_grams, drawn_grams, short_grams, status
           FROM reviews WHERE review_id = ?''',
        (review_id,),
    ).fetchone()
    if row is None:
        return None
    piece_id, allowed, requested, drawn, short, status = row
    piece = read_accepted_totals(db, piece_id)
    receipt = load_review_receipt(db, review_id)
    if piece is None or receipt is None:
        raise sqlite3.DatabaseError(f'review {review_id} has an incomplete stored record')
    uses = tuple(
        BagUse(bag, decimal_integer(grams)) for bag, grams in db.execute(
            'SELECT bag_id, net_grams FROM review_uses WHERE review_id = ? ORDER BY position',
            (review_id,),
        )
    )
    request = ReviewRequest(piece_id, tuple(json.loads(allowed)), decimal_integer(requested))
    allocation = Allocation(uses, decimal_integer(drawn), decimal_integer(short), status)
    return StoredReview(review_id, piece, request, allocation, receipt)
