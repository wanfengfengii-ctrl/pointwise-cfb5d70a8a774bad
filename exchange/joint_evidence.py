"""Capability evidence for a joint piece, computed from the sealed operation graph.

The evidence for a selected-bag set is a table of upper bounds.  For every
nonempty bag subset ``S`` of the selection and every nonempty subset ``T`` of
the published batch codes, the bound is the largest number of grams of batches
``T`` that can jointly reach bags ``S`` through the sealed operation prefix.
It is the maximum flow from batches ``T`` to sinks ``S`` on the material graph
where each node carries its own net grams as capacity.  Unselected bags stay in
the graph, so their physical share of the original batches is present in every
bound without publishing their identity, grams or composition.

Batch codes are the original batch identifiers that can reach any selected bag
along the input/output relation, including zero-gram inputs.
"""
from collections import defaultdict, deque
import itertools
import sqlite3

from handling.operations import load_operation_log
from inventory.snapshot import InventorySnapshot


def sealed_graph(db: sqlite3.Connection, snapshot: InventorySnapshot):
    """Return (node grams, producer->consumer edges, raw batch grams)."""
    log = load_operation_log(db, snapshot.segment_id, through_sequence=snapshot.through_sequence)
    grams = {}
    for root in log.raw_inputs:
        grams[root.batch_id] = root.net_grams
    edges = []
    for operation in log.operations:
        for port in operation.outputs:
            grams[port.node_id] = port.net_grams
        if operation.kind == 'split':
            for port in operation.outputs:
                edges.append((operation.inputs[0], port.node_id))
        else:
            for source in operation.inputs:
                edges.append((source, operation.outputs[0].node_id))
    batches = {root.batch_id: root.net_grams for root in log.raw_inputs}
    return grams, edges, batches


def reachable_batches(edges, batches, sinks) -> tuple[str, ...]:
    """Batch codes with an input/output path to any sink bag, sorted by code point."""
    adjacency = defaultdict(set)
    for producer, consumer in edges:
        adjacency[producer].add(consumer)
    targets = set(sinks)
    codes = []
    for batch_id in batches:
        seen = set()
        stack = [batch_id]
        while stack:
            node = stack.pop()
            for next_node in adjacency[node]:
                if next_node not in seen:
                    seen.add(next_node)
                    stack.append(next_node)
        if seen & targets:
            codes.append(batch_id)
    return tuple(sorted(codes))


class _FlowNetwork:
    """Integer max-flow over a node-capacity material graph (Edmonds-Karp)."""

    def __init__(self, grams, edges):
        self.grams = grams
        self.edges = edges

    def max_flow(self, sources, sinks) -> int:
        capacities = defaultdict(int)
        adjacency = defaultdict(set)

        def add_edge(left, right, capacity):
            capacities[(left, right)] = capacities.get((left, right), 0) + capacity
            adjacency[left].add(right)
            adjacency[right].add(left)

        source = ('source',)
        sink = ('sink',)
        limit = sum(self.grams[batch] for batch in sources)
        for batch in sources:
            add_edge(source, ('in', batch), self.grams[batch])
        for node, grams in self.grams.items():
            add_edge(('in', node), ('out', node), grams)
        for producer, consumer in self.edges:
            add_edge(('out', producer), ('in', consumer), limit)
        for bag in sinks:
            add_edge(('out', bag), sink, self.grams[bag])

        total = 0
        while True:
            parent = {source: None}
            queue = deque([source])
            while queue and sink not in parent:
                left = queue.popleft()
                for right in adjacency[left]:
                    if right not in parent and capacities[(left, right)] > 0:
                        parent[right] = left
                        queue.append(right)
            if sink not in parent:
                return total
            path = []
            node = sink
            while parent[node] is not None:
                path.append((parent[node], node))
                node = parent[node]
            pushed = min(capacities[edge] for edge in path)
            for left, right in path:
                capacities[(left, right)] -= pushed
                capacities[(right, left)] += pushed
            total += pushed


def capacity_table(db, snapshot: InventorySnapshot, selected: tuple[str, ...]):
    """Return (batch codes, evidence entries) for the ordered selection."""
    grams, edges, batches = sealed_graph(db, snapshot)
    codes = reachable_batches(edges, batches, selected)
    network = _FlowNetwork(grams, edges)
    entries = []
    for size in range(1, len(selected) + 1):
        for bags in itertools.combinations(selected, size):
            for count in range(1, len(codes) + 1):
                for chosen in itertools.combinations(codes, count):
                    entries.append((bags, chosen, network.max_flow(chosen, bags)))
    return codes, entries
