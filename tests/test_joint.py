from contextlib import closing
from dataclasses import replace
import json
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from exchange.format import encode_totals
from exchange.issue import issue_totals
from exchange.joint import decode_joint, encode_joint
from exchange.joint_issue import issue_joint
from exchange.joint_receive import receive_joint
from exchange.receive import PieceConflict
from joint_cases import CASES, build_source
from review.joint_allocate import allocate_joint
from review.joint_publish import review_joint
from review.joint_readback import read_joint_review
from review.joint_requests import validate_joint_requests
from storage import open_source, open_station


class JointCase(unittest.TestCase):
    def build(self, name):
        self.directory = TemporaryDirectory(prefix='lanxi-joint-')
        self.addCleanup(self.directory.cleanup)
        self.source = open_source(Path(self.directory.name) / 'source.sqlite3')
        self.addCleanup(self.source.close)
        self.snapshot = build_source(self.source, name)
        return self.snapshot

    def seal_station(self):
        self.station_path = Path(self.directory.name) / 'station.sqlite3'
        self.station = open_station(self.station_path)
        self.addCleanup(self.station.close)

    def issue(self, selected):
        self.body = issue_joint(self.source, self.snapshot.inventory_id, selected)
        self.piece = decode_joint(self.body)
        return self.body

    def accept(self, body=None):
        body = self.body if body is None else body
        return receive_joint(self.station, self.piece.piece_id, self.piece.inventory_id, body)

    def review(self, first, second):
        return review_joint(self.station, self.piece.piece_id, [first, second])


def request(bags, code, grams):
    return {'allowed_bags': list(bags), 'batch_code': code, 'required_grams': grams}


class JointScenarioTests(JointCase):
    def check(self, name, selected, first, second, status, uses):
        self.build(name)
        self.seal_station()
        self.issue(selected)
        self.accept()
        outcome = self.review(first, second)
        self.assertEqual(outcome['status'], status)
        self.assertEqual(outcome['uses'], uses)
        return outcome

    def test_single_short_on_shared_bag(self):
        self.check('single', CASES['single']['selected'],
                   request(['left'], 'A', 5), request(['left'], 'A', 5), 'short', [[], []])

    def test_single_disjoint_bags(self):
        self.check('single', CASES['single']['selected'],
                   request(['left'], 'A', 5), request(['right'], 'A', 5), 'satisfied',
                   [[['left', 5]], [['right', 5]]])

    def test_single_wide_then_narrow(self):
        self.check('single', CASES['single']['selected'],
                   request(['left', 'right'], 'A', 5), request(['left'], 'A', 5), 'satisfied',
                   [[['right', 5]], [['left', 5]]])

    def test_mixed_same_batch_short(self):
        self.check('mixed', CASES['mixed']['selected'],
                   request(['left'], 'A', 5), request(['right'], 'A', 5), 'short', [[], []])

    def test_mixed_distinct_batches(self):
        self.check('mixed', CASES['mixed']['selected'],
                   request(['left'], 'A', 5), request(['right'], 'B', 5), 'satisfied',
                   [[['left', 5]], [['right', 5]]])

    def test_separate_batches_short(self):
        self.check('separate', CASES['separate']['selected'],
                   request(['left'], 'A', 5), request(['right'], 'B', 5), 'short', [[], []])

    def test_hidden_overdraw_of_unselected_share(self):
        self.check('hidden', CASES['hidden']['selected'],
                   request(['kept'], 'A', 2), request(['kept'], 'A', 1), 'short', [[], []])

    def test_hidden_mixed_batch_satisfied(self):
        self.check('hidden', CASES['hidden']['selected'],
                   request(['kept'], 'A', 2), request(['kept'], 'B', 5), 'satisfied',
                   [[['kept', 2]], [['kept', 5]]])

    def test_shared_common_pool_short(self):
        self.check('shared', CASES['shared']['selected'],
                   request(['left'], 'A', 2), request(['right'], 'A', 2), 'short', [[], []])

    def test_shared_across_pools_satisfied(self):
        self.check('shared', CASES['shared']['selected'],
                   request(['left'], 'A', 2), request(['other'], 'A', 2), 'satisfied',
                   [[['left', 2]], [['other', 2]]])


