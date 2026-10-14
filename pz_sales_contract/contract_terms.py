"""Versioned contract clauses pinned to each contract at creation."""
import hashlib
import json
from pathlib import Path

import frappe


LEGACY_TERMS_V1_SHA256 = 'af5bca40d97909791820b4eb7d2031f4765c863e7d0cad44eef8d5ed5c3937f7'
ARCHIVED_TERMS_V2_SHA256 = 'f09bfdc955dd477ca151a848a9b5b934dd9f9ea41583c3aeeb67ffd02571c461'
ARCHIVED_TERMS_V3_SHA256 = '2d7f41f3d77b49af758d65fb927e1f42b08c88674f2d409c1bc50ff2c8abb577'
CURRENT_TERMS_V4_SHA256 = 'af5bca40d97909791820b4eb7d2031f4765c863e7d0cad44eef8d5ed5c3937f7'
CURRENT_TERMS_V5_SHA256 = 'c7e120bcf689054352db1b9a187a10bf6386e8b4fff12524ba1808cf7c38960a'
CURRENT_TERMS_V6_SHA256 = '07bf70a28cd2f3999ed665181e2908854eed5070f7197bae7e98fc919540b870'
CURRENT_TERMS_VERSION = 'v6'
PARAMETERIZED_TERMS_VERSIONS = frozenset({'v5', 'v6'})
SIMPLE_PRINT_TERMS_VERSIONS = frozenset({'v2', 'v3', 'v4', 'v5', CURRENT_TERMS_VERSION})

PINNED_TERMS = {
    'v1': ('v1.json', LEGACY_TERMS_V1_SHA256),
    'v2': ('v2.json', ARCHIVED_TERMS_V2_SHA256),
    'v3': ('v3.json', ARCHIVED_TERMS_V3_SHA256),
    'v4': ('v4.json', CURRENT_TERMS_V4_SHA256),
    'v5': ('v5.json', CURRENT_TERMS_V5_SHA256),
    'v6': ('v6.json', CURRENT_TERMS_V6_SHA256),
}


def _app_path():
    return Path(frappe.get_app_path('pz_sales_contract'))


def _validated_snapshot(raw):
    clauses = json.loads(raw)
    if not isinstance(clauses, list) or not clauses or not all(isinstance(row, str) for row in clauses):
        raise ValueError('Contract terms snapshot must be a non-empty JSON list of clauses')
    return raw


def _pinned_terms_snapshot(version):
    filename, expected_digest = PINNED_TERMS.get(version, PINNED_TERMS['v1'])
    raw = (_app_path() / 'terms_versions' / filename).read_text(encoding='utf-8')
    clauses = json.loads(_validated_snapshot(raw))
    canonical = json.dumps(clauses, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if digest != expected_digest:
        raise RuntimeError(f'Archived contract terms {filename} changed; restore the reviewed version or add an explicit new version')
    return raw


def _legacy_terms_snapshot():
    return _pinned_terms_snapshot('v1')


def _snapshot_for_version(version):
    return _pinned_terms_snapshot(version if version in PINNED_TERMS else 'v1')


def _parameterized_v5_snapshot(raw, advance_percentage):
    from pz_sales_contract.payment_split import format_percentage, normalize_advance_percentage

    clauses = json.loads(_validated_snapshot(raw))
    advance = normalize_advance_percentage(advance_percentage)
    balance = 100 - advance
    clause = clauses[2]
    if clause.count('{advance_percentage}') != 1 or clause.count('{balance_percentage}') != 1:
        raise RuntimeError('The pinned v5 payment clause must contain exactly one advance and balance percentage')
    clauses[2] = clause.replace('{advance_percentage}', format_percentage(advance))
    clauses[2] = clauses[2].replace('{balance_percentage}', format_percentage(balance))
    return json.dumps(clauses, ensure_ascii=False, indent=2) + '\n'


def _active_terms_template():
    raw = _validated_snapshot((_app_path() / 'terms.json').read_text(encoding='utf-8'))
    clauses = json.loads(raw)
    canonical = json.dumps(clauses, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if digest != PINNED_TERMS[CURRENT_TERMS_VERSION][1]:
        raise RuntimeError(f'Active contract terms do not match the pinned {CURRENT_TERMS_VERSION} wording')
    return raw


def snapshot_for_new_contract(original=None, advance_percentage=30, cargo_ready_days=None, version=None):
    """Preserve amendments; parameterize only the selected new/draft version."""
    if original:
        snapshot = original.get('terms_snapshot')
        if snapshot:
            return _validated_snapshot(snapshot)
        # Keep a versioned source's baseline when a historical snapshot is absent.
        # Truly legacy records without a version use the immutable v1 copy.
        version = original.get('terms_version')
        if version in PARAMETERIZED_TERMS_VERSIONS:
            return snapshot_for_new_contract(advance_percentage=original.get('advance_percentage'),
                cargo_ready_days=original.get('cargo_ready_within_days'), version=version)
        return _snapshot_for_version(version)
    version = version or CURRENT_TERMS_VERSION
    raw = _active_terms_template() if version == CURRENT_TERMS_VERSION else _snapshot_for_version(version)
    snapshot = _parameterized_v5_snapshot(raw, advance_percentage)
    if version == 'v6':
        from pz_sales_contract.cargo_readiness import readiness_clause
        clause = readiness_clause(cargo_ready_days, advance_percentage)
        if clause:
            clauses = json.loads(snapshot)
            clauses.append(clause)
            snapshot = json.dumps(clauses, ensure_ascii=False, indent=2) + '\n'
    return snapshot


def clauses_for_contract(doc):
    """Render saved clauses or the pinned version archive for a missing snapshot."""
    snapshot = doc.get('terms_snapshot')
    if not snapshot:
        version = doc.get('terms_version')
        if version in PARAMETERIZED_TERMS_VERSIONS:
            snapshot = snapshot_for_new_contract(advance_percentage=doc.get('advance_percentage'),
                cargo_ready_days=doc.get('cargo_ready_within_days'), version=version)
        else:
            snapshot = _snapshot_for_version(version)
    return json.loads(_validated_snapshot(snapshot))
