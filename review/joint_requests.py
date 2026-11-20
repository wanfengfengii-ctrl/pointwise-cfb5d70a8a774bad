from dataclasses import dataclass

from exchange.joint import JointPiece
from intake.weighing import parse_identifier, parse_net_grams, record_rows


_REQUEST_FIELDS = {'allowed_bags', 'batch_code', 'required_grams'}


@dataclass(frozen=True)
class JointRequest:
    allowed_bags: tuple[str, ...]
    batch_code: str
    required_grams: int


def _validate_one(piece: JointPiece, row) -> JointRequest:
    if not isinstance(row, dict) or row.keys() != _REQUEST_FIELDS:
        raise ValueError('a joint request needs allowed_bags, batch_code and required_grams')
    bags = record_rows(row['allowed_bags'], 'allowed bags')
    allowed = {parse_identifier(bag, 'allowed bag') for bag in bags}
    unknown = allowed.difference(piece.selected)
    if unknown:
        raise ValueError(f'unknown allowed bag {min(unknown)!r}')
    code = parse_identifier(row['batch_code'], 'batch code')
    if code not in piece.batch_codes:
        raise ValueError(f'unknown batch code {code!r}')
    grams = parse_net_grams(row['required_grams'], 'requested grams')
    return JointRequest(tuple(sorted(allowed)), code, grams)


def validate_joint_requests(piece: JointPiece, requests) -> tuple[JointRequest, JointRequest]:
    rows = record_rows(requests, 'joint requests')
    if len(rows) != 2:
        raise ValueError('a joint review needs exactly two requests')
    first = _validate_one(piece, rows[0])
    second = _validate_one(piece, rows[1])
    return first, second
