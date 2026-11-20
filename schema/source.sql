CREATE TABLE IF NOT EXISTS raw_batches (
    batch_id TEXT PRIMARY KEY NOT NULL,
    net_grams TEXT NOT NULL,
    ticket_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_receipts (
    receipt_no INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE REFERENCES raw_batches(batch_id),
    source TEXT,
    source_line TEXT,
    CHECK ((source IS NULL) = (source_line IS NULL))
);

CREATE TABLE IF NOT EXISTS intake_conflicts (
    conflict_no INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES raw_batches(batch_id),
    incoming_grams TEXT NOT NULL,
    incoming_ticket TEXT NOT NULL,
    source TEXT,
    source_line TEXT,
    CHECK ((source IS NULL) = (source_line IS NULL))
);

CREATE TABLE IF NOT EXISTS operation_segments (
    segment_id TEXT PRIMARY KEY NOT NULL,
    closed_sequence INTEGER CHECK (closed_sequence >= 0)
);

CREATE TABLE IF NOT EXISTS operations (
    segment_id TEXT NOT NULL REFERENCES operation_segments(segment_id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    operation_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('split', 'mix')),
    input_nodes TEXT NOT NULL,
    output_ports TEXT NOT NULL,
    PRIMARY KEY (segment_id, sequence),
    UNIQUE (segment_id, operation_id)
);

CREATE TABLE IF NOT EXISTS raw_uses (
    batch_id TEXT PRIMARY KEY NOT NULL REFERENCES raw_batches(batch_id),
    segment_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    FOREIGN KEY (segment_id, sequence) REFERENCES operations(segment_id, sequence)
);
CREATE INDEX IF NOT EXISTS raw_uses_by_segment ON raw_uses(segment_id, sequence);

CREATE TABLE IF NOT EXISTS material_nodes (
    segment_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    net_grams TEXT NOT NULL,
    produced_sequence INTEGER NOT NULL,
    consumed_sequence INTEGER CHECK (consumed_sequence > produced_sequence),
    PRIMARY KEY (segment_id, node_id),
    FOREIGN KEY (segment_id, produced_sequence) REFERENCES operations(segment_id, sequence),
    FOREIGN KEY (segment_id, consumed_sequence) REFERENCES operations(segment_id, sequence)
);

CREATE TABLE IF NOT EXISTS inventories (
    inventory_id TEXT PRIMARY KEY NOT NULL,
    segment_id TEXT NOT NULL UNIQUE REFERENCES operation_segments(segment_id),
    through_sequence INTEGER NOT NULL CHECK (through_sequence >= 0)
);

CREATE TABLE IF NOT EXISTS inventory_bags (
    inventory_id TEXT NOT NULL REFERENCES inventories(inventory_id),
    position INTEGER NOT NULL CHECK (position >= 0),
    bag_id TEXT NOT NULL,
    net_grams TEXT NOT NULL,
    PRIMARY KEY (inventory_id, position),
    UNIQUE (inventory_id, bag_id)
);

CREATE TABLE IF NOT EXISTS issued_totals (
    piece_id TEXT PRIMARY KEY NOT NULL,
    inventory_id TEXT NOT NULL UNIQUE REFERENCES inventories(inventory_id),
    body TEXT NOT NULL
);
