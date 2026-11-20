from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.receive import receive_totals
from handling.operations import record_operation
from handling.segments import open_segment
from intake.imports import import_weighings
from inventory.close import close_inventory
from review.publish import review_total
from review.readback import read_review
from storage import open_source, open_station


def main() -> None:
    samples = Path(__file__).resolve().parent / 'samples'
    day = json.loads((samples / 'workday.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='lanxi-demo-') as temporary:
        directory = Path(temporary)
        station_path = directory / 'station.sqlite3'
        with closing(open_source(directory / 'source.sqlite3')) as source:
            imported = import_weighings(source, samples / 'weighings.json')
            refused = [entry.error for entry in imported if entry.error is not None]
            if refused:
                raise ValueError(f'sample weighings refused: {refused}')
            open_segment(source, day['segment_id'])
            for operation in day['operations']:
                record_operation(source, day['segment_id'], **operation)
            closed = close_inventory(
                source, day['segment_id'], day['observations'], inventory_id=day['inventory_id'],
            )
            if closed.snapshot is None:
                raise ValueError(f'sample inventory differences: {closed.difference}')
            piece = issue_totals(source, closed.snapshot.inventory_id)
            body = encode_totals(piece)

        with closing(open_station(station_path)) as station:
            accepted = receive_totals(station, piece.piece_id, piece.inventory_id, body)
            signed = review_total(station, accepted.piece_id, **day['request'])
        with closing(open_station(station_path)) as station:
            stored = read_review(station, signed.review_id)
            if stored != signed:
                raise RuntimeError('reopened review differs from the signed review')
            uses = [(use.bag_id, use.net_grams) for use in stored.allocation.uses]
            if uses != [('bag-A', 6), ('bag-B', 2)] or stored.allocation.status != 'satisfied':
                raise RuntimeError('sample review did not take the expected eight grams')
            print(json.dumps(asdict(stored), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
