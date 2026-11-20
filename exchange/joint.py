"""V2 joint-piece wire format: selected-bag identities, net grams, public batch
codes and anonymous joint evidence.

Evidence is a capability table ``uplifts``: for every nonempty subset of the
selected bags and every nonempty subset of the published batch codes an upper
bound on the grams of that batch subset that can jointly reach that bag subset
across the whole sealed operation graph.  The bounds already account for
unselected bags that occupy the same original batches, so they preserve the
complete joint composition relation of the selection while publishing no
unselected bag identity, no internal node, no operation and no internal route.

All quantities are exact nonnegative integers (arbitrary precision); booleans,
floats, strings and nulls are refused and duplicate fields, bags or entries
raise ``ValueError``.
"""
from dataclasses import dataclass
import json

from intake.weighing import parse_identifier, parse_net_grams
from storage import decimal_integer, integer_text


V2_FORMAT = 2
_TOP_FIELDS = {'format', 'piece_id', 'inventory_id', 'bags', 'batch_codes', 'evidence'}
_EVIDENCE_FIELDS = {'format', 'uplifts'}
_UPLIFT_FIELDS = {'bags', 'batches', 'grams'}


@dataclass(frozen=True)
class JointPiece:
    piece_id: str
    inventory_id: str
    bags: tuple[tuple[str, int], ...]
    batch_codes: tuple[str, ...]
    evidence: dict

    @property
    def format_version(self) -> int:
        return V2_FORMAT

    @property
    def selected(self) -> tuple[str, ...]:
        return tuple(bag for bag, _ in self.bags)

    def net_grams(self, bag_id: str) -> int:
        for bag, grams in self.bags:
            if bag == bag_id:
                return grams
        raise ValueError(f'unknown bag {bag_id!r}')

    def cap(self, bags, batches) -> int:
        """Published upper bound for the given bag and batch subsets."""
        key = (frozenset(bags), frozenset(batches))
        for entry in self.evidence['uplifts']:
            if (frozenset(entry['bags']), frozenset(entry['batches'])) == key:
                return entry['grams']
        return 0


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate joint field {name!r}')
        result[name] = value
    return result


def _reject_constant(token):
    raise ValueError(f'invalid joint number {token!r}')


def decode_json(body):
    if not isinstance(body, (str, bytes)):
        raise ValueError('joint body must be JSON text or UTF-8 bytes')
    if isinstance(body, bytes):
        body = body.decode('utf-8')
    try:
        return json.loads(
            body, parse_int=decimal_integer, parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('joint body is not valid JSON') from exc


def _identifier_list(rows, field: str) -> tuple[str, ...]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError(f'{field} must be an array')
    seen = set()
    values = []
    for row in rows:
        key = parse_identifier(row, field)
        if key in seen:
            raise ValueError(f'duplicate {field} entry {key!r}')
        seen.add(key)
        values.append(key)
    return tuple(values)


def _check_bags(rows) -> tuple[tuple[str, int], ...]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError('joint bags must be an ordered array')
    seen = set()
    bags = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError('a joint bag row needs a bag ID and net grams')
        bag = parse_identifier(row[0], 'bag ID')
        grams = parse_net_grams(row[1], 'bag grams')
        if bag in seen:
            raise ValueError(f'duplicate bag {bag!r}')
        seen.add(bag)
        bags.append((bag, grams))
    return tuple(bags)


def normalise_evidence(entries) -> dict:
    """Order and validate ``(bags, batches, grams)`` triples into evidence form."""
    ordered = sorted(
        ((tuple(bags), tuple(batches), grams) for bags, batches, grams in entries),
        key=lambda entry: (len(entry[0]), entry[0], len(entry[1]), entry[1]),
    )
    return {
        'format': V2_FORMAT,
        'uplifts': [
            {'bags': list(bags), 'batches': list(batches), 'grams': grams}
            for bags, batches, grams in ordered
        ],
    }


def _check_evidence(evidence, bags, codes) -> dict:
    if not isinstance(evidence, dict):
        raise ValueError('joint evidence must be an object')
    if evidence.keys() != _EVIDENCE_FIELDS:
        raise ValueError('joint evidence needs format and uplifts')
    if type(evidence['format']) is not int or evidence['format'] != V2_FORMAT:
        raise ValueError('unsupported joint evidence format')
    rows = evidence['uplifts']
    if not isinstance(rows, list):
        raise ValueError('joint uplifts must be an array')
    bag_ids = [bag for bag, _ in bags]
    seen = set()
    entries = []
    for row in rows:
        if not isinstance(row, dict) or row.keys() != _UPLIFT_FIELDS:
            raise ValueError('a joint uplift needs bags, batches and grams')
        selected = _identifier_list(row['bags'], 'uplift bags')
        batches = _identifier_list(row['batches'], 'uplift batches')
        if not selected or not batches:
            raise ValueError('an uplift needs a nonempty bag and batch subset')
        unknown = set(selected).difference(bag_ids)
        if unknown:
            raise ValueError(f'unknown uplift bag {min(unknown)!r}')
        unknown = set(batches).difference(codes)
        if unknown:
            raise ValueError(f'unknown uplift batch {min(unknown)!r}')
        grams = parse_net_grams(row['grams'], 'uplift grams')
        key = (frozenset(selected), frozenset(batches))
        if key in seen:
            raise ValueError('duplicate uplift entry')
        seen.add(key)
        entries.append((selected, batches, grams))
    return normalise_evidence(entries)


def encode_joint(piece: JointPiece) -> str:
    piece_id = json.dumps(parse_identifier(piece.piece_id, 'piece ID'), ensure_ascii=False)
    inventory_id = json.dumps(parse_identifier(piece.inventory_id, 'inventory ID'), ensure_ascii=False)
    bags = _check_bags(piece.bags)
    codes = _identifier_list(piece.batch_codes, 'batch code')
    evidence = _check_evidence(piece.evidence, bags, codes)
    bag_rows = ','.join(
        '[' + json.dumps(bag, ensure_ascii=False) + ',' + integer_text(grams) + ']'
        for bag, grams in bags
    )
    code_rows = ','.join(json.dumps(code, ensure_ascii=False) for code in codes)
    uplift_rows = ','.join(
        '{"bags":[' + ','.join(json.dumps(b, ensure_ascii=False) for b in entry['bags']) +
        '],"batches":[' + ','.join(json.dumps(b, ensure_ascii=False) for b in entry['batches']) +
        '],"grams":' + integer_text(entry['grams']) + '}'
        for entry in evidence['uplifts']
    )
    return (
        f'{{"format":{V2_FORMAT},"piece_id":{piece_id},"inventory_id":{inventory_id},'
        f'"bags":[{bag_rows}],"batch_codes":[{code_rows}],'
        f'"evidence":{{"format":{V2_FORMAT},"uplifts":[{uplift_rows}]}}}}'
    )


def decode_joint(body) -> JointPiece:
    payload = decode_json(body)
    if not isinstance(payload, dict) or payload.keys() != _TOP_FIELDS:
        raise ValueError('invalid joint body fields')
    if type(payload['format']) is not int or payload['format'] != V2_FORMAT:
        raise ValueError('unsupported joint format')
    piece_id = parse_identifier(payload['piece_id'], 'piece ID')
    inventory_id = parse_identifier(payload['inventory_id'], 'inventory ID')
    bags = _check_bags(payload['bags'])
    codes = _identifier_list(payload['batch_codes'], 'batch code')
    evidence = _check_evidence(payload['evidence'], bags, codes)
    return JointPiece(piece_id, inventory_id, bags, codes, evidence)
