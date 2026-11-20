import hashlib
import json
import sqlite3

from exchange.joint import JointPiece, encode_joint, normalise_evidence
from exchange.joint_evidence import capacity_table
from intake.weighing import parse_identifier
from inventory.readback import read_inventory
from storage import write_transaction


def _selected_list(selected_bags) -> tuple[str, ...]:
    if isinstance(selected_bags, (str, bytes, bytearray)):
        raise ValueError('selected bags must be a collection of bag IDs')
    try:
        rows = tuple(selected_bags)
    except TypeError as exc:
        raise ValueError('selected bags must be a collection of bag IDs') from exc
    keys = tuple(parse_identifier(row, 'selected bag') for row in rows)
    if len(set(keys)) != len(keys):
        raise ValueError('selected bags must be distinct')
    return keys


def _piece_id(inventory_id: str, selected: tuple[str, ...]) -> str:
    material = json.dumps([inventory_id, list(selected)], ensure_ascii=False).encode('utf-8')
    return 'joint:' + hashlib.sha256(material).hexdigest()[:32]


def issue_joint(db: sqlite3.Connection, inventory_id, selected_bags) -> str:
    """Issue the fixed V2 joint text for a sealed inventory and ordered selection.

    Reissuing the same inventory and ordered selection returns the original
    text; the piece ID is stable in the ordered selection.
    """
    key = parse_identifier(inventory_id, 'inventory ID')
    selected = _selected_list(selected_bags)
    piece_id = _piece_id(key, selected)
    with write_transaction(db):
        existing = db.execute(
            'SELECT body FROM issued_joint WHERE piece_id = ?', (piece_id,),
        ).fetchone()
        if existing is not None:
            return existing[0]
        snapshot = read_inventory(db, key)
        if snapshot is None:
            raise LookupError(f'no sealed inventory {key!r}')
        bag_grams = dict(snapshot.bags)
        unknown = [bag for bag in selected if bag not in bag_grams]
        if unknown:
            raise ValueError(f'unknown selected bag {unknown[0]!r}')
        codes, entries = capacity_table(db, snapshot, selected)
        evidence = normalise_evidence(entries)
        piece = JointPiece(
            piece_id, key, tuple((bag, bag_grams[bag]) for bag in selected), codes, evidence,
        )
        body = encode_joint(piece)
        db.execute(
            'INSERT INTO issued_joint(piece_id, inventory_id, selected_bags, body) VALUES (?, ?, ?, ?)',
            (piece_id, key, '\x1f'.join(selected), body),
        )
        return body
