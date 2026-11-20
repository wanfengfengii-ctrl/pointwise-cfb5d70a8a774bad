from dataclasses import dataclass
import sqlite3

from storage import integer_text, require_transaction


@dataclass(frozen=True)
class InventorySnapshot:
    inventory_id: str
    segment_id: str
    through_sequence: int
    bags: tuple[tuple[str, int], ...]


def save_snapshot(db: sqlite3.Connection, snapshot: InventorySnapshot) -> None:
    require_transaction(db)
    db.execute(
        'INSERT INTO inventories(inventory_id, segment_id, through_sequence) VALUES (?, ?, ?)',
        (snapshot.inventory_id, snapshot.segment_id, snapshot.through_sequence),
    )
    db.executemany(
        '''INSERT INTO inventory_bags(inventory_id, position, bag_id, net_grams)
           VALUES (?, ?, ?, ?)''',
        [(snapshot.inventory_id, position, bag_id, integer_text(grams))
         for position, (bag_id, grams) in enumerate(sorted(snapshot.bags))],
    )
