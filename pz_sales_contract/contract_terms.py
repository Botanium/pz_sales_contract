"""Versioned contract clauses pinned to each contract at creation."""
import hashlib
import json
from pathlib import Path

import frappe


LEGACY_TERMS_V1_SHA256 = 'af5bca40d97909791820b4eb7d2031f4765c863e7d0cad44eef8d5ed5c3937f7'
CURRENT_TERMS_VERSION = 'v2'


def _app_path():
    return Path(frappe.get_app_path('pz_sales_contract'))


def _validated_snapshot(raw):
    clauses = json.loads(raw)
    if not isinstance(clauses, list) or not clauses or not all(isinstance(row, str) for row in clauses):
        raise ValueError('Contract terms snapshot must be a non-empty JSON list of clauses')
    return raw


def _legacy_terms_snapshot():
    raw = (_app_path() / 'terms_versions' / 'v1.json').read_text(encoding='utf-8')
    clauses = json.loads(_validated_snapshot(raw))
    canonical = json.dumps(clauses, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if digest != LEGACY_TERMS_V1_SHA256:
        raise RuntimeError('Archived contract terms v1.json changed; restore the reviewed version or add an explicit new version')
    return raw


def snapshot_for_new_contract(original=None):
    """Copy the source version for an amendment, or current approved terms for a new family."""
    if original:
        snapshot = original.get('terms_snapshot')
        if snapshot:
            return _validated_snapshot(snapshot)
        # Existing contracts predate snapshots. Keep their current clause set
        # pinned to the immutable v1 copy rather than the mutable live file.
        return _legacy_terms_snapshot()
    return _validated_snapshot((_app_path() / 'terms.json').read_text(encoding='utf-8'))


def clauses_for_contract(doc):
    """Render saved clauses; pre-snapshot records use the immutable v1 baseline."""
    snapshot = doc.get('terms_snapshot')
    if not snapshot:
        snapshot = _legacy_terms_snapshot()
    return json.loads(_validated_snapshot(snapshot))