class JointWireTests(JointCase):
    def test_public_boundary_hides_unselected_bags_and_internals(self):
        self.build('hidden')
        self.issue(CASES['hidden']['selected'])
        payload = json.loads(self.body)
        self.assertEqual(payload['format'], 2)
        self.assertEqual(payload['bags'], [['kept', 7]])
        self.assertEqual(payload['batch_codes'], ['A', 'B'])
        text = self.body
        for secret in ('unselected-reserve', 'internal-rest', 'reserve', 'mix-one', 'split-one'):
            self.assertNotIn(secret, text)
        # The unselected share still constrains A at kept.
        self.assertEqual(self.piece.cap(['kept'], ['A']), 2)

    def test_empty_selection_is_legal(self):
        self.build('single')
        self.seal_station()
        self.issue([])
        self.assertEqual(self.piece.bags, ())
        self.assertEqual(self.piece.batch_codes, ())
        self.assertEqual(self.piece.evidence['uplifts'], [])
        self.accept()
        # No batch code is published, so no request can name a valid one.
        for code in ('A', 'anything'):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    self.review(request([], code, 0), request([], code, 0))
        self.assertEqual(
            self.station.execute('SELECT COUNT(*) FROM joint_reviews').fetchone()[0], 0,
        )

    def test_issue_is_stable_and_order_sensitive(self):
        self.build('shared')
        first = issue_joint(self.source, self.snapshot.inventory_id, ['left', 'right'])
        again = issue_joint(self.source, self.snapshot.inventory_id, ['left', 'right'])
        other = issue_joint(self.source, self.snapshot.inventory_id, ['right', 'left'])
        self.assertEqual(first, again)
        self.assertNotEqual(decode_joint(first).piece_id, decode_joint(other).piece_id)
        self.assertEqual([bag for bag, _ in decode_joint(other).bags], ['right', 'left'])

    def test_issue_rejects_duplicate_and_unknown_bags(self):
        self.build('single')
        with self.assertRaises(ValueError):
            issue_joint(self.source, self.snapshot.inventory_id, ['left', 'left'])
        with self.assertRaises(ValueError):
            issue_joint(self.source, self.snapshot.inventory_id, ['absent'])
        with self.assertRaises(LookupError):
            issue_joint(self.source, 'missing', [])

    def test_receive_rejects_v1_body(self):
        self.build('single')
        self.seal_station()
        piece = issue_totals(self.source, self.snapshot.inventory_id)
        with self.assertRaises(ValueError):
            receive_joint(self.station, piece.piece_id, piece.inventory_id, encode_totals(piece))

    def test_receive_rejects_bad_binding_and_malformed(self):
        self.build('single')
        self.seal_station()
        self.issue(CASES['single']['selected'])
        with self.assertRaises(ValueError):
            receive_joint(self.station, 'other', self.piece.inventory_id, self.body)
        with self.assertRaises(ValueError):
            receive_joint(self.station, self.piece.piece_id, 'other', self.body)
        broken = self.body.replace('"format":2', '"format":3')
        with self.assertRaises(ValueError):
            receive_joint(self.station, self.piece.piece_id, self.piece.inventory_id, broken)
        self.assertIsNone(read_joint_review(self.station, 1))

    def test_receive_reuses_acceptance_for_equivalent_content(self):
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        first = self.accept()
        reformatted = json.dumps(json.loads(self.body), indent=2, sort_keys=True, ensure_ascii=False)
        replay = receive_joint(self.station, self.piece.piece_id, self.piece.inventory_id,
                               reformatted.encode('utf-8'))
        self.assertEqual(first, replay)
        self.assertEqual(
            self.station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0], 1,
        )

    def test_receive_conflicting_content_keeps_first(self):
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        first = self.accept()
        altered = replace(self.piece, bags=(('left', 6), ('right', 5)))
        with self.assertRaises(PieceConflict):
            receive_joint(self.station, self.piece.piece_id, self.piece.inventory_id, encode_joint(altered))
        self.assertEqual(
            self.station.execute('SELECT acceptance_no FROM accepted_joint WHERE piece_id = ?',
                                 (self.piece.piece_id,)).fetchone()[0], first,
        )


