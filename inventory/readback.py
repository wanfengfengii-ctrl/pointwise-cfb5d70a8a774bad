import sqlite3

from intake.weighing import parse_identifier
from inventory.snapshot import InventorySnapshot
from storage import decimal_integer


def read_inventory(db: sqlite3.Connection, inventory_id: str) -> InventorySnapshot | None:
    key = parse_identifier(inventory_id, 'inventory ID')
    row = db.execute(
        'SELECT segment_id, through_sequence FROM inventories WHERE inventory_id = ?', (key,),
    ).fetchone()
    if row is None:
        return None
    bags = tuple(
        (bag, decimal_integer(grams)) for bag, grams in db.execute(
            '''SELECT bag_id, net_grams FROM inventory_bags
               WHERE inventory_id = ? ORDER BY position''', (key,),
        )
    )
    return InventorySnapshot(key, row[0], row[1], bags)
