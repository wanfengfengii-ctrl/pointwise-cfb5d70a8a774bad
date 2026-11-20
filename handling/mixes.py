from dataclasses import dataclass

from handling.balance import OutputPort, check_node_identities, parse_output_port
from intake.weighing import parse_identifier, record_rows


@dataclass(frozen=True)
class MixSpec:
    inputs: tuple[str, ...]
    output: OutputPort


def prepare_mix(inputs, output) -> MixSpec:
    keys = tuple(parse_identifier(node, 'mix input') for node in record_rows(inputs, 'mix inputs'))
    if len(keys) < 2:
        raise ValueError('a mix needs at least two inputs')
    port = parse_output_port(output)
    check_node_identities(keys, (port,))
    return MixSpec(keys, port)
