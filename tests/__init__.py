from contextlib import ExitStack, closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.receive import receive_totals
from handling.operations import record_operation
from handling.segments import open_segment
from intake.batches import receive_batch
from inventory.close import close_inventory
from storage import open_source, open_station


class WorkdayCase(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        directory = Path(self.resources.enter_context(TemporaryDirectory(prefix='lanxi-test-')))
        self.source_path = directory / 'source.sqlite3'
        self.station_path = directory / 'station.sqlite3'
        self.source = self.resources.enter_context(closing(open_source(self.source_path)))
        self.station = self.resources.enter_context(closing(open_station(self.station_path)))

    def reopen_source(self):
        self.source.close()
        self.source = self.resources.enter_context(closing(open_source(self.source_path)))

    def reopen_station(self):
        self.station.close()
        self.station = self.resources.enter_context(closing(open_station(self.station_path)))

    def mixed_segment(self):
        receive_batch(self.source, 'batch-A', 7, 'ticket-A')
        receive_batch(self.source, 'batch-B', 3, 'ticket-B')
        open_segment(self.source, 'day')
        return record_operation(self.source, 'day', 'mix', 'mix', ['batch-A', 'batch-B'], [('mix-10', 10)])

    def split_segment(self):
        self.mixed_segment()
        return record_operation(
            self.source, 'day', 'split', 'split', ['mix-10'], [('bag-A', 6), ('bag-B', 4)],
        )

    def two_bag_piece(self):
        self.split_segment()
        close_inventory(self.source, 'day', [('bag-B', 4), ('bag-A', 6)])
        return issue_totals(self.source, 'day')

    def four_gram_piece(self):
        receive_batch(self.source, 'batch-4', 4, 'ticket-4')
        receive_batch(self.source, 'batch-0', 0, 'ticket-0')
        open_segment(self.source, 'small')
        record_operation(self.source, 'small', 'mix', 'mix', ['batch-4', 'batch-0'], [('bag-4', 4)])
        close_inventory(self.source, 'small', [('bag-4', 4)])
        return issue_totals(self.source, 'small')

    def receive_piece(self, piece):
        return receive_totals(self.station, piece.piece_id, piece.inventory_id, encode_totals(piece))

    def scenario(self, case_id, input_data, expected, actual, downstream_expected, downstream_actual, paths, oracle):
        self.assertEqual(actual, expected)
        self.assertEqual(downstream_actual, downstream_expected)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': case_id,
            'input': input_data,
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': paths,
            'oracle': oracle,
        }, ensure_ascii=False, sort_keys=True), flush=True)