class JointReviewRuleTests(JointCase):
    def test_unknown_piece(self):
        self.build('single')
        self.seal_station()
        with self.assertRaises(LookupError):
            review_joint(self.station, 'joint:absent', [request([], 'A', 0), request([], 'A', 0)])

    def test_request_validation(self):
        self.build('single')
        self.seal_station()
        self.issue(CASES['single']['selected'])
        self.accept()
        base = request(['left'], 'A', 5)
        bad_rows = [
            [base],
            [base, base, base],
            [request(['absent'], 'A', 0), request([], 'A', 0)],
            [request(['left'], 'Z', 0), request([], 'A', 0)],
            [request(['left'], 'A', -1), request([], 'A', 0)],
            [request(['left'], 'A', True), request([], 'A', 0)],
            [request(['left'], 'A', 1.0), request([], 'A', 0)],
            [{'allowed_bags': ['left'], 'batch_code': 'A'}, request([], 'A', 0)],
        ]
        for rows in bad_rows:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    review_joint(self.station, self.piece.piece_id, rows)
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM joint_reviews').fetchone()[0], 0)

    def test_zero_gram_and_empty_sets(self):
        self.build('single')
        self.seal_station()
        self.issue(CASES['single']['selected'])
        self.accept()
        outcome = self.review(request([], 'A', 0), request([], 'A', 0))
        self.assertEqual(outcome['status'], 'satisfied')
        self.assertEqual(outcome['uses'], [[], []])

    def test_readback_round_trip_and_unknown(self):
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        self.accept()
        signed = self.review(request(['left'], 'A', 5), request(['right'], 'B', 5))
        self.station.close()
        self.station = open_station(self.station_path)
        self.assertEqual(read_joint_review(self.station, signed['review_id']), signed)
        self.assertEqual(read_joint_review(self.station, 999), None)
        for value in (0, -1, True, 1.0, '1'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    read_joint_review(self.station, value)

    def test_allocate_matches_satisfied_uses(self):
        self.build('shared')
        self.seal_station()
        self.issue(CASES['shared']['selected'])
        self.accept()
        parsed = validate_joint_requests(
            self.piece, [request(['left'], 'A', 2), request(['other'], 'A', 2)],
        )
        allocation = allocate_joint(self.piece, parsed)
        self.assertEqual(allocation.status, 'satisfied')
        self.assertEqual(
            [(use.bag_id, use.grams) for use in allocation.uses[0]], [('left', 2)],
        )


class JointAtomicityTests(JointCase):
    def counts(self):
        return tuple(self.station.execute(statement).fetchone()[0] for statement in (
            'SELECT COUNT(*) FROM joint_reviews',
            'SELECT COUNT(*) FROM joint_review_requests',
            'SELECT COUNT(*) FROM joint_review_uses',
        ))

    def test_review_write_failure_leaves_no_partial_and_retries(self):
        import sqlite3
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        self.accept()
        self.station.execute(
            '''CREATE TRIGGER refuse_uses BEFORE INSERT ON joint_review_uses
               BEGIN SELECT RAISE(ABORT, 'joint use write failed'); END''',
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'joint use write failed'):
            self.review(request(['left'], 'A', 5), request(['right'], 'B', 5))
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertIsNone(read_joint_review(self.station, 1))
        # The accepted piece survives the failed signing and the retry works.
        self.station.execute('DROP TRIGGER refuse_uses')
        signed = self.review(request(['left'], 'A', 5), request(['right'], 'B', 5))
        self.assertEqual(signed['status'], 'satisfied')
        self.station.close()
        self.station = open_station(self.station_path)
        self.assertEqual(read_joint_review(self.station, signed['review_id']), signed)
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0], 1)

    def test_review_request_write_failure_leaves_no_partial(self):
        import sqlite3
        self.build('single')
        self.seal_station()
        self.issue(CASES['single']['selected'])
        self.accept()
        self.station.execute(
            '''CREATE TRIGGER refuse_request BEFORE INSERT ON joint_review_requests
               BEGIN SELECT RAISE(ABORT, 'joint request write failed'); END''',
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'joint request write failed'):
            self.review(request(['left'], 'A', 5), request(['right'], 'A', 5))
        self.assertEqual(self.counts(), (0, 0, 0))
        self.station.execute('DROP TRIGGER refuse_request')
        signed = self.review(request(['left'], 'A', 5), request(['right'], 'A', 5))
        self.assertEqual(signed['status'], 'satisfied')

    def test_receive_write_failure_leaves_nothing(self):
        import sqlite3
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        self.station.execute(
            '''CREATE TRIGGER refuse_accept BEFORE INSERT ON accepted_joint
               BEGIN SELECT RAISE(ABORT, 'joint accept write failed'); END''',
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'joint accept write failed'):
            self.accept()
        self.assertEqual(
            self.station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0], 0,
        )
        self.station.execute('DROP TRIGGER refuse_accept')
        self.accept()
        self.assertEqual(
            self.station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0], 1,
        )


