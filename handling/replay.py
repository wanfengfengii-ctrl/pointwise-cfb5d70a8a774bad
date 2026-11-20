from collections import defaultdict
from dataclasses import dataclass
import sqlite3

from handling.balance import check_conservation, check_node_identities
from handling.operations import load_operation_log


@dataclass(frozen=True)
class ReplayedSegment:
    segment_id: str
    through_sequence: int
    bags: tuple[tuple[str, int], ...]


def replay_segment(db: sqlite3.Connection, segment_id: str, *, through_sequence: int | None = None) -> ReplayedSegment:
    log = load_operation_log(db, segment_id, through_sequence=through_sequence)
    roots_by_sequence = defaultdict(list)
    for root in log.raw_inputs:
        roots_by_sequence[root.sequence].append(root)

    known = set()
    available = {}
    last = 0
    for operation in log.operations:
        if operation.sequence != last + 1:
            raise ValueError('operation log has a sequence gap')
        if operation.kind == 'split' and (len(operation.inputs) != 1 or len(operation.outputs) < 2):
            raise ValueError('invalid split in operation log')
        if operation.kind == 'mix' and (len(operation.inputs) < 2 or len(operation.outputs) != 1):
            raise ValueError('invalid mix in operation log')
        for root in roots_by_sequence.pop(operation.sequence, ()):
            if root.batch_id in known or root.batch_id not in operation.inputs:
                raise ValueError(f'inconsistent raw input {root.batch_id!r} in operation log')
            known.add(root.batch_id)
            available[root.batch_id] = root.net_grams

        check_node_identities(operation.inputs, operation.outputs, known)
        try:
            input_grams = [available[node] for node in operation.inputs]
        except KeyError as exc:
            raise ValueError(f'unavailable input {exc.args[0]!r} in operation log') from exc
        check_conservation(input_grams, operation.outputs)
        for node in operation.inputs:
            del available[node]
        for output in operation.outputs:
            known.add(output.node_id)
            available[output.node_id] = output.net_grams
        last = operation.sequence

    if roots_by_sequence:
        raise ValueError('raw inputs have no matching operation')
    return ReplayedSegment(log.segment_id, last, tuple(sorted(available.items())))
