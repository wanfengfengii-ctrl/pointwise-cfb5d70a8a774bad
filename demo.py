"""End-to-end demonstration of the V1 net-weight shift and the V2 joint review.

Every scene seals its own source database, severs the source connection, then
accepts and judges at the external station and reopens its stored result.
"""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.receive import receive_totals
from exchange.joint import decode_joint as read_joint_body
from exchange.joint_issue import issue_joint
from exchange.joint_receive import receive_joint
from handling.operations import record_operation
from handling.segments import open_segment
from intake.imports import import_weighings
from inventory.close import close_inventory
from joint_cases import CASES as JOINT_CASES, build_source
from review.joint_publish import review_joint
from review.joint_readback import read_joint_review
from review.publish import review_total
from review.readback import read_review
from storage import open_source, open_station


def _workday_demo(samples: Path, directory: Path) -> dict:
    day = json.loads((samples / 'workday.json').read_text(encoding='utf-8'))
    station_path = directory / 'v1-station.sqlite3'
    with closing(open_source(directory / 'v1-source.sqlite3')) as source:
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
            raise RuntimeError('reopened V1 review differs from the signed review')
        uses = [(use.bag_id, use.net_grams) for use in stored.allocation.uses]
        if uses != [('bag-A', 6), ('bag-B', 2)] or stored.allocation.status != 'satisfied':
            raise RuntimeError('sample V1 review did not take the expected eight grams')
        return {'v1_review': json.loads(json.dumps(asdict(stored), ensure_ascii=False))}


def _prepare(directory: Path, tag: str, name: str):
    """Seal the source and cut it before the station sees the joint text."""
    with closing(open_source(directory / f'{tag}-source.sqlite3')) as source:
        snapshot = build_source(source, name)
        body = issue_joint(source, snapshot.inventory_id, JOINT_CASES[name]['selected'])
    return snapshot.inventory_id, read_joint_body(body), body


def _scene(directory: Path, tag: str, name: str, first, second) -> dict:
    inventory_id, piece, body = _prepare(directory, tag, name)
    path = directory / f'{tag}-station.sqlite3'
    with closing(open_station(path)) as station:
        acceptance = receive_joint(station, piece.piece_id, piece.inventory_id, body)
        replay = receive_joint(station, piece.piece_id, piece.inventory_id, body)
        if replay != acceptance:
            raise RuntimeError(f'{tag}: duplicate reception was not idempotent')
        signed = review_joint(station, piece.piece_id, [first, second])
        accepted_rows = station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0]
    with closing(open_station(path)) as station:
        restored = read_joint_review(station, signed['review_id'])
        if restored != signed:
            raise RuntimeError(f'{tag} joint review did not survive reopening')
    return {
        'inventory': inventory_id,
        'selected': [bag for bag, _ in piece.bags],
        'public_batch_codes': list(piece.batch_codes),
        'acceptance_no': acceptance,
        'accepted_rows_after_replay': accepted_rows,
        'status': signed['status'],
        'uses': signed['uses'],
        'reopened_matches': restored == signed,
    }


def _failure_scene(directory: Path, tag: str, name: str, first, second) -> dict:
    """Inject a signing write failure, verify no partial result, then retry."""
    inventory_id, piece, body = _prepare(directory, tag, name)
    path = directory / f'{tag}-station.sqlite3'
    with closing(open_station(path)) as station:
        acceptance = receive_joint(station, piece.piece_id, piece.inventory_id, body)
        station.execute(
            '''CREATE TRIGGER demo_refuse_uses BEFORE INSERT ON joint_review_uses
               BEGIN SELECT RAISE(ABORT, 'injected joint-use failure'); END''',
        )
        raised = None
        try:
            review_joint(station, piece.piece_id, [first, second])
        except sqlite3.IntegrityError as error:
            raised = str(error)
        counts = tuple(station.execute(statement).fetchone()[0] for statement in (
            'SELECT COUNT(*) FROM joint_reviews',
            'SELECT COUNT(*) FROM joint_review_requests',
            'SELECT COUNT(*) FROM joint_review_uses',
        ))
        station.execute('DROP TRIGGER demo_refuse_uses')
        retried = review_joint(station, piece.piece_id, [first, second])
    if raised is None:
        raise RuntimeError(f'{tag}: failure injection did not raise')
    if counts != (0, 0, 0):
        raise RuntimeError(f'{tag}: a failed signing left partial rows {counts}')
    return {
        'inventory': inventory_id,
        'acceptance_no': acceptance,
        'failure': raised,
        'rows_after_failure': list(counts),
        'retry_status': retried['status'],
        'retry_uses': retried['uses'],
    }


def main() -> None:
    samples = Path(__file__).resolve().parent / 'samples'
    with TemporaryDirectory(prefix='lanxi-demo-') as temporary:
        directory = Path(temporary)
        report = {'v1_workday': _workday_demo(samples, directory)}

        # Back-mixing contention: both留样单 need A from the same intermediate mix,
        # so each would pass alone but only one bag can supply the shared A.
        report['back_mixing_contention'] = _scene(
            directory, 'contention', 'mixed',
            {'allowed_bags': ['left'], 'batch_code': 'A', 'required_grams': 5},
            {'allowed_bags': ['right'], 'batch_code': 'A', 'required_grams': 5},
        )
        # Unselected-bag occupancy: 3 g of A is already held by an unselected bag,
        # so the selected 7 g bag can only ever contribute 2 g of A.
        report['unselected_occupancy'] = _scene(
            directory, 'occupancy', 'hidden',
            {'allowed_bags': ['kept'], 'batch_code': 'A', 'required_grams': 2},
            {'allowed_bags': ['kept'], 'batch_code': 'A', 'required_grams': 1},
        )
        # The same sealed selection still satisfies two留样单 on distinct batches.
        report['unselected_occupancy_distinct_batches'] = _scene(
            directory, 'distinct', 'hidden',
            {'allowed_bags': ['kept'], 'batch_code': 'A', 'required_grams': 2},
            {'allowed_bags': ['kept'], 'batch_code': 'B', 'required_grams': 5},
        )
        # Rolled-back signing, then a clean retry that keeps the accepted piece.
        report['write_failure_then_retry'] = _failure_scene(
            directory, 'rollback', 'shared',
            {'allowed_bags': ['left'], 'batch_code': 'A', 'required_grams': 2},
            {'allowed_bags': ['other'], 'batch_code': 'A', 'required_grams': 2},
        )

        if report['back_mixing_contention']['status'] != 'short':
            raise RuntimeError('back-mixing contention should be short')
        if report['unselected_occupancy']['status'] != 'short':
            raise RuntimeError('unselected-bag occupancy should be short')
        if report['unselected_occupancy_distinct_batches']['status'] != 'satisfied':
            raise RuntimeError('distinct-batch joint should be satisfied')
        if report['write_failure_then_retry']['retry_status'] != 'satisfied':
            raise RuntimeError('retried joint review should be satisfied')
        for key in ('back_mixing_contention', 'unselected_occupancy',
                    'unselected_occupancy_distinct_batches'):
            if not report[key]['reopened_matches']:
                raise RuntimeError(f'{key} did not reopen identically')
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
