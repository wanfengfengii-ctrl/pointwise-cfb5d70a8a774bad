from dataclasses import dataclass

from exchange.format import TotalsPiece
from review.requests import ReviewRequest


@dataclass(frozen=True)
class BagUse:
    bag_id: str
    net_grams: int


@dataclass(frozen=True)
class Allocation:
    uses: tuple[BagUse, ...]
    drawn_grams: int
    short_grams: int
    status: str


def allocate_total(piece: TotalsPiece, request: ReviewRequest) -> Allocation:
    if request.piece_id != piece.piece_id:
        raise ValueError('allocation requires the adopted piece')
    allowed = set(request.allowed_bags)
    remaining = request.required_grams
    uses = []
    for bag, capacity in piece.bags:
        if not remaining:
            break
        if bag in allowed:
            grams = min(remaining, capacity)
            if grams:
                uses.append(BagUse(bag, grams))
                remaining -= grams
    return Allocation(
        tuple(uses), request.required_grams - remaining, remaining,
        'satisfied' if remaining == 0 else 'short',
    )
