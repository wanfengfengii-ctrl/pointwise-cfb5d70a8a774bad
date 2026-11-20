CREATE TABLE IF NOT EXISTS accepted_totals (
    acceptance_no INTEGER PRIMARY KEY,
    piece_id TEXT NOT NULL UNIQUE,
    inventory_id TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY,
    piece_id TEXT NOT NULL REFERENCES accepted_totals(piece_id),
    allowed_bags TEXT NOT NULL,
    requested_grams TEXT NOT NULL,
    drawn_grams TEXT NOT NULL,
    short_grams TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('satisfied', 'short'))
);

CREATE TABLE IF NOT EXISTS review_uses (
    review_id INTEGER NOT NULL REFERENCES reviews(review_id),
    position INTEGER NOT NULL CHECK (position >= 0),
    bag_id TEXT NOT NULL,
    net_grams TEXT NOT NULL,
    PRIMARY KEY (review_id, position),
    UNIQUE (review_id, bag_id)
);

CREATE TABLE IF NOT EXISTS review_receipts (
    review_id INTEGER PRIMARY KEY REFERENCES reviews(review_id),
    receipt_no TEXT NOT NULL UNIQUE,
    piece_id TEXT NOT NULL REFERENCES accepted_totals(piece_id),
    inventory_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('satisfied', 'short')),
    requested_grams TEXT NOT NULL,
    drawn_grams TEXT NOT NULL,
    short_grams TEXT NOT NULL
);
