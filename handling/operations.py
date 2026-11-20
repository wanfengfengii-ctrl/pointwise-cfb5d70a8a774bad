from dataclasses import dataclass
import json
import sqlite3

from handling.balance import OutputPort, check_conservation, check_node_identities
from handling.mixes import prepare_mix
from handling.segments import get_segment, require_open_segment
from handling.splits import prepare_split
from intake.batches import get_batch
from intake.weighing import parse_identifier, parse_net_grams, record_rows
from storage import decimal_integer, integer_text, write_transaction


@dataclass(frozen=True)
class OperationRecord:
    sequence: int
    operation_id: str
    kind: str
    inputs: tuple[str, ...]
    outputs: tuple[OutputPort, ...]


@dataclass(frozen=True)
class RawInput:
    batch_id: str
    net_grams: int
    sequence: int


@dataclass(frozen=True)
class OperationLog:
    segment_id: str
    raw_inputs: tuple[RawInput, ...]
    operations: tuple[OperationRecord, ...]


@dataclass(frozen=True)
class _Input:
    node_id: str
    net_grams: int
    is_raw: bool


def _shape(kind, inputs, outputs) -> tuple[tuple[str, ...], tuple[OutputPort, ...]]:
    if kind not in ('split', 'mix'):
        raise ValueError('operation kind must be split or mix')
    sources = record_rows(inputs, 'operation inputs')
    exits = record_rows(outputs, 'operation outputs')
    if kind == 'split':
        if len(sources) != 1:
            raise ValueError('a split needs exactly one input')
        split = prepare_split(sources[0], exits)
        return (split.input_node,), split.outputs
    if len(exits) != 1:
        raise ValueError('a mix needs exactly one output')
    mix = prepare_mix(sources, exits[0])
    return mix.inputs, (mix.output,)


def _resolve_input(db: sqlite3.Connection, segment_id: str, node_id: str) -> _Input:
    node = db.execute(
        '''SELECT net_grams, consumed_sequence FROM material_nodes
           WHERE segment_id = ? AND node_id = ?''',
        (segment_id, node_id),
    ).fetchone()
    if node is not None:
        grams, consumed = node
        if consumed is not None:
            raise ValueError(f'input {node_id!r} has already been consumed')
        return _Input(node_id, decimal_integer(grams), False)

    batch = get_batch(db, node_id)
    if batch is None:
        raise ValueError(f'input {node_id!r} is unavailable in this segment')
    if db.execute('SELECT 1 FROM raw_uses WHERE batch_id = ?', (node_id,)).fetchone():
        raise ValueError(f'raw batch {node_id!r} has already been consumed')
    return _Input(node_id, batch.net_grams, True)


def _occupied_outputs(db: sqlite3.Connection, segment_id: str, outputs: tuple[OutputPort, ...]):
    for port in outputs:
        occupied = db.execute(
            '''SELECT 1 FROM material_nodes WHERE segment_id = ? AND node_id = ?
               UNION ALL SELECT 1 FROM raw_batches WHERE batch_id = ?''',
            (segment_id, port.node_id, port.node_id),
        ).fetchone()
        if occupied is not None:
            yield port.node_id


def _store_operation(
    db: sqlite3.Connection, segment_id: str, record: OperationRecord, sources: tuple[_Input, ...],
) -> None:
    db.execute(
        '''INSERT INTO operations
           (segment_id, sequence, operation_id, kind, input_nodes, output_ports)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (segment_id, record.sequence, record.operation_id, record.kind, json.dumps(record.inputs),
         json.dumps([(port.node_id, integer_text(port.net_grams)) for port in record.outputs])),
    )
    for source in sources:
        if source.is_raw:
            db.execute(
                'INSERT INTO raw_uses(batch_id, segment_id, sequence) VALUES (?, ?, ?)',
                (source.node_id, segment_id, record.sequence),
            )
        else:
            db.execute(
                '''UPDATE material_nodes SET consumed_sequence = ?
                   WHERE segment_id = ? AND node_id = ?''',
                (record.sequence, segment_id, source.node_id),
            )
    db.executemany(
        '''INSERT INTO material_nodes(segment_id, node_id, net_grams, produced_sequence)
           VALUES (?, ?, ?, ?)''',
        [(segment_id, port.node_id, integer_text(port.net_grams), record.sequence)
         for port in record.outputs],
    )


def record_operation(db: sqlite3.Connection, segment_id, operation_id, kind, inputs, outputs) -> OperationRecord:
    segment_id = parse_identifier(segment_id, 'segment ID')
    operation_id = parse_identifier(operation_id, 'operation ID')
    input_nodes, ports = _shape(kind, inputs, outputs)
    with write_transaction(db):
        require_open_segment(db, segment_id)
        if db.execute(
            'SELECT 1 FROM operations WHERE segment_id = ? AND operation_id = ?', (segment_id, operation_id),
        ).fetchone():
            raise ValueError(f'operation {operation_id!r} already exists in this segment')
        sources = tuple(_resolve_input(db, segment_id, node) for node in input_nodes)
        check_node_identities(input_nodes, ports, _occupied_outputs(db, segment_id, ports))
        check_conservation((source.net_grams for source in sources), ports)
        sequence = db.execute(
            'SELECT COALESCE(MAX(sequence), 0) + 1 FROM operations WHERE segment_id = ?', (segment_id,),
        ).fetchone()[0]
        record = OperationRecord(sequence, operation_id, kind, input_nodes, ports)
        _store_operation(db, segment_id, record, sources)
        return record


def load_operation_log(db: sqlite3.Connection, segment_id: str, *, through_sequence: int | None = None) -> OperationLog:
    segment = get_segment(db, segment_id)
    if segment is None:
        raise LookupError(f'unknown segment {segment_id!r}')
    query = '''SELECT sequence, operation_id, kind, input_nodes, output_ports
               FROM operations WHERE segment_id = ?'''
    params = (segment.segment_id,)
    if through_sequence is not None:
        cutoff = parse_net_grams(through_sequence, 'operation sequence')
        query += ' AND sequence <= ?'
        params += (min(cutoff, 2**63 - 1),)
    rows = db.execute(query + ' ORDER BY sequence', params).fetchall()
    operations = tuple(
        OperationRecord(sequence, key, kind, tuple(json.loads(inputs)),
                        tuple(OutputPort(node, decimal_integer(grams)) for node, grams in json.loads(outputs)))
        for sequence, key, kind, inputs, outputs in rows
    )
    # Capturing the operation prefix first bounds the second read even during an append.
    last = operations[-1].sequence if operations else 0
    roots = db.execute(
        '''SELECT r.batch_id, b.net_grams, r.sequence
           FROM raw_uses AS r JOIN raw_batches AS b USING (batch_id)
           WHERE r.segment_id = ? AND r.sequence <= ? ORDER BY r.sequence, r.batch_id''',
        (segment.segment_id, last),
    )
    raw_inputs = tuple(RawInput(key, decimal_integer(grams), sequence) for key, grams, sequence in roots)
    return OperationLog(segment.segment_id, raw_inputs, operations)
