import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class Doc(dict):
    def set(self, key, value):
        self[key] = value

class TestPartyEntry(unittest.TestCase):
    def setUp(self):
        frappe = types.ModuleType('frappe')
        frappe.MandatoryError = ValueError
        def throw(message, exception):
            raise exception(message)
        frappe.throw = throw
        spec = importlib.util.spec_from_file_location('party_under_test', ROOT / 'pz_sales_contract/parties.py')
        self.party = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': frappe}):
            spec.loader.exec_module(self.party)

    def test_all_direct_party_fields_reject_blank_and_accept_phone_only_contact(self):
        doc = Doc({field: 'Entered value' for field in self.party.PARTY_REQUIRED_FIELDS},
            party_entry_version='direct-v1', buyer_email_phone='00971 505 65 1305')
        self.party.validate_party_fields(doc)
        for field in self.party.PARTY_REQUIRED_FIELDS:
            bad = Doc(doc, **{field: '   '})
            with self.assertRaises(ValueError, msg=field):
                self.party.validate_party_fields(bad)

    def test_legacy_records_are_not_backfilled_or_given_new_requirements(self):
        doc = Doc(customer_name='Old buyer', contact_person='Old Contact')
        before = dict(doc)
        self.party.validate_party_fields(doc)
        self.assertEqual(doc, before)

    def test_schema_has_editable_snapshots_and_buyer_position_in_buyer_details(self):
        schema = json.loads((ROOT / 'pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.json').read_text())
        fields = {field['fieldname']: field for field in schema['fields']}
        for field in self.party.PARTY_LINK_FIELDS:
            self.assertTrue(fields[field]['hidden'])
            self.assertFalse(fields[field].get('reqd'))
        for field in self.party.PARTY_REQUIRED_FIELDS:
            self.assertFalse(fields[field].get('read_only'))
            self.assertIn('direct-v1', fields[field]['mandatory_depends_on'])
        order = schema['field_order']
        self.assertLess(order.index('customer_details'), order.index('contact_display'))
        self.assertEqual(order.index('buyer_position'), order.index('contact_display') + 1)
        self.assertEqual(order.count('buyer_position'), 1)
        self.assertNotIn('TRANSOCEANGROUP.CO', json.dumps(schema))


    def test_optional_buyer_details_allow_blank_but_primary_phone_remains_required(self):
        doc = Doc({field: 'Entered value' for field in self.party.PARTY_REQUIRED_FIELDS},
            party_entry_version='direct-v1', customer_tax_id=None, buyer_email_phone='')
        self.party.validate_party_fields(doc)
        doc['buyer_phone'] = ''
        with self.assertRaisesRegex(ValueError, 'Buyer phone'):
            self.party.validate_party_fields(doc)
        schema = json.loads((ROOT / 'pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.json').read_text())
        fields = {field['fieldname']: field for field in schema['fields']}
        for field in ('customer_tax_id', 'buyer_email_phone'):
            self.assertFalse(fields[field].get('reqd'))
            self.assertFalse(fields[field].get('mandatory_depends_on'))


    def test_payment_fields_optional_and_bank_is_plain_data(self):
        schema = json.loads((ROOT / 'pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.json').read_text())
        fields = {field['fieldname']: field for field in schema['fields']}
        for field in self.party.PAYMENT_INSTRUCTION_FIELDS:
            self.assertFalse(fields[field].get('reqd'))
            self.assertFalse(fields[field].get('mandatory_depends_on'))
        self.assertEqual(fields['bank_receiving_account']['fieldtype'], 'Data')
        self.assertFalse(fields['bank_receiving_account'].get('options'))
        self.assertEqual(fields['cash_receiving_account']['fieldtype'], 'Link')
