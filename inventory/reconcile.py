from dataclasses import dataclass

from handling.replay import ReplayedSegment
from inventory.observations import ObservedBag


@dataclass(frozen=True)
class InventoryDifference:
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    gram_deltas: tuple[tuple[str, int], ...]

    @property
    def matches(self) -> bool:
        return not (self.missing or self.extra or self.gram_deltas)


def compare_bag_ledger(ledger: ReplayedSegment, observations: tuple[ObservedBag, ...]) -> InventoryDifference:
    expected = dict(ledger.bags)
    actual = {bag.bag_id: bag.net_grams for bag in observations}
    missing = tuple(sorted(expected.keys() - actual.keys()))
    extra = tuple(sorted(actual.keys() - expected.keys()))
    common = sorted(expected.keys() & actual.keys())
    differences = tuple((bag, actual[bag] - expected[bag]) for bag in common if actual[bag] != expected[bag])
    return InventoryDifference(missing, extra, differences)
