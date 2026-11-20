from dataclasses import dataclass

from exchange.format import TotalsPiece
from intake.weighing import parse_identifier, parse_net_grams, record_rows


@dataclass(frozen=True)
class ReviewRequest:
    piece_id: str
    allowed_bags: tuple[str, ...]
    required_grams: int


def validate_review_request(piece: TotalsPiece, piece_id, allowed_bags, required_grams) -> ReviewRequest:
    key = parse_identifier(piece_id, 'piece ID')
    if key != piece.piece_id:
        raise ValueError('request does not match the accepted piece')
    grams = parse_net_grams(required_grams, 'requested grams')
    allowed = {
        parse_identifier(bag, 'allowed bag') for bag in record_rows(allowed_bags, 'allowed bags')
    }
    unknown = allowed.difference(bag for bag, _ in piece.bags)
    if unknown:
        raise ValueError(f'unknown allowed bag {min(unknown)!r}')
    return ReviewRequest(key, tuple(sorted(allowed)), grams)
