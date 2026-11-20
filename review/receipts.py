from dataclasses import dataclass
import sqlite3

from review.allocate import Allocation
from review.requests import ReviewRequest
from storage import decimal_integer, integer_text, require_transaction


@dataclass(frozen=True)
class ReviewReceipt:
    review_id: int
    receipt_no: str
    piece_id: str
    inventory_id: str
    status: str
    requested_grams: int
    drawn_grams: int
    short_grams: int


def create_review_receipt(
    review_id: int, inventory_id: str, request: ReviewRequest, allocation: Allocation,
) -> ReviewReceipt:
    return ReviewReceipt(
        review_id, f'RV-{review_id}', request.piece_id, inventory_id, allocation.status,
        request.required_grams, allocation.drawn_grams, allocation.short_grams,
    )


def store_review_receipt(db: sqlite3.Connection, receipt: ReviewReceipt) -> None:
    require_transaction(db)
    db.execute(
        '''INSERT INTO review_receipts
           (review_id, receipt_no, piece_id, inventory_id, status, requested_grams, drawn_grams, short_grams)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (receipt.review_id, receipt.receipt_no, receipt.piece_id, receipt.inventory_id, receipt.status,
         integer_text(receipt.requested_grams), integer_text(receipt.drawn_grams),
         integer_text(receipt.short_grams)),
    )


def load_review_receipt(db: sqlite3.Connection, review_id: int) -> ReviewReceipt | None:
    row = db.execute(
        '''SELECT receipt_no, piece_id, inventory_id, status, requested_grams, drawn_grams, short_grams
           FROM review_receipts WHERE review_id = ?''',
        (review_id,),
    ).fetchone()
    if row is None:
        return None
    receipt_no, piece_id, inventory_id, status, requested, drawn, short = row
    return ReviewReceipt(
        review_id, receipt_no, piece_id, inventory_id, status,
        decimal_integer(requested), decimal_integer(drawn), decimal_integer(short),
    )