class JointReopenTests(JointCase):
    def test_source_closed_then_receive_review_and_reopen(self):
        self.build('shared')
        self.issue(CASES['shared']['selected'])
        self.source.close()
        self.seal_station()
        acceptance = self.accept()
        satisfied = self.review(request(['left'], 'A', 2), request(['other'], 'A', 2))
        short = self.review(request(['left'], 'A', 2), request(['right'], 'A', 2))
        self.station.close()
        self.station = open_station(self.station_path)
        self.assertEqual(read_joint_review(self.station, satisfied['review_id']), satisfied)
        self.assertEqual(read_joint_review(self.station, short['review_id']), short)
        self.assertEqual(read_joint_review(self.station, satisfied['review_id'])['acceptance_no'], acceptance)

    def test_mixed_and_separate_share_v1_body_but_not_v2(self):
        bodies = {}
        for name in ('mixed', 'separate'):
            self.build(name)
            bodies[name] = self.issue(CASES[name]['selected'])
            self.source.close()
        # V1 sees the same bag ledger...
        self.assertEqual(decode_joint(bodies['mixed']).bags, decode_joint(bodies['separate']).bags)
        # ...but V2 evidence differs, which is what separates the joint outcomes.
        self.assertNotEqual(
            decode_joint(bodies['mixed']).evidence['uplifts'],
            decode_joint(bodies['separate']).evidence['uplifts'],
        )


class JointReinitializeTests(JointCase):
    def test_reinitialize_station_preserves_joint_records(self):
        from storage import initialize_station
        self.build('mixed')
        self.seal_station()
        self.issue(CASES['mixed']['selected'])
        acceptance = self.accept()
        first = self.review(request(['left'], 'A', 5), request(['right'], 'B', 5))
        second = self.review(request(['left'], 'A', 5), request(['right'], 'A', 5))
        initialize_station(self.station)
        initialize_station(self.station)
        self.station.close()
        self.station = open_station(self.station_path)
        self.assertEqual(read_joint_review(self.station, first['review_id']), first)
        self.assertEqual(read_joint_review(self.station, second['review_id']), second)
        self.assertEqual(first['acceptance_no'], acceptance)
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM accepted_joint').fetchone()[0], 1)


class JointSharedBagTests(unittest.TestCase):
    def test_one_bag_holding_two_batches(self):
        from handling.segments import open_segment
        from handling.operations import record_operation
        from intake.batches import receive_batch
        from inventory.close import close_inventory
        directory = TemporaryDirectory(prefix='lanxi-sharedbag-')
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        with closing(open_source(path / 'source.sqlite3')) as source:
            receive_batch(source, 'A', 5, 'tA')
            receive_batch(source, 'B', 3, 'tB')
            open_segment(source, 'day')
            record_operation(source, 'day', 'mix', 'mix', ['A', 'B'], [('both-mass', 8)])
            record_operation(source, 'day', 'split', 'split', ['both-mass'],
                             [('both', 6), ('aonly', 2)])
            close_inventory(source, 'day', [('both', 6), ('aonly', 2)], inventory_id='inv')
            body = issue_joint(source, 'inv', ['both', 'aonly'])
        piece = decode_joint(body)
        self.assertEqual(piece.cap(['both'], ['A', 'B']), 6)
        with closing(open_station(path / 'station.sqlite3')) as station:
            receive_joint(station, piece.piece_id, piece.inventory_id, body)
            fits = review_joint(station, piece.piece_id, [
                request(['both'], 'A', 4), request(['both'], 'B', 2),
            ])
            self.assertEqual(fits['status'], 'satisfied')
            over = review_joint(station, piece.piece_id, [
                request(['both'], 'A', 5), request(['both'], 'B', 3),
            ])
            self.assertEqual(over['status'], 'short')
            self.assertEqual(over['uses'], [[], []])


class JointIssueAtomicityTests(JointCase):
    def test_issue_write_failure_leaves_no_partial(self):
        import sqlite3
        self.build('mixed')
        self.source.execute(
            '''CREATE TRIGGER refuse_issue BEFORE INSERT ON issued_joint
               BEGIN SELECT RAISE(ABORT, 'joint issue write failed'); END''',
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'joint issue write failed'):
            issue_joint(self.source, self.snapshot.inventory_id, CASES['mixed']['selected'])
        self.assertEqual(
            self.source.execute('SELECT COUNT(*) FROM issued_joint').fetchone()[0], 0,
        )
        self.source.execute('DROP TRIGGER refuse_issue')
        body = issue_joint(self.source, self.snapshot.inventory_id, CASES['mixed']['selected'])
        self.assertEqual(decode_joint(body).bags,
                         tuple((bag, grams) for bag, grams in
                               ((bag, dict(self.snapshot.bags)[bag]) for bag in CASES['mixed']['selected'])))

    def test_issue_unknown_inventory_and_lookup(self):
        self.build('single')
        with self.assertRaises(LookupError):
            issue_joint(self.source, 'no-such-inventory', [])
        with self.assertRaises(ValueError):
            issue_joint(self.source, self.snapshot.inventory_id, 'left')
        with self.assertRaises(ValueError):
            issue_joint(self.source, self.snapshot.inventory_id, ['left', 'left'])
