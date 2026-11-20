"""Joint allocation for two simultaneous留样单 against one accepted V2 piece.

The published caps bound every bag-subset/batch-subset combination.  A pair of
draws is admissible when each request draws only from its own allowed bags and
its own batch code, each reaches its exact whole-gram demand, and every cap
holds for the two draws together.  Every admissible integer draw extends to a
full bag composition consistent with the original ledger, and every
ledger-consistent composition yields its draws, so the caps are exactly the
joint feasibility relation.

A single left-to-right pass can strand grams on a flexible bag and miss a
feasible joint, so the allocator tries a small set of deterministic orders:
both request orders crossed with bag order, reversed bag order, and bag order
sorted by the other request's single-batch capacity.  The first admissible pass
wins; if none does, no joint allocation exists.
"""
from dataclasses import dataclass

from exchange.joint import JointPiece
from review.joint_requests import JointRequest


@dataclass(frozen=True)
class JointUse:
    bag_id: str
    grams: int


@dataclass(frozen=True)
class JointAllocation:
    uses: tuple[tuple[JointUse, ...], tuple[JointUse, ...]]
    status: str


def _room(piece: JointPiece, requests, drawn, index: int, bag: str) -> int:
    """Largest further grams ``index`` may take at ``bag`` without breaking a cap."""
    limit = None
    for entry in piece.evidence['uplifts']:
        if bag not in entry['bags'] or requests[index].batch_code not in entry['batches']:
            continue
        used = 0
        for other in (0, 1):
            if requests[other].batch_code not in entry['batches']:
                continue
            for position, chosen in enumerate(piece.selected):
                if chosen in entry['bags']:
                    used += drawn[other][position]
        room = entry['grams'] - used
        limit = room if limit is None else min(limit, room)
    return 0 if limit is None else max(limit, 0)


def _serve(piece, requests, drawn, order, bag_order) -> bool:
    selected = piece.selected
    for index in order:
        remaining = requests[index].required_grams
        allowed = set(requests[index].allowed_bags)
        for position in bag_order:
            bag = selected[position]
            if not remaining:
                break
            if bag not in allowed:
                continue
            take = min(remaining, _room(piece, requests, drawn, index, bag))
            if take:
                drawn[index][position] += take
                remaining -= take
        if remaining:
            return False
    return True


def _single_cap(piece: JointPiece, batch_code: str, bag: str) -> int:
    for entry in piece.evidence['uplifts']:
        if entry['bags'] == [bag] and entry['batches'] == [batch_code]:
            return entry['grams']
    return 0


def _orders(piece: JointPiece, requests):
    """Deterministic serving strategies; the first admissible one wins."""
    indexes = list(range(len(piece.selected)))
    bags = piece.selected
    by_first = sorted(indexes, key=lambda p: _single_cap(piece, requests[0].batch_code, bags[p]))
    by_second = sorted(indexes, key=lambda p: _single_cap(piece, requests[1].batch_code, bags[p]))
    bag_orders = (
        indexes,
        list(reversed(indexes)),
        by_first, list(reversed(by_first)),
        by_second, list(reversed(by_second)),
    )
    for request_order in ((0, 1), (1, 0)):
        for bag_order in bag_orders:
            yield request_order, bag_order


def allocate_joint(piece: JointPiece, requests: tuple[JointRequest, JointRequest]) -> JointAllocation:
    size = len(piece.selected)
    for request_order, bag_order in _orders(piece, requests):
        drawn = [[0] * size for _ in range(2)]
        if _serve(piece, requests, drawn, request_order, bag_order):
            uses = tuple(
                tuple(
                    JointUse(bag, drawn[index][position])
                    for position, bag in enumerate(piece.selected)
                    if drawn[index][position]
                )
                for index in (0, 1)
            )
            return JointAllocation(uses, 'satisfied')
    return JointAllocation(((), ()), 'short')
