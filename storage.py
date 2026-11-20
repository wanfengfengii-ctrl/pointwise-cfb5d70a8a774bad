from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sqlite3


_SCHEMA_DIR = Path(__file__).resolve().parent / 'schema'


def integer_text(value: int) -> str:
    return str(Decimal(value))


def decimal_integer(text: str) -> int:
    return int(Decimal(text))


@contextmanager
def write_transaction(db: sqlite3.Connection):
    if db.in_transaction:
        raise RuntimeError('this entry point owns its write transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def require_transaction(db: sqlite3.Connection) -> None:
    if not db.in_transaction:
        raise RuntimeError('an active caller transaction is required')


def _initialize(db: sqlite3.Connection, schema_name: str) -> None:
    if db.in_transaction:
        raise RuntimeError('initialization requires an idle connection')
    schema = (_SCHEMA_DIR / schema_name).read_text(encoding='utf-8')
    db.execute('PRAGMA foreign_keys = ON')
    try:
        db.executescript('BEGIN IMMEDIATE;\n' + schema + '\nCOMMIT;')
    except BaseException:
        db.rollback()
        raise


def initialize_source(db: sqlite3.Connection) -> None:
    _initialize(db, 'source.sql')


def initialize_station(db: sqlite3.Connection) -> None:
    _initialize(db, 'station.sql')


def _open(path, initialize) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        initialize(db)
    except BaseException:
        db.close()
        raise
    return db


def open_source(path) -> sqlite3.Connection:
    return _open(path, initialize_source)


def open_station(path) -> sqlite3.Connection:
    return _open(path, initialize_station)
