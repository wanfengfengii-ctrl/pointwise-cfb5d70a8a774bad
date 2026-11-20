from contextlib import closing
import json

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.receive import receive_totals
from handling.operations import record_operation
from handling.segments import open_segment
from intake.batches import receive_batch
from inventory.close import close_inventory
from review.publish import review_total
from storage import open_source, open_station


INVENTORY_ID = "sealed-day"
SEGMENT_ID = "day"
CASES = {
    "single": {
        "batches": [("A", 10)],
        "operations": [("split-one", "split", ["A"], [("left", 5), ("right", 5)])],
        "observations": [("left", 5), ("right", 5)],
        "selected": ["left", "right"],
    },
    "mixed": {
        "batches": [("A", 5), ("B", 5)],
        "operations": [
            ("mix-one", "mix", ["A", "B"], [("internal-mix", 10)]),
            ("split-one", "split", ["internal-mix"], [("left", 5), ("right", 5)]),
        ],
        "observations": [("left", 5), ("right", 5)],
        "selected": ["right", "left"],
    },
    "separate": {
        "batches": [("A", 5), ("B", 5), ("zero-A", 0), ("zero-B", 0)],
        "operations": [
            ("mix-A", "mix", ["A", "zero-A"], [("right", 5)]),
            ("mix-B", "mix", ["B", "zero-B"], [("left", 5)]),
        ],
        "observations": [("left", 5), ("right", 5)],
        "selected": ["right", "left"],
    },
    "hidden": {
        "batches": [("A", 5), ("B", 5)],
        "operations": [
            ("reserve", "split", ["A"], [("unselected-reserve", 3), ("internal-rest", 2)]),
            ("mix-one", "mix", ["internal-rest", "B"], [("kept", 7)]),
        ],
        "observations": [("kept", 7), ("unselected-reserve", 3)],
        "selected": ["kept"],
    },
    "shared": {
        "batches": [("A", 4), ("B", 4)],
        "operations": [
            ("split-A", "split", ["A"], [("a-one", 2), ("a-two", 2)]),
            ("split-B", "split", ["B"], [("b-one", 2), ("b-two", 2)]),
            ("mix-one", "mix", ["a-one", "b-one"], [("pool-one", 4)]),
            ("mix-two", "mix", ["a-two", "b-two"], [("other", 4)]),
            ("split-one", "split", ["pool-one"], [("left", 2), ("right", 2)]),
        ],
        "observations": [("left", 2), ("right", 2), ("other", 4)],
        "selected": ["other", "right", "left"],
    },
}


def build_source(db, name):
    case = CASES[name]
    for batch_id, grams in case["batches"]:
        receive_batch(db, batch_id, grams, "ticket-" + batch_id)
    open_segment(db, SEGMENT_ID)
    for operation_id, kind, inputs, outputs in case["operations"]:
        record_operation(db, SEGMENT_ID, operation_id, kind, inputs, outputs)
    closed = close_inventory(db, SEGMENT_ID, case["observations"], inventory_id=INVENTORY_ID)
    if closed.snapshot is None:
        raise RuntimeError(f"{name} could not be sealed: {closed.difference}")
    return closed.snapshot


def v1_body(name):
    with closing(open_source(":memory:")) as db:
        snapshot = build_source(db, name)
        piece = issue_totals(db, snapshot.inventory_id)
        if piece.bags != tuple(sorted(CASES[name]["observations"])):
            raise RuntimeError(f"{name} V1 bag ledger differs from its observations")
        return encode_totals(piece)


def main():
    bodies = {name: v1_body(name) for name in CASES}
    if bodies["mixed"] != bodies["separate"]:
        raise RuntimeError("equal bag ledgers should produce the same V1 body")
    piece = json.loads(bodies["single"])
    with closing(open_station(":memory:")) as db:
        receive_totals(db, piece["piece_id"], piece["inventory_id"], bodies["single"])
        independent = [review_total(db, piece["piece_id"], ["left"], 5) for _ in range(2)]
    if any(report.allocation.status != "satisfied" for report in independent):
        raise RuntimeError("a five-gram V1 request against left should pass independently")
    print(json.dumps({
        "counts_by_inventory": {name: len(json.loads(body)["bags"]) for name, body in bodies.items()},
        "same_v1_body": json.loads(bodies["mixed"]),
        "independent_v1_draws": [
            [[use.bag_id, use.net_grams] for use in report.allocation.uses] for report in independent
        ],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
