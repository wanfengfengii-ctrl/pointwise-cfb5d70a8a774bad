from dataclasses import dataclass


@dataclass(frozen=True)
class Weighing:
    batch_id: str
    net_grams: int
    ticket_id: str


def parse_identifier(value, field: str = 'identifier') -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{field} must be a nonblank identifier')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be valid Unicode') from exc
    return value


def parse_net_grams(value, field: str = 'net grams') -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a nonnegative integer')
    return value


def parse_weighing(batch_id, net_grams, ticket_id) -> Weighing:
    return Weighing(
        parse_identifier(batch_id, 'batch ID'),
        parse_net_grams(net_grams),
        parse_identifier(ticket_id, 'weighing ticket'),
    )


def record_rows(value, field: str) -> tuple:
    from collections.abc import Mapping

    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError(f'{field} must be a collection of entries')
    try:
        return tuple(value)
    except TypeError as exc:
        raise ValueError(f'{field} must be a collection of entries') from exc
