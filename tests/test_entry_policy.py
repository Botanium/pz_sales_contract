import importlib.util
import json
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class Doc(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def check_permission(self, permission):
        self.checked_permission = permission


class TestEntryPolicy(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda: lambda fn: fn
        self.frappe.throw = Mock(side_effect=ValueError)
        self.frappe.db = Mock()
        self.frappe.db.get_value.return_value = None
        self.frappe.db.get_single_value.return_value = None
        self.frappe.get_doc = Mock()
        self.frappe.get_all = Mock(return_value=[])
        self.frappe.get_list = Mock(return_value=[])
        self.frappe.get_cached_doc = Mock(return_value=Doc(allow_stale=0, stale_days=10))
        self.frappe.has_permission = Mock(return_value=True)
        utils = types.ModuleType('frappe.utils')
        utils.getdate = lambda value: date.fromisoformat(str(value))
        utils.add_days = lambda value, days: utils.getdate(value) + timedelta(days=days)
        spec = importlib.util.spec_from_file_location('entry_policy_under_test', ROOT / 'pz_sales_contract/entry_policy.py')
        self.policy = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.utils': utils}):
            spec.loader.exec_module(self.policy)

    def test_optional_discount_normalizes_only_missing_or_valid_numbers(self):
        for value in (None, '', 0, '0', 12.5, '12.5'):
            self.assertEqual(self.policy.normalize_discount(value), float(value or 0))
        for value in (-1, '-1', 'invalid', 'NaN', 'Infinity', '1e9999'):
            with self.assertRaises(ValueError):
                self.policy.normalize_discount(value)

    def test_usd_company_uses_one_without_currency_exchange_lookup(self):
        self.assertEqual(self.policy.usd_conversion_rate('USD', '2026-10-03'), 1)
        self.frappe.get_all.assert_not_called()

    def test_iqd_company_uses_stored_selling_rate_and_native_staleness_filters(self):
        self.frappe.get_all.return_value = [Doc(exchange_rate=1310)]
        self.assertEqual(self.policy.usd_conversion_rate('IQD', '2026-10-03'), 1310)
        filters = self.frappe.get_all.call_args.kwargs['filters']
        self.assertIn(['from_currency', '=', 'USD'], filters)
        self.assertIn(['to_currency', '=', 'IQD'], filters)
        self.assertIn(['for_selling', '=', 1], filters)
        self.assertIn(['date', '>', date(2026, 9, 23)], filters)
        self.assertIn(['date', '<=', date(2026, 10, 3)], filters)

    def test_missing_negative_or_nonfinite_fx_fails_without_defaulting_to_one(self):
        for rates in ([], [Doc(exchange_rate=0)], [Doc(exchange_rate=-1)], [Doc(exchange_rate=float('nan'))]):
            self.frappe.get_all.return_value = rates
            with self.assertRaises(ValueError):
                self.policy.usd_conversion_rate('IQD', '2026-10-03')

    def test_unknown_or_ambiguous_usd_price_lists_require_configuration(self):
        for lists in ([], ['USD A', 'USD B']):
            self.frappe.get_list.return_value = lists
            with self.assertRaises(ValueError):
                self.policy.usd_price_list('Seller')
        self.frappe.get_list.return_value = ['Only USD']
        self.assertEqual(self.policy.usd_price_list('Seller'), 'Only USD')

    def test_company_price_list_and_native_default_must_be_enabled_usd_selling(self):
        self.frappe.db.get_value.return_value = 'Configured'
        self.frappe.get_doc.return_value = Doc(name='Configured', currency='IQD', enabled=1, selling=1)
        with self.assertRaises(ValueError):
            self.policy.usd_price_list('Seller')
        self.frappe.get_doc.return_value.currency = 'USD'
        self.assertEqual(self.policy.usd_price_list('Seller'), 'Configured')
        self.assertEqual(self.frappe.get_doc.return_value.checked_permission, 'read')
        self.frappe.db.get_value.return_value = None
        self.frappe.db.get_single_value.return_value = 'Configured'
        self.assertEqual(self.policy.usd_price_list('Seller'), 'Configured')

    def test_existing_currency_and_rate_are_not_rewritten(self):
        historic = Doc(currency='EUR', conversion_rate=1.17, selling_price_list='Historic EUR')
        self.policy.apply_usd_policy(historic)
        self.assertEqual(historic.currency, 'EUR')
        self.assertEqual(historic.conversion_rate, 1.17)
        self.frappe.get_doc.assert_not_called()

    def test_new_usd_policy_rejects_non_usd_and_pins_saved_accounting_values(self):
        doc = Doc(entry_policy_version=self.policy.ENTRY_POLICY_VERSION, currency='EUR')
        with self.assertRaises(ValueError):
            self.policy.apply_usd_policy(doc)
        doc.update(currency='USD', company='Seller', transaction_date='2026-10-03',
            conversion_rate=1310, selling_price_list='USD')
        old = Doc(doc)
        self.policy.apply_usd_policy(doc, old)
        self.frappe.get_doc.assert_not_called()
        doc.conversion_rate = 1
        with self.assertRaises(ValueError):
            self.policy.apply_usd_policy(doc, old)

    def test_packaging_is_derived_from_verified_items_and_unknown_items_stay_blank(self):
        for name, expected in [('Bitumen - Bulk', 'Bulk'), ('Bitumen - Drum', 'Drum'),
                ('Bitumen - Jumbo', 'Jumbo'), ('Bitumen VG30 Jumbo Bag', 'Jumbo Bag')]:
            row = Doc(item_code=name, packaging=None)
            self.policy.apply_item_packaging(row)
            self.assertEqual(row.packaging, expected)
            row.packaging = 'Wrong'
            self.policy.apply_item_packaging(row)
            self.assertEqual(row.packaging, expected)
        row = Doc(item_code='Unverified Bulk Service', packaging=None)
        self.policy.apply_item_packaging(row)
        self.assertIsNone(row.packaging)
        row.packaging = 'Explicit packaging'
        self.policy.apply_item_packaging(row)
        self.assertIsNone(row.packaging)

    def test_changed_item_replaces_old_packaging_with_verified_mapping(self):
        old = Doc(item_code='Bitumen - Bulk', packaging='Bulk')
        row = Doc(item_code='Bitumen - Drum', packaging='Bulk')
        self.policy.apply_item_packaging(row, old)
        self.assertEqual(row.packaging, 'Drum')

        unknown = Doc(item_code='Unverified Bulk Service', packaging='Drum')
        self.policy.apply_item_packaging(unknown, old)
        self.assertIsNone(unknown.packaging)

    def test_historical_packaging_snapshot_is_preserved(self):
        old = Doc(item_code='Bitumen - Bulk', packaging='Previously agreed packaging')
        row = Doc(old)
        self.policy.apply_item_packaging(row, old)
        self.assertEqual(row.packaging, old.packaging)

    def test_amendment_copy_match_requires_the_same_line_content(self):
        old = Doc(name='saved-row', idx=1, item_code='Bitumen - Bulk',
            grade_master='Grade 60/70', grade='60/70', qty=10, uom='Nos',
            rate=100, specification_reference='Legacy reference', packaging='Legacy pack')
        copied = Doc(name='new-row', idx=1, item_code='Bitumen - Bulk',
            grade_master='Grade 60/70', grade='60/70', qty=10, uom='Nos',
            rate=100, specification_reference='Legacy reference', packaging=None)
        self.assertIsNone(self.policy.find_previous_item_row(copied, [old]))
        self.assertIs(self.policy.find_previous_item_row(copied, [old], allow_copy_match=True), old)

        replacement = Doc(copied)
        replacement.qty = 20
        self.assertIsNone(self.policy.find_previous_item_row(
            replacement, [old], allow_copy_match=True))
        self.policy.apply_item_packaging(replacement)
        self.assertEqual(replacement.packaging, 'Bulk')

    def test_location_selection_snapshots_label_and_rejects_disabled_new_selection(self):
        doc = Doc(entry_policy_version=self.policy.ENTRY_POLICY_VERSION, contract_location='loc-1')
        self.frappe.get_doc.return_value = Doc(location_name='Mersin, Turkey', disabled=0)
        self.policy.validate_location(doc)
        self.assertEqual(doc.named_place, 'Mersin, Turkey')
        self.frappe.get_doc.return_value.disabled = 1
        with self.assertRaises(ValueError):
            self.policy.validate_location(doc)

    def test_location_label_edits_never_rewrite_existing_contract_or_amendment_snapshot(self):
        old = Doc(entry_policy_version=self.policy.ENTRY_POLICY_VERSION,
            contract_location='loc-1', named_place='Original agreed place')
        doc = Doc(old, named_place='Changed master label')
        self.policy.validate_location(doc, old)
        self.assertEqual(doc.named_place, 'Original agreed place')
        self.frappe.get_doc.assert_not_called()

    def test_location_permissions_are_limited_to_contract_roles(self):
        schema = json.loads((ROOT / 'pz_sales_contract/sales_contracts/doctype/pz_contract_location/pz_contract_location.json').read_text())
        permissions = {row['role']: row for row in schema['permissions']}
        self.assertEqual(set(permissions), {'PZ Sales Contract User', 'PZ Sales Contract Manager'})
        self.assertFalse(permissions['PZ Sales Contract User'].get('create'))
        self.assertTrue(permissions['PZ Sales Contract Manager']['create'])
        self.assertTrue(schema['quick_entry'])

    def test_date_change_resolves_accounting_rate_but_retains_saved_price_list(self):
        old = Doc(entry_policy_version=self.policy.ENTRY_POLICY_VERSION, currency='USD',
            company='Seller', transaction_date='2026-10-02', conversion_rate=1300,
            selling_price_list='Saved USD')
        doc = Doc(old, transaction_date='2026-10-03')
        self.frappe.get_doc.return_value = Doc(default_currency='IQD')
        self.frappe.get_all.return_value = [Doc(exchange_rate=1310)]
        self.policy.apply_usd_policy(doc, old)
        self.assertEqual(doc.conversion_rate, 1310)
        self.assertEqual(doc.selling_price_list, 'Saved USD')
        self.frappe.get_list.assert_not_called()

    def test_item_lookup_checks_permissions_and_rejects_disabled_or_nonsales_items(self):
        item = Doc(name='Bitumen - Bulk', item_name='Bitumen - Bulk', description='Synthetic',
            stock_uom='Tonne', disabled=0, is_sales_item=1)
        self.frappe.get_doc.return_value = item
        self.assertEqual(self.policy.get_item_details(item.name)['packaging'], 'Bulk')
        self.assertEqual(item.checked_permission, 'read')
        for disabled, sales in [(1, 1), (0, 0)]:
            item.update(disabled=disabled, is_sales_item=sales)
            with self.assertRaises(ValueError):
                self.policy.get_item_details(item.name)
        self.frappe.has_permission.return_value = False
        self.frappe.get_doc.reset_mock()
        with self.assertRaises(ValueError):
            self.policy.get_item_details(item.name)
        self.frappe.get_doc.assert_not_called()

    def test_starter_locations_are_not_recreated_after_label_edits(self):
        self.frappe.db.exists.return_value = True
        self.policy.ensure_starter_locations()
        self.frappe.get_doc.assert_not_called()
        self.frappe.db.exists.return_value = False
        self.policy.ensure_starter_locations()
        self.assertEqual(self.frappe.get_doc.call_count, 2)
        self.assertEqual(self.frappe.get_doc.return_value.insert.call_args.kwargs,
            {'ignore_permissions': True, 'set_name': 'PZ-LOC-MERSIN'})


if __name__ == '__main__':
    unittest.main()
