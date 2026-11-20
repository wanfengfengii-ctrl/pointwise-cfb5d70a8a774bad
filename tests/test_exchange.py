from dataclasses import replace
import json

from exchange.format import TotalsPiece, decode_totals, encode_totals
from exchange.readback import read_accepted_totals
from exchange.receive import PieceConflict, receive_totals
from review.publish import review_total
from tests import WorkdayCase


class ExchangeTests(WorkdayCase):
    def test_v6_conflicting_content_preserves_original(self):
        piece = self.four_gram_piece()
        self.receive_piece(piece)
        conflicting_piece = replace(piece, bags=(('bag-4', 6),))
        self.source.close()
        with self.assertRaises(PieceConflict):
            self.receive_piece(conflicting_piece)
        adopted = read_accepted_totals(self.station, piece.piece_id)
        signed = review_total(self.station, piece.piece_id, ['bag-4'], 5)
        self.assertEqual(adopted, piece)
        self.scenario(
            'v6', {'original': 4, 'reposted': 6, 'requested': 5},
            (('bag-4', 4),), adopted.bags,
            ('short', 4, 1), (signed.allocation.status, signed.allocation.drawn_grams, signed.allocation.short_grams),
            ['exchange/receive.py', 'exchange/readback.py', 'review/publish.py', 'review/allocate.py'],
            'The first accepted four-gram bag leaves a one-gram shortfall for five grams.',
        )

    def test_v6_same_content_reuses_first_acceptance(self):
        piece = self.two_bag_piece()
        first = self.receive_piece(piece)
        reformatted = json.dumps(json.loads(encode_totals(piece)), indent=2, sort_keys=True)
        self.reopen_station()
        replay = receive_totals(self.station, piece.piece_id, piece.inventory_id, reformatted)
        self.assertEqual(first, replay)
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM accepted_totals').fetchone()[0], 1)

    def test_v6_duplicate_bags(self):
        piece = self.four_gram_piece()
        self.receive_piece(piece)
        body = '{"format":1,"piece_id":"new","inventory_id":"small","bags":[["bag-4",4],["bag-4",6]]}'
        self.source.close()
        with self.assertRaisesRegex(ValueError, 'duplicate bag'):
            receive_totals(self.station, 'new', 'small', body)
        self.assertIsNone(read_accepted_totals(self.station, 'new'))
        signed = review_total(self.station, piece.piece_id, ['bag-4'], 4)
        self.assertEqual(signed.allocation.status, 'satisfied')
        self.assertEqual(signed.piece.bags, (('bag-4', 4),))

    def test_v6_binding(self):
        piece = self.four_gram_piece()
        body = encode_totals(piece)
        for piece_id, inventory in (('other-piece', piece.inventory_id), (piece.piece_id, 'other-inventory')):
            with self.subTest(piece_id=piece_id, inventory=inventory):
                with self.assertRaisesRegex(ValueError, 'identifiers'):
                    receive_totals(self.station, piece_id, inventory, body)
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM accepted_totals').fetchone()[0], 0)
        self.assertEqual(self.receive_piece(piece).piece, piece)

    def test_wire_validation_and_exact_quantities(self):
        body = {'format': 1, 'piece_id': 'p', 'inventory_id': 'i', 'bags': [['a', 0], ['b', 2]]}
        invalid = [
            {**body, 'format': True}, {**body, 'format': 2}, {**body, 'bags': [['b', 2], ['a', 0]]},
            {**body, 'bags': [['a', True]]}, {**body, 'bags': [['a', None]]}, {**body, 'bags': [['a', -1]]},
            {**body, 'bags': [['a', 1.0]]}, {**body, 'bags': [['a', '1']]}, {**body, 'bags': [['a']]},
        ]
        for entry in invalid:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    receive_totals(self.station, 'p', 'i', json.dumps(entry))
        with self.assertRaisesRegex(ValueError, 'duplicate totals field'):
            decode_totals('{"format":2,"format":1,"piece_id":"p","inventory_id":"i","bags":[]}')
        self.assertIsNone(read_accepted_totals(self.station, 'p'))
        piece = TotalsPiece('p', 'i', (('a', 0), ('b', 10**4500 + 17)))
        self.assertEqual(self.receive_piece(piece).piece, piece)
        self.reopen_station()
        self.assertEqual(read_accepted_totals(self.station, 'p'), piece)
        signed = review_total(self.station, 'p', ['b'], 10**4500 + 18)
        self.assertEqual(signed.allocation.drawn_grams, 10**4500 + 17)
        self.assertEqual(signed.allocation.short_grams, 1)
