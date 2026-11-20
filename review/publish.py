import json
import sqlite3

from exchange.format import TotalsPiece
from exchange.readback import read_accepted_totals
from review.allocate import Allocation, allocate_total
from review.readback import StoredReview, read_review
from review.receipts import create_review_receipt, store_review_receipt
from review.requests import ReviewRequest, validate_review_request
from storage import integer_text, require_transaction, write_transaction


def publish_review(
    db: sqlite3.Connection, piece: TotalsPiece, request: ReviewRequest, allocation: Allocation,
) -> int:
    """Persist the result of the caller's validation and allocation in its transaction."""
    require_transaction(db)
    if request.piece_id != piece.piece_id:
        raise ValueError('review must use the adopted piece')
    result = db.execute(
        '''INSERT INTO reviews(piece_id, allowed_bags, requested_grams, drawn_grams, short_grams, status)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (piece.piece_id, json.dumps(request.allowed_bags), integer_text(request.required_grams),
         integer_text(allocation.drawn_grams), integer_text(allocation.short_grams), allocation.status),
    )
    review_id = result.lastrowid
    db.executemany(
        'INSERT INTO review_uses(review_id, position, bag_id, net_grams) VALUES (?, ?, ?, ?)',
        [(review_id, index, use.bag_id, integer_text(use.net_grams))
         for index, use in enumerate(allocation.uses)],
    )
    receipt = create_review_receipt(review_id, piece.inventory_id, request, allocation)
    store_review_receipt(db, receipt)
    return review_id


def review_total(db: sqlite3.Connection, piece_id, allowed_bags, required_grams) -> StoredReview:
    with write_transaction(db):
        piece = read_accepted_totals(db, piece_id)
        if piece is None:
            raise LookupError(f'no accepted piece {piece_id!r}')
        request = validate_review_request(piece, piece_id, allowed_bags, required_grams)
        allocation = allocate_total(piece, request)
        review_id = publish_review(db, piece, request, allocation)
        return read_review(db, review_id)
