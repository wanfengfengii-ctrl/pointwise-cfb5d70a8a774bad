from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from intake.batches import RawBatch, accept_weighing
from intake.weighing import Weighing, parse_identifier, parse_weighing
from storage import decimal_integer


@dataclass(frozen=True)
class ImportResult:
    source_line: int
    batch: RawBatch | None
    error: str | None


def parse_import_row(row) -> Weighing:
    if not isinstance(row, dict) or row.keys() != {'batch_id', 'net_grams', 'ticket_id'}:
        raise ValueError('each weighing row needs batch_id, net_grams and ticket_id')
    return parse_weighing(row['batch_id'], row['net_grams'], row['ticket_id'])


def _read_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate import field {name!r}')
        result[name] = value
    return result


def import_weighings(db: sqlite3.Connection, path, *, source: str | None = None) -> tuple[ImportResult, ...]:
    file = Path(path)
    origin = parse_identifier(file.name if source is None else source, 'weighing source')
    with file.open(encoding='utf-8') as stream:
        rows = json.load(stream, parse_int=decimal_integer, object_pairs_hook=_read_object)
    if not isinstance(rows, list):
        raise ValueError('the weighing document must be an array of rows')

    results = []
    for line, row in enumerate(rows, 1):
        try:
            weighing = parse_import_row(row)
            batch = accept_weighing(db, weighing, source=origin, source_line=line)
        except ValueError as exc:
            results.append(ImportResult(line, None, str(exc)))
        else:
            results.append(ImportResult(line, batch, None))
    return tuple(results)
