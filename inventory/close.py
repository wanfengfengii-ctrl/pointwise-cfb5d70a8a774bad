from dataclasses import dataclass
import sqlite3

from handling.replay import replay_segment
from handling.segments import require_open_segment, seal_segment
from intake.weighing import parse_identifier
from inventory.observations import read_observations
from inventory.reconcile import InventoryDifference, compare_bag_ledger
from inventory.snapshot import InventorySnapshot, save_snapshot
from storage import write_transaction


@dataclass(frozen=True)
class CloseResult:
    snapshot: InventorySnapshot | None
    difference: InventoryDifference


def close_inventory(db: sqlite3.Connection, segment_id, observations, *, inventory_id=None) -> CloseResult:
    segment_id = parse_identifier(segment_id, 'segment ID')
    key = segment_id if inventory_id is None else parse_identifier(inventory_id, 'inventory ID')
    observed_bags = read_observations(observations)
    with write_transaction(db):
        require_open_segment(db, segment_id)
        replay = replay_segment(db, segment_id)
        difference = compare_bag_ledger(replay, observed_bags)
        if not difference.matches:
            return CloseResult(None, difference)
        snapshot = InventorySnapshot(key, segment_id, replay.through_sequence, replay.bags)
        save_snapshot(db, snapshot)
        seal_segment(db, segment_id, replay.through_sequence)
        return CloseResult(snapshot, difference)
