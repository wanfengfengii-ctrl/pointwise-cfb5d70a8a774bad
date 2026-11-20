from dataclasses import dataclass

from handling.balance import OutputPort, check_node_identities, parse_output_port
from intake.weighing import parse_identifier, record_rows


@dataclass(frozen=True)
class SplitSpec:
    input_node: str
    outputs: tuple[OutputPort, ...]


def prepare_split(input_node, outputs) -> SplitSpec:
    key = parse_identifier(input_node, 'split input')
    ports = tuple(parse_output_port(row) for row in record_rows(outputs, 'split outputs'))
    if len(ports) < 2:
        raise ValueError('a split needs at least two outputs')
    check_node_identities((key,), ports)
    return SplitSpec(key, ports)
