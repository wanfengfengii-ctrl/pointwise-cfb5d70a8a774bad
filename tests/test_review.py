import sqlite3

from exchange.readback import read_accepted_totals
from review.publish import review_total
from review.readback import read_review
from storage import initialize_station
from tests import WorkdayCase


class ReviewTests(WorkdayCase):
    def _uses(self, signed):
        return tuple((use.bag_id, use.net_grams) for use in signed.allocation.uses)

    def _counts(self):
        return tuple(self.station.execute(statement).fetchone()[0] for statement in (
            'SELECT COUNT(*) FROM reviews',
            'SELECT COUNT(*) FROM review_uses',
            'SELECT COUNT(*) FROM review_receipts',
        ))

    def _fail_receipt(self):
        self.station.execute(
            '''CREATE TRIGGER refuse_receipt BEFORE INSERT ON review_receipts
               BEGIN
                   SELECT CASE WHEN EXISTS (SELECT 1 FROM review_uses WHERE review_id = NEW.review_id)
                               THEN RAISE(ABORT, 'receipt write failed after uses')
                               ELSE RAISE(ABORT, 'receipt write reached before uses') END;
               END''',
        )

    def test_v7_offline_review_and_reopen(self):
        piece = self.two_bag_piece()
        self.source.close()
        self.receive_piece(piece)
        signed = review_total(self.station, piece.piece_id, ['bag-A', 'bag-B'], 8)
        self.reopen_station()
        restored = read_review(self.station, signed.review_id)
        self.assertEqual(restored, signed)
        self.assertEqual(restored.piece, piece)
        self.assertEqual(restored.request.allowed_bags, ('bag-A', 'bag-B'))
        self.assertEqual(restored.request.required_grams, 8)
        self.assertEqual((restored.receipt.requested_grams, restored.receipt.drawn_grams, restored.receipt.short_grams), (8, 8, 0))
        self.scenario(
            'v7', {'bags': [6, 4], 'required': 8, 'source_closed': True},
            (('bag-A', 6), ('bag-B', 2)), self._uses(signed),
            ('totals:day', 'day', 'satisfied', (('bag-A', 6), ('bag-B', 2))),
            (restored.piece.piece_id, restored.receipt.inventory_id, restored.receipt.status, self._uses(restored)),
            ['exchange/receive.py', 'review/allocate.py', 'review/publish.py', 'review/readback.py'],
            'The first bag contributes six grams and the second supplies the remaining two grams.',
        )

    def test_v7_package_order(self):
        piece = self.two_bag_piece()
        self.receive_piece(piece)
        first = review_total(self.station, piece.piece_id, ['bag-A', 'bag-B'], 8)
        second = review_total(self.station, piece.piece_id, ['bag-B', 'bag-A', 'bag-A'], 8)
        self.assertEqual(first.request, second.request)
        self.assertNotEqual(first.review_id, second.review_id)
        self.source.close()
        self.reopen_station()
        for signed in (first, second):
            restored = read_review(self.station, signed.review_id)
            self.assertEqual(restored.receipt, signed.receipt)
            self.assertEqual(self._uses(restored), (('bag-A', 6), ('bag-B', 2)))

    def test_v7_request_rules(self):
        piece = self.two_bag_piece()
        self.receive_piece(piece)
        with self.assertRaises(LookupError):
            review_total(self.station, 'missing-piece', [], 0)
        with self.assertRaisesRegex(ValueError, 'unknown allowed bag'):
            review_total(self.station, piece.piece_id, ['bag-A', 'absent'], 0)
        for value in (None, -1, 0.0, True, '1'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    review_total(self.station, piece.piece_id, ['bag-A'], value)
        self.assertEqual(self._counts(), (0, 0, 0))
        only_b = review_total(self.station, piece.piece_id, ['bag-B'], 6)
        self.assertEqual(self._uses(only_b), (('bag-B', 4),))
        self.assertEqual(only_b.allocation.short_grams, 2)
        for demand, status in ((0, 'satisfied'), (1, 'short')):
            signed = review_total(self.station, piece.piece_id, [], demand)
            self.assertEqual(self._uses(signed), ())
            self.assertEqual((signed.allocation.status, signed.allocation.short_grams), (status, demand))
        self.assertIsNone(read_review(self.station, 999))

    def test_v7_reinitialize_station(self):
        piece = self.two_bag_piece()
        self.receive_piece(piece)
        first = review_total(self.station, piece.piece_id, ['bag-A', 'bag-B'], 8)
        extra = review_total(self.station, piece.piece_id, ['bag-B'], 5)
        initialize_station(self.station)
        initialize_station(self.station)
        self.source.close()
        self.reopen_station()
        self.assertEqual(read_accepted_totals(self.station, piece.piece_id), piece)
        self.assertEqual(read_review(self.station, first.review_id), first)
        self.assertEqual(read_review(self.station, extra.review_id), extra)
        self.assertEqual(extra.receipt.short_grams, 1)

    def test_v8_receipt_failure_then_short_review(self):
        piece = self.four_gram_piece()
        self.receive_piece(piece)
        self._fail_receipt()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'failed after uses'):
            review_total(self.station, piece.piece_id, ['bag-4'], 5)
        self.assertIsNone(read_review(self.station, 1))
        failed_counts = self._counts()
        self.station.execute('DROP TRIGGER refuse_receipt')
        signed = review_total(self.station, piece.piece_id, ['bag-4'], 5)
        self.source.close()
        self.reopen_station()
        self.assertEqual(read_review(self.station, signed.review_id), signed)
        self.assertEqual(signed.piece, piece)
        self.scenario(
            'v8', {'bag': 4, 'requested': 5, 'failure': 'before review receipt insert'},
            (0, 0, 0), failed_counts,
            ('short', 4, 1, 'totals:small'),
            (signed.receipt.status, signed.receipt.drawn_grams, signed.receipt.short_grams, signed.receipt.piece_id),
            ['review/allocate.py', 'review/publish.py', 'review/receipts.py', 'review/readback.py'],
            'A rolled-back transaction leaves no review rows. A four-gram bag supplies four of five grams on retry.',
        )

    def test_v8_atomic_retry_with_existing_review(self):
        piece = self.four_gram_piece()
        self.receive_piece(piece)
        previous = review_total(self.station, piece.piece_id, ['bag-4'], 2)
        self.assertEqual(previous.review_id, 1)
        before = self._counts()
        self._fail_receipt()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'failed after uses'):
            review_total(self.station, piece.piece_id, ['bag-4'], 5)
        self.assertIsNone(read_review(self.station, 2))
        self.assertEqual(self._counts(), before)
        self.assertEqual(read_review(self.station, 1), previous)
        self.station.execute('DROP TRIGGER refuse_receipt')
        retried = review_total(self.station, piece.piece_id, ['bag-4'], 5)
        self.assertEqual(self._counts(), tuple(value + 1 for value in before))
        self.assertEqual(self._uses(retried), (('bag-4', 4),))
        self.assertEqual((retried.allocation.status, retried.allocation.short_grams), ('short', 1))
        self.reopen_station()
        self.assertEqual(read_review(self.station, retried.review_id), retried)
        self.assertEqual(read_review(self.station, previous.review_id), previous)
