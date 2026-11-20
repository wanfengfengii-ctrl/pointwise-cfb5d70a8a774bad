import json
import unittest

from handling.operations import load_operation_log, record_operation
from handling.replay import replay_segment
from handling.segments import open_segment
from intake.batches import BatchConflict, get_batch, receive_batch
from intake.imports import import_weighings
from tests import WorkdayCase


class HandlingTests(WorkdayCase):
    def test_v1_mix_split(self):
        self.split_segment()
        log = load_operation_log(self.source, 'day')
        self.scenario(
            'v1', {'batches': [7, 3], 'mix': 10, 'outlets': [6, 4]},
            (('batch-A', 'batch-B'), ('mix-10',)), tuple(op.inputs for op in log.operations),
            (('bag-A', 6), ('bag-B', 4)), replay_segment(self.source, 'day').bags,
            ['intake/batches.py', 'handling/operations.py', 'handling/replay.py'],
            '7 + 3 = 10 = 6 + 4. The two original batches and the intermediate mix are consumed once each.',
        )
        self.assertEqual(tuple((r.batch_id, r.sequence) for r in log.raw_inputs), (('batch-A', 1), ('batch-B', 1)))

    def test_v1_batch_identity(self):
        path = self.source_path.parent / 'tickets.json'
        rows = [
            {'batch_id': 'batch-A', 'net_grams': 7, 'ticket_id': 'ticket-A'},
            {'batch_id': 'batch-B', 'net_grams': 3, 'ticket_id': 'ticket-B'},
            {'batch_id': 'batch-A', 'net_grams': 7, 'ticket_id': 'ticket-A'},
            {'batch_id': 'batch-A', 'net_grams': 8, 'ticket_id': 'ticket-A'},
            {'batch_id': 'batch-A', 'net_grams': 7, 'ticket_id': 'other-ticket'},
        ]
        path.write_text(json.dumps(rows), encoding='utf-8')
        first, second, same, weight_conflict, ticket_conflict = import_weighings(self.source, path, source='scale-day')
        self.assertEqual(first.batch, same.batch)
        self.assertEqual((first.batch.receipt.source, first.batch.receipt.source_line), ('scale-day', 1))
        self.assertEqual(second.batch.receipt.source_line, 2)
        for conflict in (weight_conflict, ticket_conflict):
            self.assertIsNone(conflict.batch)
            self.assertIn('conflicts', conflict.error)
        with self.assertRaises(BatchConflict):
            receive_batch(self.source, 'batch-A', 7, 'third-ticket')
        self.assertEqual(get_batch(self.source, 'batch-A'), first.batch)
        self.assertEqual(self.source.execute(
            'SELECT incoming_grams, incoming_ticket, source_line FROM intake_conflicts ORDER BY conflict_no',
        ).fetchall(), [('8', 'ticket-A', '4'), ('7', 'other-ticket', '5'), ('7', 'third-ticket', None)])
        self.split_segment()
        self.assertEqual(replay_segment(self.source, 'day').bags, (('bag-A', 6), ('bag-B', 4)))

    def test_v1_exact_grams(self):
        zero = receive_batch(self.source, 'zero', 0, 'zero-ticket')
        self.assertEqual(zero.receipt.net_grams, 0)
        large = 10**4500 + 17
        receive_batch(self.source, 'large', large, 'large-ticket')
        self.assertEqual(get_batch(self.source, 'large').net_grams, large)
        for value in (None, -1, 1.0, True, False, '5'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    receive_batch(self.source, 'bad', value, 'bad-ticket')
                self.assertIsNone(get_batch(self.source, 'bad'))
        path = self.source_path.parent / 'invalid.json'
        path.write_text('[{"batch_id":"missing","ticket_id":"ticket"}]', encoding='utf-8')
        result, = import_weighings(self.source, path)
        self.assertIsNone(result.batch)
        self.assertIsNotNone(result.error)
        self.assertIsNone(get_batch(self.source, 'missing'))

    def test_v1_reconsume(self):
        self.split_segment()
        before = load_operation_log(self.source, 'day')
        with self.assertRaisesRegex(ValueError, 'already been consumed'):
            record_operation(self.source, 'day', 'again', 'mix', ['batch-A', 'bag-A'], [('bad', 13)])
        self.assertEqual(load_operation_log(self.source, 'day'), before)
        self.assertEqual(replay_segment(self.source, 'day').bags, (('bag-A', 6), ('bag-B', 4)))
        record_operation(self.source, 'day', 'again', 'mix', ['bag-A', 'bag-B'], [('final', 10)])
        self.assertEqual(replay_segment(self.source, 'day').bags, (('final', 10),))

    def test_v2_bad_split_then_correct_split(self):
        self.mixed_segment()
        with self.assertRaisesRegex(ValueError, 'conserve'):
            record_operation(self.source, 'day', 'split', 'split', ['mix-10'], [('bag-A', 6), ('bag-B', 5)])
        after_error = replay_segment(self.source, 'day')
        correct = record_operation(self.source, 'day', 'split', 'split', ['mix-10'], [('bag-A', 6), ('bag-B', 4)])
        self.assertEqual(correct.sequence, 2)
        self.scenario(
            'v2', {'input': 10, 'attempted': [6, 5], 'corrected': [6, 4]},
            (1, (('mix-10', 10),)), (after_error.through_sequence, after_error.bags),
            (('bag-A', 6), ('bag-B', 4)), replay_segment(self.source, 'day').bags,
            ['handling/operations.py', 'handling/balance.py', 'handling/replay.py'],
            'Six plus five is eleven. The refused operation consumes no material, and the corrected split totals ten.',
        )

    def test_input_scope_and_identity(self):
        self.split_segment()
        open_segment(self.source, 'other')
        receive_batch(self.source, 'free', 4, 'free-ticket')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            record_operation(self.source, 'other', 'mix', 'mix', ['bag-A', 'free'], [('other-bag', 10)])
        with self.assertRaisesRegex(ValueError, 'consumed'):
            record_operation(self.source, 'other', 'split', 'split', ['batch-A'], [('x', 4), ('y', 3)])
        with self.assertRaisesRegex(ValueError, 'duplicate input'):
            record_operation(self.source, 'day', 'mix-2', 'mix', ['bag-A', 'bag-A'], [('again', 12)])
        with self.assertRaisesRegex(ValueError, 'duplicate output'):
            record_operation(self.source, 'day', 'split-2', 'split', ['bag-A'], [('dup', 3), ('dup', 3)])
        with self.assertRaisesRegex(ValueError, 'occupied'):
            record_operation(self.source, 'day', 'mix-2', 'mix', ['bag-A', 'bag-B'], [('mix-10', 10)])
        self.assertEqual(load_operation_log(self.source, 'other').operations, ())
        self.assertEqual(replay_segment(self.source, 'day').bags, (('bag-A', 6), ('bag-B', 4)))


if __name__ == '__main__':
    unittest.main()
