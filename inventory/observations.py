from dataclasses import dataclass

from intake.weighing import parse_identifier, parse_net_grams, record_rows


@dataclass(frozen=True)
class ObservedBag:
    bag_id: str
    net_grams: int


def read_observations(rows) -> tuple[ObservedBag, ...]:
    seen = set()
    observations = []
    for row in record_rows(rows, 'observations'):
        if isinstance(row, ObservedBag):
            row = (row.bag_id, row.net_grams)
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError('an observation needs a bag ID and net grams')
        bag_id = parse_identifier(row[0], 'observed bag ID')
        grams = parse_net_grams(row[1], 'observed grams')
        if bag_id in seen:
            raise ValueError(f'duplicate observed bag {bag_id!r}')
        seen.add(bag_id)
        observations.append(ObservedBag(bag_id, grams))
    return tuple(observations)
