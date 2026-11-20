from dataclasses import dataclass
from typing import Iterable

from intake.weighing import parse_identifier, parse_net_grams


@dataclass(frozen=True)
class OutputPort:
    node_id: str
    net_grams: int


def parse_output_port(row) -> OutputPort:
    if isinstance(row, OutputPort):
        node_id, grams = row.node_id, row.net_grams
    elif isinstance(row, (tuple, list)) and len(row) == 2:
        node_id, grams = row
    else:
        raise ValueError('an output must contain a node ID and net grams')
    return OutputPort(parse_identifier(node_id, 'output node'), parse_net_grams(grams))


def check_node_identities(
    inputs: tuple[str, ...], outputs: tuple[OutputPort, ...], occupied: Iterable[str] = (),
) -> None:
    input_ids = set(inputs)
    if len(input_ids) != len(inputs):
        raise ValueError('duplicate input node')
    output_ids = {port.node_id for port in outputs}
    if len(output_ids) != len(outputs):
        raise ValueError('duplicate output node')
    collisions = output_ids.intersection(occupied) | output_ids.intersection(input_ids)
    if collisions:
        raise ValueError(f'output node already occupied: {min(collisions)!r}')


def check_conservation(input_grams: Iterable[int], outputs: tuple[OutputPort, ...]) -> None:
    net_in = sum(input_grams)
    net_out = sum(port.net_grams for port in outputs)
    if net_in != net_out:
        raise ValueError('operation does not conserve net grams')
