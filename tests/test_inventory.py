import sqlite3

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.readback import read_issued_totals, read_issued_totals_for_inventory
from handling.operations import load_operation_log, record_operation
from handling.replay import replay_segment
from handling.segments import get_segment, open_segment
from intake.batches import get_batch, receive_batch
from inventory.close import close_inventory
from inventory.readback import read_inventory
from storage import initialize_source
from tests import WorkdayCase


class InventoryTests(WorkdayCase):
    def test_v3_seal_issue_and_reopen(self):
        self.split_segment()
        observations = [('bag-B', 4), ('bag-A', 6)]
        snapshot = close_inventory(self.source, 'day', observations).snapshot
        piece = issue_totals(self.source, 'day')
        self.reopen_source()
        self.assertEqual(read_inventory(self.source, 'day'), snapshot)
        self.assertEqual(read_issued_totals(self.source, piece.piece_id), piece)
        self.scenario(
            'v3', {'segment': 'day', 'observations': observations},
            (2, (('bag-A', 6), ('bag-B', 4))), (snapshot.through_sequence, snapshot.bags),
            ('totals:day', 'day', (('bag-A', 6), ('bag-B', 4))),
            (piece.piece_id, piece.inventory_id, issue_totals(self.source, 'day').bags),
            ['handling/replay.py', 'inventory/close.py', 'inventory/readback.py', 'exchange/issue.py'],
            'The second operation produces the only two live bags, in code point order by bag ID.',
        )

    def test_v3_replay_order(self):
        self.split_segment()
        log = load_operation_log(self.source, 'day')
        self.assertEqual(tuple((op.sequence, op.kind) for op in log.operations), ((1, 'mix'), (2, 'split')))
        self.assertEqual(replay_segment(self.source, 'day', through_sequence=1).bags, (('mix-10', 10),))
        original_replay = replay_segment(self.source, 'day')
        self.assertEqual(original_replay.bags, (('bag-A', 6), ('bag-B', 4)))
        result = close_inventory(self.source, 'day', [('bag-B', 4), ('bag-A', 6)])
        self.assertEqual(result.snapshot.bags, original_replay.bags)
        self.assertEqual(result.snapshot.through_sequence, 2)

    def test_v3_closed_segment(self):
        piece = self.two_bag_piece()
        snapshot = read_inventory(self.source, 'day')
        log = load_operation_log(self.source, 'day')
        with self.assertRaisesRegex(ValueError, 'closed'):
            record_operation(self.source, 'day', 'late', 'mix', ['bag-A', 'bag-B'], [('late', 10)])
        with self.assertRaisesRegex(ValueError, 'closed'):
            close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)], inventory_id='late')
        self.reopen_source()
        self.assertEqual(open_segment(self.source, 'day').closed_sequence, 2)
        self.assertEqual(load_operation_log(self.source, 'day'), log)
        self.assertEqual(read_inventory(self.source, 'day'), snapshot)
        self.assertIsNone(read_inventory(self.source, 'late'))
        self.assertEqual(issue_totals(self.source, 'day'), piece)

    def test_v3_snapshot_identity(self):
        self.split_segment()
        old = close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)], inventory_id='old').snapshot
        other_piece = self.four_gram_piece()
        self.assertIsNone(read_issued_totals_for_inventory(self.source, 'old'))
        issued = issue_totals(self.source, 'old')
        self.assertEqual(issued.inventory_id, old.inventory_id)
        self.assertEqual(issued.bags, (('bag-A', 6), ('bag-B', 4)))
        self.assertNotEqual(issued.bags, other_piece.bags)
        self.reopen_source()
        self.assertEqual(read_issued_totals(self.source, issued.piece_id), issued)
        self.assertEqual(issue_totals(self.source, 'old'), issued)

    def test_v3_reinitialize_source(self):
        original = self.two_bag_piece()
        log = load_operation_log(self.source, 'day')
        extra = receive_batch(self.source, 'extra', 9, 'ticket-extra')
        other = self.four_gram_piece()
        initialize_source(self.source)
        initialize_source(self.source)
        self.assertEqual(get_batch(self.source, 'extra'), extra)
        self.assertEqual(load_operation_log(self.source, 'day'), log)
        self.assertEqual(read_inventory(self.source, 'small').bags, (('bag-4', 4),))
        self.assertEqual(read_issued_totals(self.source, original.piece_id), original)
        self.assertEqual(read_issued_totals(self.source, other.piece_id), other)

    def test_v4_difference_then_issue(self):
        self.split_segment()
        result = close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 3)])
        self.assertIsNone(result.snapshot)
        self.assertIsNone(read_inventory(self.source, 'day'))
        self.assertTrue(get_segment(self.source, 'day').is_open)
        with self.assertRaises(LookupError):
            issue_totals(self.source, 'day')
        self.assertIsNone(read_issued_totals_for_inventory(self.source, 'day'))
        close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)])
        self.scenario(
            'v4', {'ledger': [6, 4], 'observed': [6, 3], 'corrected': [6, 4]},
            ((), (), (('bag-B', -1),)),
            (result.difference.missing, result.difference.extra, result.difference.gram_deltas),
            (('bag-A', 6), ('bag-B', 4)), issue_totals(self.source, 'day').bags,
            ['inventory/reconcile.py', 'inventory/close.py', 'exchange/issue.py'],
            'Three minus four is minus one. A corrected four-gram observation agrees exactly.',
        )

    def test_v4_bag_set(self):
        self.split_segment()
        result = close_inventory(self.source, 'day', [('bag-A', 6), ('other', 4)])
        self.assertIsNone(result.snapshot)
        self.assertEqual(result.difference.missing, ('bag-B',))
        self.assertEqual(result.difference.extra, ('other',))
        self.assertEqual(result.difference.gram_deltas, ())
        with self.assertRaises(LookupError):
            issue_totals(self.source, 'day')
        self.assertTrue(get_segment(self.source, 'day').is_open)
        close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)])
        self.assertEqual(issue_totals(self.source, 'day').bags, (('bag-A', 6), ('bag-B', 4)))

    def test_v4_invalid_observation(self):
        self.split_segment()
        invalid = (
            [('bag-A', 6), ('bag-B', 4), ('bag-B', 3)],
            [('bag-A', 6), ('bag-B', None)], [('bag-A', 6), ('bag-B', True)],
            [('bag-A', 6), ('bag-B', 4.0)], [('bag-A', 6), ('bag-B', -1)],
            [('bag-A', 6), ('bag-B',)],
        )
        for observations in invalid:
            with self.subTest(observations=observations):
                with self.assertRaises(ValueError):
                    close_inventory(self.source, 'day', observations)
                self.assertTrue(get_segment(self.source, 'day').is_open)
                self.assertIsNone(read_inventory(self.source, 'day'))
        self.assertIsNotNone(close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)]).snapshot)

    def test_v5_empty_inventory(self):
        receive_batch(self.source, 'waiting', 8, 'waiting-ticket')
        open_segment(self.source, 'empty')
        result = close_inventory(self.source, 'empty', [])
        piece = issue_totals(self.source, 'empty')
        body = '{"format":1,"piece_id":"totals:empty","inventory_id":"empty","bags":[]}'
        self.assertEqual(load_operation_log(self.source, 'empty').raw_inputs, ())
        self.scenario(
            'v5', {'segment': 'empty', 'operations': [], 'observations': [], 'waiting_batch_grams': 8},
            (0, ()), (result.snapshot.through_sequence, result.snapshot.bags),
            body, encode_totals(piece),
            ['handling/replay.py', 'inventory/close.py', 'exchange/format.py', 'exchange/issue.py'],
            'An unapplied intake is not an output of any operation. The empty ledger is explicit.',
        )
        self.assertEqual(self.receive_piece(piece).piece, piece)

    def test_v5_zero_weight_bag(self):
        receive_batch(self.source, 'batch-4', 4, 'ticket-4')
        open_segment(self.source, 'zero-bag')
        record_operation(self.source, 'zero-bag', 'split', 'split', ['batch-4'], [('full', 4), ('zero', 0)])
        omitted = close_inventory(self.source, 'zero-bag', [('full', 4)])
        self.assertEqual(omitted.difference.missing, ('zero',))
        self.assertIsNone(omitted.snapshot)
        result = close_inventory(self.source, 'zero-bag', [('full', 4), ('zero', 0)])
        self.assertEqual(result.snapshot.bags, (('full', 4), ('zero', 0)))
        piece = issue_totals(self.source, 'zero-bag')
        self.assertEqual(self.receive_piece(piece).piece.bags, (('full', 4), ('zero', 0)))

    def test_close_rolls_back_if_segment_update_fails(self):
        self.split_segment()
        self.source.execute('''CREATE TRIGGER prevent_seal BEFORE UPDATE ON operation_segments
                               BEGIN SELECT RAISE(ABORT, 'seal write failed'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'seal write failed'):
            close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)])
        self.assertIsNone(read_inventory(self.source, 'day'))
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM inventory_bags').fetchone()[0], 0)
        self.assertTrue(get_segment(self.source, 'day').is_open)
        self.source.execute('DROP TRIGGER prevent_seal')
        self.assertIsNotNone(close_inventory(self.source, 'day', [('bag-A', 6), ('bag-B', 4)]).snapshot)
