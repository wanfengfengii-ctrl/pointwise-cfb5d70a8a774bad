from dataclasses import dataclass
import json

from intake.weighing import parse_identifier, parse_net_grams
from storage import decimal_integer, integer_text


V1_FORMAT = 1


@dataclass(frozen=True)
class TotalsPiece:
    piece_id: str
    inventory_id: str
    bags: tuple[tuple[str, int], ...]
    format_version: int = V1_FORMAT


def _check_version(version) -> None:
    if type(version) is not int or version != V1_FORMAT:
        raise ValueError('unsupported totals format')


def _validate_bags(rows) -> tuple[tuple[str, int], ...]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError('bag ledger must be an ordered array')
    seen = set()
    bags = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError('a bag row needs an ID and net grams')
        bag = parse_identifier(row[0], 'bag ID')
        grams = parse_net_grams(row[1], 'bag grams')
        if bag in seen:
            raise ValueError(f'duplicate bag {bag!r}')
        if bags and bag < bags[-1][0]:
            raise ValueError('totals bags must be ordered by ID')
        seen.add(bag)
        bags.append((bag, grams))
    return tuple(bags)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate totals field {name!r}')
        result[name] = value
    return result


def encode_totals(piece: TotalsPiece) -> str:
    _check_version(piece.format_version)
    piece_id = json.dumps(parse_identifier(piece.piece_id, 'piece ID'), ensure_ascii=False)
    inventory_id = json.dumps(parse_identifier(piece.inventory_id, 'inventory ID'), ensure_ascii=False)
    rows = _validate_bags(piece.bags)
    bags = ','.join(
        '[' + json.dumps(bag, ensure_ascii=False) + ',' + integer_text(grams) + ']'
        for bag, grams in rows
    )
    return f'{{"format":{V1_FORMAT},"piece_id":{piece_id},"inventory_id":{inventory_id},"bags":[{bags}]}}'


def decode_totals(body: str | bytes) -> TotalsPiece:
    if not isinstance(body, (str, bytes)):
        raise ValueError('totals body must be JSON text or UTF-8 bytes')
    if isinstance(body, bytes):
        body = body.decode('utf-8')
    payload = json.loads(body, parse_int=decimal_integer, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or payload.keys() != {'format', 'piece_id', 'inventory_id', 'bags'}:
        raise ValueError('invalid totals body fields')
    _check_version(payload['format'])
    return TotalsPiece(
        parse_identifier(payload['piece_id'], 'piece ID'),
        parse_identifier(payload['inventory_id'], 'inventory ID'),
        _validate_bags(payload['bags']),
    )
