import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_timedelta, today

from pz_sales_contract.payments import payment_status, get_status
from pz_sales_contract.contract_terms import CURRENT_TERMS_VERSION, clauses_for_contract, snapshot_for_new_contract
from pz_sales_contract.testing import (
    setup_fixtures, contract, receipt, refund, reconcile, new_customer,
    synthetic_bitumen_grade, COMPANY,
)
from pz_sales_contract.sales_contracts.doctype.pz_contract_defaults.pz_contract_defaults import (
    COMPANY_DEFAULT_FIELDS,
    get_company_defaults,
)
from pz_sales_contract.sales_contracts.doctype.pz_sales_contract.pz_sales_contract import (
    HISTORICAL_CONTRACT_FIELDS,
    ITEM_ONLY_DRAFT_SO_SCOPE,
    grade_snapshot,
)

# Every needed record is created explicitly below. Do not recursively import
# optional ERPNext fixtures (Payment Gateway belongs to another app in v16).
IGNORE_TEST_RECORD_DEPENDENCIES = ['Customer','Company','Address','Contact','Currency','Price List',
    'Incoterm','Bitumen Grade','Holiday List','Sales Order','PZ Sales Contract','Item','UOM','Account','Cost Center','Project',
    'Location','Branch','Department','PZ Contract Location']


class TestPZSalesContract(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_account=setup_fixtures()
        frappe.db.set_single_value('Print Settings','allow_print_for_draft',1)
        frappe.db.set_single_value('Print Settings','allow_print_for_cancelled',1)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def clear_synthetic_company_defaults(self):
        # This is a dedicated disposable-test fixture, never a live Company setup.
        if frappe.db.exists('PZ Contract Defaults', COMPANY):
            frappe.delete_doc('PZ Contract Defaults', COMPANY, ignore_permissions=True)

    def complete_legacy_schedule(self, doc):
        doc.customer_address = frappe.db.get_value('Dynamic Link',
            dict(parenttype='Address', link_doctype='Customer', link_name=doc.customer), 'parent')
        doc.contact_person = frappe.db.get_value('Dynamic Link',
            dict(parenttype='Contact', link_doctype='Customer', link_name=doc.customer), 'parent')
        doc.seller_address = 'PZ Synthetic Seller-Billing'
        if not doc.is_new():
            # Emulate a stored pre-cutover record, including its internal links.
            frappe.db.set_value(doc.doctype, doc.name, dict(party_entry_version=None,
                customer_address=doc.customer_address, contact_person=doc.contact_person,
                seller_address=doc.seller_address))
            doc.reload()
        for fieldname, value in {
            'delivery_date': today(),
            'delivery_arrangement': 'Synthetic agreed delivery arrangement',
            'transport_responsibility': 'Buyer transport (synthetic)',
            'insurance_responsibility': 'Buyer insurance (synthetic)',
            'measurement_basis': 'Synthetic unit; no tolerance or price adjustment agreed',
            'notice_channel': 'synthetic-contract-notices@example.invalid',
            'collection_grace': 48,
            'grace_unit': 'Calendar hours',
            'collection_arrangement': 'Synthetic appointment only',
            'delay_charges': 'None agreed (synthetic)',
            'penalty_basis_cap': 'None agreed (synthetic)',
            'cure_period': '5 calendar days (synthetic)',
            'latent_claim_period': '7 calendar days after discovery (synthetic)',
            'force_majeure_threshold': '30 calendar days (synthetic)',
            'governing_law': 'Synthetic placeholder; not legal advice or real agreement',
            'courts': 'Synthetic courts placeholder',
        }.items():
            doc.set(fieldname, value)
        if not doc.specifications:
            doc.append('specifications', dict(item_code='PZ Synthetic Bitumen',
                property='Penetration', unit='dmm', test_method='Synthetic method',
                requirement='60-70 (demo only)'))
        return doc

    def synthetic_company_defaults(self, **overrides):
        values = dict(
            doctype='PZ Contract Defaults',
            company=COMPANY,
            seller_address='PZ Synthetic Seller-Billing',
            seller_signatory='Synthetic configured seller',
            seller_position='Synthetic configured manager',
            currency='USD',
            conversion_rate=1,
            selling_price_list='PZ Synthetic USD',
            delivery_arrangement='Synthetic configured delivery and risk arrangement',
            transport_responsibility='Buyer transport (synthetic)',
            insurance_responsibility='Buyer insurance (synthetic)',
            measurement_basis='Synthetic measurement; no tolerance or price adjustment agreed',
            timezone='Asia/Baghdad',
            business_days='Monday,Tuesday,Wednesday,Thursday,Friday',
            opens_at='09:00:00',
            closes_at='17:00:00',
            holiday_list='PZ Synthetic Calendar',
            notice_channel='synthetic-contract-notices@example.invalid',
            collection_grace=48,
            grace_unit='Calendar hours',
            collection_arrangement='Synthetic configured appointment-only collection',
            delay_charges='Synthetic default: none agreed',
            penalty_basis_cap='Synthetic default: none agreed',
            cure_period='Synthetic 5 calendar days',
            latent_claim_period='Synthetic 7 calendar days after discovery',
            force_majeure_threshold='Synthetic 30 calendar days',
            governing_law='Synthetic configured law placeholder',
            courts='Synthetic configured court placeholder',
            bank_receiving_account='PZ Synthetic Bank - PZT',
            cash_receiving_account='PZ Synthetic Cash - PZT',
            beneficiary='SYNTHETIC — DO NOT PAY',
            bank_branch='SYNTHETIC BANK — NO REAL ACCOUNT',
            account_iban='USD / SYNTHETIC-NOT-AN-ACCOUNT',
            swift_reference='SYNTHETIC ONLY',
        )
        values.update(overrides)
        return frappe.get_doc(values)

    def synthetic_company_account(self, account_name, kind, currency):
        name = f'{account_name} - PZT'
        if not frappe.db.exists('Account', name):
            parent = frappe.db.get_value('Account', dict(company=COMPANY, is_group=1, root_type='Asset'), 'name')
            frappe.get_doc(dict(doctype='Account', account_name=account_name, company=COMPANY,
                parent_account=parent, account_currency=currency, account_type=kind, is_group=0)).insert()
        return name

    def synthetic_alternate_bank_account(self, currency='USD'):
        return self.synthetic_company_account(f'PZ Synthetic Alternate Bank {currency}', 'Bank', currency)

    def test_native_arithmetic_and_master_links(self):
        tax_account=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Income'),'name')
        d=contract(discount_amount=100)
        self.assertEqual((d.subtotal,d.tax_total,d.grand_total,d.advance_required,d.balance_required),(1000,0,900,270,630))
        self.assertFalse(d.taxes)
        d.submit()
        order=frappe.get_doc('Sales Order',d.sales_order)
        self.assertEqual(order.docstatus,0)
        self.assertFalse(order.delivery_date)
        self.assertFalse(order.taxes)
        order.delivery_date=add_days(today(),10)
        for item in order.items:
            item.delivery_date=order.delivery_date
        order.append('taxes',dict(charge_type='On Net Total',account_head=tax_account,
            description='Synthetic 10%',rate=10))
        order.save().submit()
        self.assertEqual((order.net_total,order.grand_total),(900,990))
        self.assertEqual(frappe.db.get_value('PZ Sales Contract',d.name,'grand_total'),900)
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'named_place'),d.named_place)
        self.assertEqual(d.items[0].item_name,'Synthetic Bitumen')
        self.assertIn('Nine Hundred only',d.in_words)
        self.assertEqual('Synthetic buyer address',d.address_display)
        self.assertEqual(frappe.db.get_value('Sales Order Item',
            {'parent': d.sales_order, 'idx': 1}, 'custom_bitumen_grade'), d.items[0].grade_master)

    def test_contract_line_grades_are_independent(self):
        first_grade = synthetic_bitumen_grade()
        second_grade = synthetic_bitumen_grade('80/100')
        allow_multiple_items = frappe.db.get_single_value('Selling Settings', 'allow_multiple_items')
        frappe.db.set_single_value('Selling Settings', 'allow_multiple_items', 1)
        try:
            d = contract(submit=True, items=[
                dict(item_code='PZ Synthetic Bitumen', qty=1, uom='Nos', rate=10,
                    grade_master=first_grade, packaging='Synthetic drums'),
                dict(item_code='PZ Synthetic Bitumen', qty=1, uom='Nos', rate=10,
                    grade_master=second_grade, packaging='Synthetic drums'),
            ])
            grades = frappe.get_all('Sales Order Item', filters={'parent': d.sales_order},
                fields=['custom_bitumen_grade'], order_by='idx asc')
            self.assertEqual([row.custom_bitumen_grade for row in grades], [first_grade, second_grade])
        finally:
            frappe.db.set_single_value('Selling Settings', 'allow_multiple_items', allow_multiple_items)

    def test_grade_snapshot_falls_back_to_canonical_name_when_code_field_is_absent(self):
        grade = SimpleNamespace(name='PZ Synthetic Grade Name', get=lambda key: None)
        no_code_meta = SimpleNamespace(has_field=lambda fieldname: False)
        with patch.object(frappe, 'get_meta', return_value=no_code_meta):
            self.assertEqual(grade_snapshot(grade), 'PZ Synthetic Grade Name')

    def test_contract_terms_are_snapshotted_and_legacy_records_use_frozen_v1(self):
        app_path = Path(__file__).resolve().parents[3]
        active_snapshot = (app_path / 'terms.json').read_text(encoding='utf-8')
        frozen_snapshot = (app_path / 'terms_versions' / 'v1.json').read_text(encoding='utf-8')
        frozen_v2 = (app_path / 'terms_versions' / 'v2.json').read_text(encoding='utf-8')
        frozen_v3 = (app_path / 'terms_versions' / 'v3.json').read_text(encoding='utf-8')
        self.assertEqual(active_snapshot, frozen_v3)
        d = contract()
        self.assertEqual(d.terms_version, CURRENT_TERMS_VERSION)
        self.assertEqual(d.terms_snapshot, active_snapshot)
        self.assertEqual(clauses_for_contract(d), json.loads(active_snapshot))

        source_with_snapshot = SimpleNamespace(get=lambda key: active_snapshot if key == 'terms_snapshot' else None)
        self.assertEqual(snapshot_for_new_contract(source_with_snapshot), active_snapshot)

        v2_source = SimpleNamespace(get=lambda key: {'terms_version': 'v2', 'terms_snapshot': None}.get(key))
        self.assertEqual(snapshot_for_new_contract(v2_source), frozen_v2)
        self.assertEqual(clauses_for_contract(v2_source), json.loads(frozen_v2))

        legacy_source = SimpleNamespace(get=lambda key: None)
        self.assertEqual(snapshot_for_new_contract(legacy_source), frozen_snapshot)
        self.assertEqual(clauses_for_contract(legacy_source), json.loads(frozen_snapshot))

        d.terms_snapshot = '[]'
        with self.assertRaises(frappe.ValidationError):
            d.save()

    def test_missing_optional_print_stamp_is_safe(self):
        import base64
        from tempfile import TemporaryDirectory
        from pz_sales_contract.printing import _load_print_stamp
        with TemporaryDirectory() as directory:
            stamp_path = Path(directory) / 'petrol_zone_stamp.png'
            self.assertIsNone(_load_print_stamp(directory))
            stamp_path.write_bytes(b'synthetic print-only stamp fixture')
            expected = 'data:image/png;base64,' + base64.b64encode(stamp_path.read_bytes()).decode()
            self.assertEqual(_load_print_stamp(directory), expected)

    def test_public_history_stamp_is_not_embedded_in_new_prints(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from pz_sales_contract.printing import PUBLICLY_EXPOSED_STAMP_SHA256, _load_print_stamp
        with TemporaryDirectory() as directory:
            (Path(directory) / 'petrol_zone_stamp.png').write_bytes(b'synthetic stamp bytes')
            with patch('pz_sales_contract.printing.hashlib.sha256') as sha256:
                sha256.return_value.hexdigest.return_value = PUBLICLY_EXPOSED_STAMP_SHA256
                self.assertIsNone(_load_print_stamp(directory))

    def test_simplified_contract_rejects_specifications_omitted_from_its_print(self):
        doc = contract(insert=False, specifications=[dict(item_code='PZ Synthetic Bitumen',
            property='Penetration', unit='dmm', test_method='Synthetic method', requirement='60-70 (demo only)')])
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_legacy_contracts_require_specifications_while_v2_omits_them(self):
        specification = dict(item_code='PZ Synthetic Bitumen', property='Penetration', unit='dmm',
            test_method='Synthetic method', requirement='60-70 (demo only)')
        legacy = contract(insert=False, terms_version=None, delivery_date=today())
        with self.assertRaises(frappe.ValidationError):
            legacy.validate_legacy_contract_requirements()

        legacy = contract(insert=False, terms_version=None, delivery_date=today(),
            items=[
                dict(item_code='PZ Synthetic Bitumen', grade='60/70', packaging=None,
                    qty=10, uom='Nos', rate=100, specification_reference='Synthetic reference A'),
                dict(item_code='PZ Synthetic Binder', grade='80/100', packaging=None,
                    qty=5, uom='Nos', rate=100, specification_reference='Synthetic reference B'),
            ], specifications=[specification])
        with self.assertRaises(frappe.ValidationError):
            legacy.validate_legacy_contract_requirements()
        legacy.append('specifications', dict(specification, item_code='PZ Synthetic Binder'))
        legacy.validate_legacy_contract_requirements()

        simplified = contract(insert=False, terms_version=CURRENT_TERMS_VERSION)
        simplified.validate_specifications()
        simplified.append('specifications', specification)
        with self.assertRaises(frappe.ValidationError):
            simplified.validate_specifications()

    def test_legacy_packaging_is_derived_on_item_change_and_saved_for_print(self):
        for item_code in ('Bitumen - Bulk', 'Bitumen - Drum'):
            if not frappe.db.exists('Item', item_code):
                item = frappe.copy_doc(frappe.get_doc('Item', 'PZ Synthetic Bitumen'))
                item.item_code = item_code
                item.item_name = item_code
                item.insert()

        doc = contract(insert=False, items=[dict(item_code='Bitumen - Bulk',
            qty=10, uom='Nos', rate=100, grade_master=synthetic_bitumen_grade(),
            grade='PZ-SYNTHETIC-60-70', packaging='Untrusted input',
            specification_reference='Synthetic reference')])
        doc.insert()
        self.assertEqual(doc.items[0].packaging, 'Bulk')

        # Treat the saved document as a pre-policy record with the full legacy
        # schedule and specification data expected by the historical workflow.
        frappe.db.set_value(doc.doctype, doc.name, {
            'entry_policy_version': None,
            'party_entry_version': None,
            'customer_address': frappe.db.get_value('Dynamic Link', dict(parenttype='Address', link_doctype='Customer', link_name=doc.customer), 'parent'),
            'contact_person': frappe.db.get_value('Dynamic Link', dict(parenttype='Contact', link_doctype='Customer', link_name=doc.customer), 'parent'),
            'seller_address': 'PZ Synthetic Seller-Billing',
            'terms_version': None,
            'terms_snapshot': None,
            'contract_scope_version': None,
        })
        doc.reload()
        self.complete_legacy_schedule(doc)
        doc.timezone = 'Asia/Baghdad'
        doc.business_days = 'Monday,Tuesday,Wednesday,Thursday,Friday'
        doc.opens_at = '09:00:00'
        doc.closes_at = '17:00:00'
        doc.holiday_list = 'PZ Synthetic Calendar'
        doc.set('specifications', [])
        doc.append('specifications', dict(item_code='Bitumen - Bulk',
            property='Penetration', unit='dmm', test_method='Synthetic method',
            requirement='60-70 (demo only)'))
        doc.save()

        doc.items[0].item_code = 'Bitumen - Drum'
        doc.items[0].packaging = 'Bulk'
        doc.specifications[0].item_code = 'Bitumen - Drum'
        doc.save()
        doc.reload()
        self.assertEqual(doc.items[0].packaging, 'Drum')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(frappe.get_print(doc.doctype, doc.name,
            print_format='Standard'), 'html.parser')
        product_cell = soup.select('.contract section')[0].select('table')[1].select(
            'tbody tr')[0].select('td')[1]
        self.assertIn('· Drum', product_cell.get_text(' ', strip=True))

        # An unchanged legacy line keeps its persisted package snapshot.
        frappe.db.set_value('PZ Contract Item', doc.items[0].name,
            'packaging', 'Historical legacy snapshot')
        doc.reload()
        doc.save()
        self.assertEqual(doc.items[0].packaging, 'Historical legacy snapshot')

        old_row = doc.items[0]
        old_row_name = old_row.name
        replacement = dict(item_code=old_row.item_code, qty=old_row.qty,
            uom=old_row.uom, rate=old_row.rate, grade_master=old_row.grade_master,
            grade=old_row.grade, packaging='Historical legacy snapshot',
            specification_reference=old_row.specification_reference)
        doc.set('items', [])
        doc.append('items', replacement)
        doc.save()
        doc.reload()
        self.assertNotEqual(doc.items[0].name, old_row_name)
        self.assertEqual(doc.items[0].packaging, 'Drum')

        doc.items[0].item_code = 'PZ Synthetic Bitumen'
        doc.items[0].packaging = 'Drum'
        doc.specifications[0].item_code = 'PZ Synthetic Bitumen'
        doc.save()
        doc.reload()
        self.assertIsNone(doc.items[0].packaging)

        soup = BeautifulSoup(frappe.get_print(doc.doctype, doc.name,
            print_format='Standard'), 'html.parser')
        product_cell = soup.select('.contract section')[0].select('table')[1].select(
            'tbody tr')[0].select('td')[1]
        product_text = product_cell.get_text(' ', strip=True)
        self.assertIn('PZ Synthetic Bitumen', product_text)
        self.assertNotIn('·', product_text)
        self.assertNotIn('None', product_text)

    def test_legacy_schedule_cannot_bypass_missing_inputs_but_v2_has_no_schedule(self):
        legacy = contract(insert=False, terms_version=None, contract_scope_version=None,
            delivery_date=today(), specifications=[dict(item_code='PZ Synthetic Bitumen',
                property='Penetration', unit='dmm', test_method='Synthetic method',
                requirement='60-70 (demo only)')])
        legacy.timezone = None
        with self.assertRaises(frappe.ValidationError):
            legacy.validate_schedule()
        legacy.timezone = 'Asia/Baghdad'
        legacy.delivery_arrangement = None
        with self.assertRaises(frappe.ValidationError):
            legacy.validate_schedule()
        legacy.delivery_arrangement = 'Synthetic agreed delivery arrangement'
        legacy.governing_law = None
        with self.assertRaises(frappe.ValidationError):
            legacy.validate_schedule()

        simplified = contract(insert=False, contract_scope_version=ITEM_ONLY_DRAFT_SO_SCOPE)
        simplified.timezone = None
        simplified.validate_schedule()

    def test_missing_or_disabled_grade_master_blocks_a_new_line(self):
        missing = contract(insert=False)
        missing.items[0].grade_master = 'PZ Missing Bitumen Grade'
        with self.assertRaises(frappe.ValidationError):
            missing.insert()

        disabled_doc = contract(insert=False)
        grade_name = disabled_doc.items[0].grade_master
        original_disabled = frappe.db.get_value('Bitumen Grade', grade_name, 'disabled')
        frappe.db.set_value('Bitumen Grade', grade_name, 'disabled', 1)
        try:
            with self.assertRaises(frappe.ValidationError):
                disabled_doc.insert()
        finally:
            frappe.db.set_value('Bitumen Grade', grade_name, 'disabled', original_disabled or 0)

    def test_simplified_contract_cannot_submit_after_grade_link_was_cleared(self):
        d = contract()
        # The unchanged text snapshot may remain on the draft for history,
        # but it must not turn a new simplified line into a free-text line that can
        # create a Sales Order on submission.
        d.items[0].grade_master = None
        d.save()
        with self.assertRaises(frappe.ValidationError):
            d.submit()
        self.assertFalse(d.sales_order)

    def test_unchanged_disabled_grade_remains_savable_as_history(self):
        d = contract(submit=True)
        grade_name = d.items[0].grade_master
        snapshot = d.items[0].grade
        original_disabled = frappe.db.get_value('Bitumen Grade', grade_name, 'disabled')
        frappe.db.set_value('Bitumen Grade', grade_name, 'disabled', 1)
        try:
            d.reload().save()
            self.assertEqual(d.items[0].grade_master, grade_name)
            self.assertEqual(d.items[0].grade, snapshot)
        finally:
            frappe.db.set_value('Bitumen Grade', grade_name, 'disabled', original_disabled or 0)

    def test_old_free_text_grade_snapshot_remains_savable(self):
        d = contract()
        row_name = d.items[0].name
        frappe.db.set_value('PZ Contract Item', row_name, 'grade_master', None)
        frappe.db.set_value('PZ Contract Item', row_name, 'grade', 'Legacy free-text 60/70')
        d.reload().save()
        self.assertIsNone(d.items[0].grade_master)
        self.assertEqual(d.items[0].grade, 'Legacy free-text 60/70')

    def test_legacy_explicit_entry_without_company_defaults_still_works(self):
        self.clear_synthetic_company_defaults()
        from frappe.model.document import Document

        # insert() marks documents local before applying defaults. Match that
        # lifecycle when calling the helper directly in this comparison.
        actual_defaults = frappe.get_doc(dict(doctype='PZ Sales Contract', company=COMPANY, __islocal=1))
        native_defaults = frappe.get_doc(dict(doctype='PZ Sales Contract', company=COMPANY, __islocal=1))
        Document._set_defaults(native_defaults)
        actual_defaults._set_defaults()
        for fieldname in set(COMPANY_DEFAULT_FIELDS) - {'currency', 'conversion_rate', 'selling_price_list'}:
            self.assertEqual(actual_defaults.get(fieldname), native_defaults.get(fieldname), fieldname)
        self.assertEqual(actual_defaults.currency, 'USD')
        self.assertIsNone(actual_defaults.conversion_rate)
        self.assertIsNone(actual_defaults.selling_price_list)

        doc = contract()
        self.assertEqual(doc.currency, 'USD')
        self.assertEqual(doc.seller_signatory, 'Synthetic Seller')
        self.assertEqual(doc.bank_receiving_account, 'PZ Synthetic Bank - PZT')
        self.assertIsNone(doc.governing_law)

    def test_new_v3_clears_company_defaults_and_explicit_hidden_schedule_payloads(self):
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults().insert()
        doc = contract(insert=False)
        for fieldname in HISTORICAL_CONTRACT_FIELDS:
            field = doc.meta.get_field(fieldname)
            if field.fieldtype in {'Float', 'Int', 'Currency', 'Percent'}:
                value = 1
            elif field.fieldtype == 'Time':
                value = '10:00:00'
            elif field.fieldtype == 'Link':
                value = 'PZ Synthetic Calendar'
            elif field.fieldtype == 'Code':
                value = '{"synthetic":"explicit payload"}'
            else:
                value = f'Synthetic explicit payload for {fieldname}'
            doc.set(fieldname, value)
        doc.insert()
        self.assertEqual(doc.terms_version, CURRENT_TERMS_VERSION)
        self.assertEqual(doc.contract_scope_version, ITEM_ONLY_DRAFT_SO_SCOPE)
        for fieldname in HISTORICAL_CONTRACT_FIELDS:
            self.assertIsNone(doc.get(fieldname), fieldname)

        # A hidden field submitted again during a later save is discarded too.
        for fieldname in HISTORICAL_CONTRACT_FIELDS:
            doc.set(fieldname, f'Synthetic later payload for {fieldname}')
        doc.save()
        for fieldname in HISTORICAL_CONTRACT_FIELDS:
            self.assertIsNone(doc.get(fieldname), fieldname)

    def test_usd_entry_resolves_hidden_accounting_fields_and_preserves_saved_snapshots(self):
        self.clear_synthetic_company_defaults()
        settings = self.synthetic_company_defaults().insert()
        blanks = {fieldname: None for fieldname in COMPANY_DEFAULT_FIELDS}
        doc = contract(**(blanks | {'seller_signatory': 'Explicit signer'}))
        self.assertEqual(doc.currency, 'USD')
        self.assertEqual(doc.conversion_rate, 1)
        self.assertEqual(doc.selling_price_list, 'PZ Synthetic USD')
        self.assertEqual(doc.seller_signatory, 'Explicit signer')
        self.assertIsNone(doc.bank_receiving_account)
        self.assertEqual(doc.named_place, 'Synthetic pickup point')
        old_rate, old_list = doc.conversion_rate, doc.selling_price_list
        settings.seller_signatory = 'Changed default signer'
        settings.save()
        doc.reload().save()
        self.assertEqual((doc.conversion_rate, doc.selling_price_list), (old_rate, old_list))
        self.assertEqual(doc.seller_signatory, 'Explicit signer')
        with self.assertRaisesRegex(frappe.ValidationError, 'must use USD'):
            contract(currency='EUR', conversion_rate=1.2)

    def test_existing_foreign_currency_contract_retains_its_recorded_currency_and_rate(self):
        self.clear_synthetic_company_defaults()
        eur_list = 'PZ Synthetic Historic EUR'
        if not frappe.db.exists('Price List', eur_list):
            frappe.get_doc(dict(doctype='Price List', price_list_name=eur_list,
                currency='EUR', selling=1, enabled=1)).insert()
        eur_bank = self.synthetic_alternate_bank_account('EUR')
        doc = contract()
        # Model a pre-cutover saved record, not a new foreign-currency request.
        frappe.db.set_value(doc.doctype, doc.name, dict(entry_policy_version=None,
            currency='EUR', conversion_rate=1.2, selling_price_list=eur_list,
            bank_receiving_account=eur_bank, cash_receiving_account=None))
        doc.reload().save()
        self.assertEqual((doc.currency, doc.conversion_rate, doc.selling_price_list), ('EUR', 1.2, eur_list))

    def test_contract_location_rename_preserves_saved_print_snapshot(self):
        location = frappe.get_doc(dict(doctype='PZ Contract Location', location_name='Synthetic original port')).insert()
        doc = contract(contract_location=location.name)
        self.assertEqual(doc.named_place, 'Synthetic original port')
        location.location_name = 'Synthetic renamed port'
        location.save()
        doc.reload().save()
        self.assertEqual(doc.named_place, 'Synthetic original port')
        later = contract(contract_location=location.name)
        self.assertEqual(later.named_place, 'Synthetic renamed port')
        location.disabled = 1
        location.save()
        doc.reload().save()
        with self.assertRaisesRegex(frappe.ValidationError, 'enabled Incoterm location'):
            contract(contract_location=location.name)

    def test_packaging_is_derived_after_item_change_and_printed_from_saved_value(self):
        for item_code in ('Bitumen - Bulk', 'Bitumen - Drum'):
            if not frappe.db.exists('Item', item_code):
                item = frappe.copy_doc(frappe.get_doc('Item', 'PZ Synthetic Bitumen'))
                item.item_code = item_code
                item.item_name = item_code
                item.insert()

        doc = contract(insert=False)
        doc.items[0].item_code = 'Bitumen - Bulk'
        doc.items[0].packaging = 'Untrusted input'
        doc.insert()
        self.assertEqual(doc.items[0].packaging, 'Bulk')

        doc.items[0].item_code = 'Bitumen - Drum'
        doc.items[0].packaging = 'Bulk'
        doc.save()
        doc.reload()
        self.assertEqual(doc.items[0].packaging, 'Drum')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(frappe.get_print(doc.doctype, doc.name, print_format='Standard'), 'html.parser')
        product_cell = soup.select('.contract section')[0].select('table')[1].select('tbody tr')[0].select('td')[1]
        product_text = product_cell.get_text(' ', strip=True)
        self.assertIn('Bitumen - Drum', product_text)
        self.assertIn('· Drum', product_text)

    def test_unknown_item_packaging_is_blank_and_not_claimed_in_print(self):
        doc = contract(insert=False)
        doc.items[0].packaging = 'Synthetic drums'
        doc.insert()
        self.assertIsNone(doc.items[0].packaging)

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(frappe.get_print(doc.doctype, doc.name, print_format='Standard'), 'html.parser')
        product_cell = soup.select('.contract section')[0].select('table')[1].select('tbody tr')[0].select('td')[1]
        product_text = product_cell.get_text(' ', strip=True)
        self.assertIn('PZ Synthetic Bitumen', product_text)
        self.assertNotIn('·', product_text)
        self.assertNotIn('None', product_text)

    def test_contract_location_create_permission_is_limited_to_managers(self):
        user = 'pz-location-reader@example.invalid'
        if not frappe.db.exists('User', user):
            frappe.get_doc(dict(doctype='User', email=user, first_name='Synthetic location reader',
                send_welcome_email=0, roles=[dict(role='PZ Sales Contract User')])).insert()
        self.assertTrue(frappe.has_permission('PZ Contract Location', 'read', user=user))
        self.assertFalse(frappe.has_permission('PZ Contract Location', 'create', user=user))

    def test_alternate_bank_does_not_inherit_unrelated_optional_payment_instructions(self):
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults().insert()
        alternate_bank = self.synthetic_alternate_bank_account()
        blank_instructions = dict.fromkeys(
            ('beneficiary', 'bank_branch', 'account_iban', 'swift_reference')
        )
        doc = contract(insert=False, bank_receiving_account=alternate_bank, **blank_instructions)
        doc.insert()
        self.assertEqual(doc.bank_receiving_account, alternate_bank)
        for fieldname in blank_instructions:
            self.assertIsNone(doc.get(fieldname), fieldname)

        own_instructions = {
            'beneficiary': 'SYNTHETIC ALTERNATE BENEFICIARY',
            'bank_branch': 'SYNTHETIC ALTERNATE BRANCH',
            'account_iban': 'USD / SYNTHETIC-ALTERNATE-ACCOUNT',
            'swift_reference': 'SYNTHETIC ALTERNATE REFERENCE',
        }
        complete = contract(bank_receiving_account=alternate_bank, **own_instructions)
        for fieldname, value in own_instructions.items():
            self.assertEqual(complete.get(fieldname), value, fieldname)

    def test_company_defaults_links_currency_and_accounts_fail_closed(self):
        from pz_sales_contract.testing import new_customer

        customer, customer_address, _ = new_customer()
        wrong_address = self.synthetic_company_defaults(seller_address=customer_address.name)
        with self.assertRaises(frappe.ValidationError):
            wrong_address.validate()

        wrong_price_currency = self.synthetic_company_defaults(currency='EUR', selling_price_list='PZ Synthetic USD')
        with self.assertRaises(frappe.ValidationError):
            wrong_price_currency.validate()

        wrong_account_kind = self.synthetic_company_defaults(bank_receiving_account='PZ Synthetic Cash - PZT')
        with self.assertRaises(frappe.ValidationError):
            wrong_account_kind.validate()

        wrong_account_currency = self.synthetic_company_defaults(currency='EUR', selling_price_list=None)
        with self.assertRaises(frappe.ValidationError):
            wrong_account_currency.validate()

        # The contract's existing link validation remains the final authority,
        # including for an invalid default modified outside normal Desk validation.
        self.clear_synthetic_company_defaults()
        frappe.db.savepoint('invalid_company_contract_defaults')
        bad_settings = self.synthetic_company_defaults().insert()
        bad_settings.db_set('seller_address', customer_address.name)
        direct = contract(customer=customer, seller_address=None)
        self.assertIsNone(direct.seller_address)
        frappe.db.rollback(save_point='invalid_company_contract_defaults')

    def test_defaults_api_is_limited_to_contract_creators_and_company_scope(self):
        self.clear_synthetic_company_defaults()
        settings = self.synthetic_company_defaults().insert()
        frappe.set_user('pz-sales@example.invalid')
        self.assertFalse(frappe.has_permission('PZ Contract Defaults', 'read'))
        self.assertFalse(frappe.has_permission('PZ Contract Defaults', 'write'))
        self.assertFalse(frappe.has_permission('PZ Contract Defaults', 'create'))
        returned = get_company_defaults(COMPANY)
        self.assertEqual(returned['bank_receiving_account'], settings.bank_receiving_account)
        self.assertNotIn('governing_law', returned)
        self.assertEqual(returned['allowed_incoterms'], ['EXW', 'FOB', 'CIF'])
        self.assertNotIn('company', returned)
        with self.assertRaises(frappe.FrappeTypeError):
            get_company_defaults({'name': COMPANY})

    def test_contract_incoterms_require_builtin_or_company_enabled_master(self):
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults(
            additional_incoterms=[dict(incoterm='FCA')],
        ).insert()
        self.assertEqual(get_company_defaults(COMPANY)['allowed_incoterms'], ['EXW', 'FOB', 'CIF', 'FCA'])
        self.assertEqual(contract(incoterm='FCA').incoterm, 'FCA')

        self.clear_synthetic_company_defaults()
        with self.assertRaises(frappe.ValidationError):
            contract(incoterm='FCA')

    def test_defaults_record_company_cannot_be_changed(self):
        self.clear_synthetic_company_defaults()
        settings = self.synthetic_company_defaults().insert()
        settings.company = 'PZ Synthetic Other Company'
        with self.assertRaises(frappe.ValidationError):
            settings.save()
        settings.reload()
        self.assertEqual(settings.company, COMPANY)

    def test_defaults_follow_native_company_rename(self):
        self.clear_synthetic_company_defaults()
        settings = self.synthetic_company_defaults().insert()
        renamed_company = 'PZ Synthetic Renamed Defaults Company'
        frappe.rename_doc('Company', COMPANY, renamed_company, force=True)
        try:
            settings.reload()
            self.assertEqual(settings.company, renamed_company)
            self.assertEqual(settings.name, COMPANY)
            self.assertEqual(get_company_defaults(renamed_company)['seller_signatory'], settings.seller_signatory)
            doc = contract(company=renamed_company, seller_signatory=None)
            self.assertEqual(doc.seller_signatory, settings.seller_signatory)
        finally:
            # Native IntegrationTestCase shares fixture state between methods.
            frappe.rename_doc('Company', renamed_company, COMPANY, force=True)

    def test_first_and_returning_contracts_and_no_toggle(self):
        first=contract(submit=True)
        self.assertTrue(payment_status(first).payment_draft)
        second=contract(customer=first.customer,submit=True)
        self.assertFalse(payment_status(second).payment_draft)
        first.first_family='forged'
        with self.assertRaises(frappe.ValidationError):
            first.save()

    def test_customer_refunds_reduce_current_advance(self):
        d=contract(submit=True)
        receipt(d,300,cash=True)
        outgoing=refund(d,100)
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'advance_paid'),200)
        self.assertEqual(payment_status(d).confirmed,200)
        self.assertTrue(payment_status(d).payment_draft)
        receipt(d,100,cash=True)
        self.assertEqual(payment_status(d).confirmed,300)
        self.assertFalse(payment_status(d).payment_draft)
        self.assertIn(dict(payment_entry=outgoing.name,allocated=-100.0),payment_status(d).evidence)
        outgoing.db_set('paid_to_account_currency','EUR')
        self.assertTrue(payment_status(d).payment_draft)
        outgoing.db_set('paid_to_account_currency','USD')
        outgoing.cancel()
        self.assertEqual(payment_status(d).confirmed,400)

    def test_unallocated_and_mixed_customer_refunds_fail_closed(self):
        first=contract(submit=True)
        other=contract(customer=first.customer,submit=True)
        receipt(first,300,cash=True)
        ambiguous=refund(other,100,allocations=[('Sales Order',other.sales_order,50)])
        self.assertEqual(ambiguous.unallocated_amount,50)
        self.assertTrue(payment_status(first).payment_draft)
        ambiguous.cancel()
        unrelated=refund(other,100)
        self.assertEqual(unrelated.unallocated_amount,0)
        self.assertEqual(payment_status(first).confirmed,300)
        mixed=refund(first,200,allocations=[('Sales Order',first.sales_order,100),
            ('Sales Order',other.sales_order,100)])
        self.assertEqual(mixed.unallocated_amount,0)
        self.assertEqual(payment_status(first).confirmed,200)
        self.assertTrue(payment_status(first).payment_draft)
        receipt(first,100,cash=True)
        self.assertFalse(payment_status(first).payment_draft)

    def test_native_invoice_refund_reduces_advance_evidence(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        d=contract(submit=True)
        receipt(d,300,cash=True)
        invoice=make_sales_invoice(d.sales_order)
        invoice.set_advances()
        for advance in invoice.advances:
            advance.allocated_amount=advance.advance_amount
        invoice.insert()
        invoice.submit()
        self.assertFalse(payment_status(d).payment_draft)
        refund(d,300,reference_doctype='Sales Invoice',reference_name=invoice.name)
        self.assertEqual(payment_status(d).confirmed,0)
        self.assertTrue(payment_status(d).payment_draft)

    def test_native_credit_note_refund_reduces_advance_evidence(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        d=contract(submit=True)
        receipt(d,300,cash=True)
        invoice=make_sales_invoice(d.sales_order)
        invoice.set_advances()
        for advance in invoice.advances:
            advance.allocated_amount=advance.advance_amount
        invoice.insert().submit()
        credit_note=make_sales_return(invoice.name)
        credit_note.set('advances',[])
        for item in credit_note.items:
            item.sales_order=item.so_detail=None
        credit_note.insert().submit()
        self.assertFalse(payment_status(d).payment_draft)
        outgoing=refund(d,300,reference_doctype='Sales Invoice',reference_name=credit_note.name,
            allocations=[('Sales Invoice',credit_note.name,-300)])
        self.assertEqual(outgoing.references[0].allocated_amount,-300)
        self.assertEqual(payment_status(d).confirmed,0)
        self.assertTrue(payment_status(d).payment_draft)
        outgoing.cancel()
        self.assertFalse(payment_status(d).payment_draft)

    def test_native_journal_cash_refund_fails_closed(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        d=contract(submit=True)
        receipt(d,300,cash=True)
        invoice=make_sales_invoice(d.sales_order)
        invoice.set_advances()
        for advance in invoice.advances:
            advance.allocated_amount=advance.advance_amount
        invoice.insert().submit()
        outgoing=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',
            company=COMPANY,posting_date=today(),user_remark='Synthetic cash refund regression',
            accounts=[dict(account=invoice.debit_to,party_type='Customer',party=d.customer,
                debit_in_account_currency=300,reference_type='Sales Invoice',
                reference_name=invoice.name,is_advance='No'),
                dict(account='PZ Synthetic Cash - PZT',credit_in_account_currency=300)])).insert()
        outgoing.submit()
        self.assertEqual(outgoing.docstatus,1)
        self.assertEqual(payment_status(d).confirmed,0)
        self.assertTrue(payment_status(d).payment_draft)
        outgoing.cancel()
        self.assertFalse(payment_status(d).payment_draft)

    def test_mixed_invoice_and_credit_note_refunds_fail_closed(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        first=contract(submit=True)
        other=contract(customer=first.customer,submit=True)
        receipt(first,300,cash=True)
        invoice=make_sales_invoice(first.sales_order)
        other_invoice=make_sales_invoice(other.sales_order)
        invoice.append('items',other_invoice.items[0].as_dict())
        invoice.set('advances',[])
        invoice.insert().submit()
        self.assertEqual(payment_status(first).confirmed,300)
        outgoing=refund(first,100,reference_doctype='Sales Invoice',reference_name=invoice.name)
        self.assertTrue(payment_status(first).payment_draft)
        outgoing.cancel()
        credit_note=make_sales_return(invoice.name)
        credit_note.set('advances',[])
        for item in credit_note.items:
            item.sales_order=item.so_detail=None
        multiple_items=frappe.db.get_single_value('Selling Settings','allow_multiple_items')
        try:
            frappe.db.set_single_value('Selling Settings','allow_multiple_items',1)
            credit_note.insert().submit()
        finally:
            frappe.db.set_single_value('Selling Settings','allow_multiple_items',multiple_items)
        outgoing=refund(first,200,reference_doctype='Sales Invoice',reference_name=credit_note.name,
            allocations=[('Sales Invoice',credit_note.name,-200)])
        self.assertTrue(payment_status(first).payment_draft)
        outgoing.cancel()
        self.assertFalse(payment_status(first).payment_draft)

    def test_unsupported_persisted_refund_reference_fails_closed(self):
        d=contract(submit=True)
        receipt(d,400,cash=True)
        receivable=frappe.db.get_value('Company',COMPANY,'default_receivable_account')
        expense=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Expense'),'name')
        credit=frappe.get_doc(dict(doctype='Journal Entry',voucher_type='Journal Entry',
            company=COMPANY,posting_date=today(),user_remark='Synthetic unsupported refund reference',
            accounts=[dict(account=receivable,party_type='Customer',party=d.customer,
                credit_in_account_currency=300,is_advance='No'),
                dict(account=expense,debit_in_account_currency=300,
                    cost_center=frappe.db.get_value('Company',COMPANY,'cost_center'))])).insert()
        credit.submit()
        self.assertFalse(payment_status(d).payment_draft)
        outgoing=refund(d,100)
        self.assertEqual(outgoing.unallocated_amount,0)
        self.assertFalse(payment_status(d).payment_draft)
        # Adversarial persisted reference on an otherwise valid native payout.
        # Current native v16 rejects this JE allocation at entry time; older or
        # external data must still fail closed rather than silently count it.
        outgoing.references[0].db_set('reference_doctype','Journal Entry')
        outgoing.references[0].db_set('reference_name',credit.name)
        self.assertTrue(payment_status(d).payment_draft)
        outgoing.references[0].db_set('reference_doctype','Sales Order')
        outgoing.references[0].db_set('reference_name',d.sales_order)
        outgoing.cancel()
        self.assertFalse(payment_status(d).payment_draft)

    def test_print_and_payment_evidence_respect_native_currency_precision(self):
        from bs4 import BeautifulSoup
        previous=frappe.defaults.get_global_default('currency_precision')
        try:
            for digits,qty,rate,total,required,partial,shortfall,balance in [
                (2,3,100.12,300.36,90.11,90.10,0.01,210.25),
                (3,3,100.125,300.375,90.113,90.112,0.001,210.262)]:
                with self.subTest(currency_precision=digits):
                    frappe.defaults.set_global_default('currency_precision',str(digits))
                    d=contract(submit=True,items=[dict(item_code='PZ Synthetic Bitumen',qty=qty,uom='Nos',
                        rate=rate,grade_master=synthetic_bitumen_grade(),grade='PZ-SYNTHETIC-60-70',
                        packaging='Synthetic drums',specification_reference='Synthetic precision QA')])
                    self.assertEqual((d.grand_total,d.advance_required),(total,required))
                    self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'grand_total'),total)
                    receipt(d,partial,cash=True)
                    self.assertTrue(payment_status(d).payment_draft)
                    soup=BeautifulSoup(frappe.get_print(d.doctype,d.name,print_format='Standard'),'html.parser')
                    row=soup.select('.contract section')[0].select('table')[1].select('tbody tr')[0]
                    self.assertEqual([c.get_text(strip=True) for c in row.select('td')][5:],
                        [f'{rate:.{digits}f}',f'{total:.{digits}f}'])
                    totals={r.select('td')[0].get_text(strip=True):r.select('td')[1].get_text(strip=True)
                        for r in soup.select('.totals tr')}
                    for key,value in [('Subtotal',total),('Contract Amount · USD',total),('30% advance',required),('70% balance',balance)]:
                        self.assertEqual(totals[key],f'{value:.{digits}f}')
                    # The amount remains a visible contract total, while finance
                    # evidence no longer appears in the print or controls its mark.
                    self.assertNotIn('Confirmed receipt allocation',soup.get_text())
                    self.assertNotIn('30% advance:',soup.get_text())
                    status=get_status(d.name)
                    self.assertEqual((status.currency_precision,status.required,status.confirmed),(digits,required,partial))
                    receipt(d,shortfall,cash=True)
                    self.assertFalse(payment_status(d).payment_draft)
        finally:
            frappe.defaults.set_global_default('currency_precision',previous)

    def test_bank_draft_manual_date_partial_threshold_and_cancellation(self):
        d=contract(submit=True)
        draft=receipt(d,50,submit=False)
        self.assertEqual(payment_status(d).confirmed,0)
        draft.delete()
        one=receipt(d,100)
        one.db_set('clearance_date',today())
        self.assertEqual(payment_status(d).confirmed,0)
        draft_bt=reconcile(one,self.bank_account,submit=False)
        self.assertEqual(payment_status(d).confirmed,0)
        draft_bt.delete()
        bt1=reconcile(one,self.bank_account)
        self.assertTrue(payment_status(d).payment_draft)
        self.assertEqual(payment_status(d).confirmed,100)
        two=receipt(d,200)
        bt2=reconcile(two,self.bank_account)
        self.assertFalse(payment_status(d).payment_draft)
        self.assertEqual(payment_status(d).confirmed,300)
        bt2.cancel()
        self.assertTrue(payment_status(d).payment_draft)
        self.assertEqual(payment_status(d).confirmed,100)
        one.reload().cancel()
        self.assertEqual(payment_status(d).confirmed,0)

    def test_partly_bank_reconciled_receipt_is_not_assigned_arbitrarily(self):
        d=contract(submit=True)
        p=receipt(d,400)
        reconcile(p,self.bank_account,amount=100)
        self.assertTrue(payment_status(d).payment_draft)
        self.assertEqual(payment_status(d).confirmed,0)
        reconcile(p,self.bank_account,amount=300)
        self.assertEqual(payment_status(d).confirmed,400)
        self.assertFalse(payment_status(d).payment_draft)

    def test_cash_and_cancelled_cash(self):
        d=contract(submit=True)
        p=receipt(d,299,cash=True)
        self.assertTrue(payment_status(d).payment_draft)
        q=receipt(d,1,cash=True)
        self.assertFalse(payment_status(d).payment_draft)
        q.cancel()
        self.assertTrue(payment_status(d).payment_draft)

    def test_unrelated_currency_company_and_unallocated_do_not_count(self):
        d=contract(submit=True)
        other=contract(submit=True)
        p=receipt(other,300,cash=True)
        self.assertEqual(payment_status(d).confirmed,0)
        p2=receipt(d,300,cash=True)
        self.assertEqual(payment_status(d).confirmed,300)
        # Adversarial persisted fields on synthetic records: validator must fail closed.
        p2.db_set('paid_to_account_currency','EUR')
        self.assertEqual(payment_status(d).confirmed,0)
        p2.db_set('paid_to_account_currency','USD')
        p2.db_set('company','Wrong company (synthetic)')
        self.assertEqual(payment_status(d).confirmed,0)

    def test_cancel_amend_and_reservation_retained(self):
        self.clear_synthetic_company_defaults()
        settings = self.synthetic_company_defaults(
            seller_signatory='Synthetic approved signer at creation',
            cash_receiving_account=None,
        ).insert()
        d=contract(submit=True, seller_signatory=None, cash_receiving_account=None, print_as_draft=1)
        self.assertEqual(d.seller_signatory, 'Synthetic approved signer at creation')
        self.assertIsNone(d.cash_receiving_account)
        frappe.db.set_value('PZ Contract Item', d.items[0].name,
            'packaging', 'Historical amendment snapshot')
        d.reload()
        settings.seller_signatory = 'Synthetic later default; never rewrite an agreed contract'
        settings.cash_receiving_account = 'PZ Synthetic Cash - PZT'
        settings.save()
        family=d.first_family
        d.cancel()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'docstatus'),2)
        # Simulate fields retained on an older canceled record; v2 save/submit
        # paths intentionally clear these fields before cancellation.
        d.db_set('governing_law', 'Synthetic historical law retained on amendment')
        d.db_set('approval_received', '2026-10-01T09:00:00+03:00')
        d.db_set('advance_deadline', '2026-10-02T09:00:00+03:00')
        d.reload()
        amendment=frappe.copy_doc(d)
        # Server-side frappe.copy_doc copies fields directly; native Desk uses
        # DocField.no_copy when it builds an amendment. Simulate that copy rule.
        amendment.print_as_draft = 0
        amendment.docstatus=0
        amendment.amended_from=d.name
        amendment.sales_order=None
        amendment.first_family=None
        frappe.set_user('pz-sales@example.invalid')
        self.assertFalse(frappe.has_permission(d.doctype,'amend'))
        denied=frappe.copy_doc(amendment)
        denied.amended_from=d.name
        with self.assertRaises(frappe.PermissionError):
            denied.insert()
        frappe.set_user('Administrator')
        amendment.insert()
        self.assertEqual(amendment.print_as_draft, 0)
        self.assertEqual(d.reload().print_as_draft, 1)
        self.assertEqual(amendment.terms_version, CURRENT_TERMS_VERSION)
        self.assertEqual(amendment.items[0].packaging, 'Historical amendment snapshot')
        self.assertEqual(amendment.governing_law, 'Synthetic historical law retained on amendment')
        self.assertEqual(amendment.approval_received, '2026-10-01T09:00:00+03:00')
        self.assertEqual(amendment.advance_deadline, '2026-10-02T09:00:00+03:00')
        self.assertEqual(amendment.seller_signatory, 'Synthetic approved signer at creation')
        self.assertIsNone(amendment.cash_receiving_account)
        self.assertEqual(amendment.first_family,family)
        self.assertTrue(payment_status(amendment).payment_draft)
        amendment.submit()
        self.assertNotEqual(amendment.sales_order,d.sales_order)
        self.assertFalse(payment_status(contract(customer=d.customer)).payment_draft)
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc('PZ Sales Contract',d.name,ignore_permissions=True)

    def test_generic_erp_roles_do_not_grant_contract_access(self):
        users = {}
        for index, role in enumerate(['Sales User', 'Sales Manager', 'Accounts Manager', 'System Manager']):
            user = f'pz-generic-{index}@example.invalid'
            frappe.get_doc(dict(doctype='User', email=user, first_name='Synthetic generic role',
                send_welcome_email=0, roles=[dict(role=role)])).insert()
            users[role] = user
            for action in ['read', 'create', 'write', 'submit', 'cancel', 'amend', 'print']:
                with self.subTest(user=user, action=action):
                    self.assertFalse(frappe.has_permission('PZ Sales Contract', action, user=user))
            for action in ['read', 'create', 'write', 'delete']:
                with self.subTest(user=user, doctype='PZ Contract Defaults', action=action):
                    self.assertEqual(
                        frappe.has_permission('PZ Contract Defaults', action, user=user),
                        role == 'System Manager',
                    )
        # Unrelated native finance permissions must remain intact.
        self.assertTrue(frappe.has_permission('PZ Customer History', 'create', user=users['Accounts Manager']))

    def test_permissions_sales_user_cannot_submit_pay_or_modify_registry(self):
        d=contract()
        frappe.set_user('pz-sales@example.invalid')
        self.assertTrue(frappe.has_permission('PZ Sales Contract','create'))
        self.assertFalse(frappe.has_permission('PZ Sales Contract','submit'))
        self.assertFalse(frappe.has_permission('Payment Entry','submit'))
        self.assertFalse(frappe.has_permission('Bank Transaction','write'))
        self.assertFalse(frappe.has_permission('PZ Contract Registry','write'))
        created=contract(customer=d.customer)
        self.assertEqual(created.owner,'pz-sales@example.invalid')
        with self.assertRaises(frappe.PermissionError):
            d.submit()
        self.assertTrue(get_status(d.name).payment_draft)
        frappe.set_user('pz-manager@example.invalid')
        for action in ['read', 'create', 'write', 'submit', 'cancel', 'amend', 'print']:
            self.assertTrue(frappe.has_permission('PZ Sales Contract', action))
        self.assertFalse(frappe.has_permission('PZ Customer History', 'create'))
        self.assertFalse(frappe.has_permission('Payment Entry', 'submit'))
        self.assertFalse(frappe.has_permission('PZ Contract Registry', 'write'))
        d.reload().submit()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'docstatus'),0)

    def test_print_standard_forged_payload_and_cancelled(self):
        d=contract(submit=True, print_as_draft=1)
        html=frappe.get_print('PZ Sales Contract',d.name,print_format='Standard')
        self.assertIn('>DRAFT<',html)
        self.assertNotIn('FIRST ADVANCE',html)
        clauses = json.loads((Path(__file__).resolve().parents[3] / 'terms.json').read_text())
        self.assertEqual(len(clauses), 15)
        for number, clause in enumerate(clauses, start=1):
            heading = clause.split('. ', 1)[1].split('. ', 1)[0]
            self.assertIn(f'{number}. {heading}.', html)
        self.assertIn('Contract Amount · USD',html)
        self.assertIn('linked Sales Order or invoice',html)
        self.assertNotIn('Appendix A',html)
        self.assertNotIn('<h2>Commercial Schedule</h2>',html)
        self.assertNotIn('Order and Collection Record',html)
        self.assertNotIn('PAYMENT REQUIRED WITHIN 24 BUSINESS HOURS',html)
        self.assertNotIn('collection charges and force majeure',html.lower())
        self.assertIn('Each signatory confirms that they are authorised to sign',html)
        from frappe.www.printview import get_html_and_style
        forged=d.as_dict()
        forged['customer_name']='FORGED BUYER'
        forged['first_family']='FORGED FAMILY'
        output=get_html_and_style(doc=json.dumps(forged,default=str),print_format='Standard')['html']
        self.assertNotIn('FORGED BUYER',output)
        self.assertIn('>DRAFT<',output)
        paid=receipt(d,300,cash=True)
        # Payment arrival does not change the operator's saved print choice.
        self.assertIn('>DRAFT<',frappe.get_print('PZ Sales Contract',d.name))
        paid.cancel()
        d.cancel()
        cancelled = frappe.get_print('PZ Sales Contract',d.name)
        self.assertIn('CANCELLED CONTRACT',cancelled)
        self.assertNotIn('>DRAFT<',cancelled)

    def test_pre_version_contract_keeps_legacy_print_and_v1_terms(self):
        d = contract()
        frappe.db.set_value('PZ Sales Contract', d.name, 'terms_version', None)
        frappe.db.set_value('PZ Sales Contract', d.name, 'terms_snapshot', None)
        frappe.db.set_value('PZ Sales Contract', d.name, 'contract_scope_version', None)
        frappe.get_doc(dict(doctype='PZ Contract Specification', parent=d.name,
            parenttype='PZ Sales Contract', parentfield='specifications', idx=1,
            item_code='PZ Synthetic Bitumen', property='Penetration', unit='dmm',
            test_method='Synthetic method', requirement='60-70 (demo only)')).insert(ignore_permissions=True)

        html = frappe.get_print('PZ Sales Contract', d.name, print_format='Standard')
        self.assertIn('Commercial Schedule', html)
        self.assertIn('Appendix A · Agreed Product Specification', html)
        self.assertIn('Order and Collection Record', html)
        self.assertNotIn('PAYMENT REQUIRED WITHIN 24 BUSINESS HOURS', html)
        self.assertIn('15. Authority, Law and Complete Agreement.', html)

    def test_schedule_deadlines_not_clock_days(self):
        year=frappe.utils.getdate(today()).year
        d=contract()
        d.db_set('terms_version', None)
        d.db_set('contract_scope_version', None)
        d.db_set('terms_snapshot', None)
        d.reload()
        self.complete_legacy_schedule(d)
        d.delivery_date = today()
        d.timezone = 'Asia/Baghdad'
        d.business_days = 'Monday,Tuesday,Wednesday,Thursday,Friday'
        d.opens_at = '09:00:00'
        d.closes_at = '17:00:00'
        d.holiday_list = 'PZ Synthetic Calendar'
        d.collection_grace = 48
        d.grace_unit = 'Calendar hours'
        d.approval_received = f'{year}-10-05T16:00:00+03:00'
        d.approval_evidence = 'Synthetic written approval and acceptance'
        d.save()
        self.assertEqual(d.advance_deadline,f'{year}-10-08T16:00:00+03:00')
        d.approval_received = f'{year}-10-05T16:00:00'
        with self.assertRaises(frappe.ValidationError):
            d.save()

    def test_native_invoice_reconciliation_keeps_receipt_evidence(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        d=contract(submit=True)
        p=receipt(d,300,cash=True)
        si=make_sales_invoice(d.sales_order)
        si.set_advances()
        self.assertTrue(si.advances)
        for advance in si.advances:
            advance.allocated_amount=advance.advance_amount
        si.insert()
        si.submit()
        p.reload()
        self.assertTrue(any(r.reference_doctype=='Sales Invoice' and r.reference_name==si.name for r in p.references))
        self.assertFalse(payment_status(d).payment_draft)
        si.items[0].db_set('sales_order','UNRELATED-SYNTHETIC-ORDER')
        self.assertTrue(payment_status(d).payment_draft)

    def test_customer_rename_does_not_reset_identity(self):
        first=contract(submit=True)
        renamed='PZ Synthetic Renamed '+frappe.generate_hash(length=8)
        frappe.rename_doc('Customer',first.customer,renamed,force=True)
        first.reload()
        later=contract(customer=renamed)
        self.assertTrue(payment_status(first).payment_draft)
        self.assertFalse(payment_status(later).payment_draft)

    def test_beta_print_renderer_rejected(self):
        from pz_sales_contract.printing import validate_format,guard_renderer
        with self.assertRaises(frappe.ValidationError):
            validate_format(frappe._dict(doc_type='PZ Sales Contract',print_format_builder_beta=1))
        # Simulate an already configured format in this disposable test site.
        pf=frappe.get_doc('Print Format','Petrol Zone Sales Contract')
        pf.db_set('print_format_builder_beta',1)
        old=frappe.local.form_dict
        try:
            frappe.local.form_dict=frappe._dict(doctype='PZ Sales Contract',format=pf.name)
            with self.assertRaises(frappe.ValidationError): guard_renderer()
            frappe.local.form_dict=frappe._dict(doctype='PZ Sales Contract')
            with self.assertRaises(frappe.ValidationError): guard_renderer()
            frappe.local.form_dict=frappe._dict(doctype='PZ Sales Contract',cmd='frappe.utils.weasyprint.download_pdf',doc=json.dumps({'doctype':'Sales Order'}))
            with self.assertRaises(frappe.ValidationError): guard_renderer()
            for command in ['frappe.utils.print_format.download_multi_pdf','frappe.utils.print_format.download_multi_pdf_async']:
                frappe.local.form_dict=frappe._dict(doctype={'PZ Sales Contract':['synthetic']},cmd=command,format=pf.name)
                with self.assertRaises(frappe.ValidationError): guard_renderer()
        finally:
            frappe.local.form_dict=old
            pf.db_set('print_format_builder_beta',0)

    def test_weasyprint_download_aliases_rejected_before_render(self):
        from pz_sales_contract.printing import guard_renderer
        from frappe.utils.weasyprint import download_pdf
        from frappe.printing.doctype.print_format.print_format import download_pdf as alias
        self.assertIs(alias,download_pdf)
        self.assertIn(alias,frappe.whitelisted)
        old_values,old_request=frappe.local.form_dict,getattr(frappe.local,'request',None)
        try:
            for command in ['frappe.utils.weasyprint.download_pdf',
                    'frappe.printing.doctype.print_format.print_format.download_pdf']:
                with self.subTest(command=command):
                    frappe.local.form_dict=frappe._dict(doctype='PZ Sales Contract',
                        cmd=command,print_format='Standard')
                    frappe.local.request=frappe._dict(path='/api/method')
                    with self.assertRaises(frappe.ValidationError): guard_renderer()
            # Explicit route identity must win over a misleading body cmd. API v2
            # also supports a DocType shortcut expanded after before_request hooks.
            for path in ['/api/method/frappe.utils.weasyprint.download_pdf',
                    '/api/v2/method/frappe.printing.doctype.print_format.print_format.download_pdf',
                    '/api/v2/method/Print Format/download_pdf']:
                with self.subTest(path=path):
                    frappe.local.form_dict=frappe._dict(doctype='PZ Sales Contract',
                        cmd='frappe.utils.print_format.download_pdf',print_format='Standard')
                    frappe.local.request=frappe._dict(path=path)
                    with self.assertRaises(frappe.ValidationError): guard_renderer()
                    frappe.local.form_dict.doctype='Sales Order'
                    guard_renderer()
        finally:
            frappe.local.form_dict,frappe.local.request=old_values,old_request

    def test_chrome_format_configuration_rejected(self):
        from pz_sales_contract.printing import validate_format,guard_renderer
        with self.assertRaises(frappe.ValidationError):
            validate_format(frappe._dict(doc_type='PZ Sales Contract',pdf_generator='chrome'))
        pf=frappe.get_doc('Print Format','Petrol Zone Sales Contract')
        old_generator,old_values=pf.pdf_generator,frappe.local.form_dict
        try:
            # A preexisting stored renderer is selected by native batch printing
            # even when the request has no explicit pdf_generator parameter.
            pf.db_set('pdf_generator','chrome')
            for doctype,command in [('PZ Sales Contract','frappe.utils.print_format.download_pdf'),
                    ({'PZ Sales Contract':['synthetic']},'frappe.utils.print_format.download_multi_pdf')]:
                with self.subTest(command=command):
                    frappe.local.form_dict=frappe._dict(doctype=doctype,cmd=command,format=pf.name)
                    with self.assertRaises(frappe.ValidationError): guard_renderer()
        finally:
            pf.db_set('pdf_generator',old_generator)
            frappe.local.form_dict=old_values

    def test_sales_order_taxes_do_not_change_new_contract_payment_basis(self):
        account=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Income'),'name')
        actual_account='PZ Synthetic Actual Charge - PZT'
        if not frappe.db.exists('Account',actual_account):
            parent=frappe.db.get_value('Account',dict(company=COMPANY,is_group=1,root_type='Income'),'name')
            frappe.get_doc(dict(doctype='Account',account_name='PZ Synthetic Actual Charge',company=COMPANY,
                parent_account=parent,account_currency='USD',is_group=0)).insert()
        d=contract(discount_amount=100,submit=True,submit_sales_order=False)
        self.assertEqual((d.grand_total,d.advance_required,d.balance_required),(900,270,630))
        order=frappe.get_doc('Sales Order',d.sales_order)
        order.delivery_date=add_days(today(),10)
        for item in order.items:
            item.delivery_date=order.delivery_date
        order.append('taxes',dict(charge_type='On Net Total',account_head=account,
            description='Synthetic 10%',rate=10))
        order.append('taxes',dict(charge_type='Actual',account_head=actual_account,
            description='Synthetic actual handling',tax_amount=10))
        order.save().submit()
        self.assertEqual(order.net_total,900)
        self.assertEqual(order.grand_total,1000, [
            (tax.charge_type, tax.rate, tax.tax_amount, tax.total) for tax in order.taxes
        ])
        self.assertEqual(frappe.db.get_value('PZ Sales Contract',d.name,'tax_total'),0)
        html=frappe.get_print('PZ Sales Contract',d.name)
        self.assertIn('Applicable taxes, if any, are recorded and calculated separately',html)
        self.assertNotIn('Identified taxes and charges',html)

    def test_new_contract_keeps_sales_order_draft_until_user_supplies_delivery_date(self):
        d=contract(discount_amount=100,submit=True,submit_sales_order=False)
        order=frappe.get_doc('Sales Order',d.sales_order)
        self.assertEqual(order.docstatus,0)
        self.assertFalse(order.delivery_date)
        self.assertFalse(order.skip_delivery_note)
        self.assertEqual((d.grand_total,d.tax_total,d.advance_required,d.balance_required),(900,0,270,630))
        status=payment_status(d)
        self.assertEqual(status.confirmed,0)
        self.assertTrue(status.payment_draft)
        with self.assertRaises(frappe.ValidationError):
            order.submit()

        order=frappe.get_doc('Sales Order',d.sales_order)
        order.delivery_date=add_days(today(),10)
        for item in order.items:
            item.delivery_date=order.delivery_date
        order.save().submit()
        self.assertEqual(order.docstatus,1)
        self.assertEqual(order.net_total,d.grand_total)

    def test_modified_contract_lines_cannot_be_manually_submitted_on_sales_order(self):
        d=contract(submit=True,submit_sales_order=False)
        order=frappe.get_doc('Sales Order',d.sales_order)
        order.delivery_date=add_days(today(),10)
        for item in order.items:
            item.delivery_date=order.delivery_date
        order.items[0].rate += 1
        order.save()
        with self.assertRaises(frappe.ValidationError):
            order.submit()

    def test_cancelling_contract_removes_its_linked_draft_sales_order(self):
        d=contract(submit=True,submit_sales_order=False)
        order_name=d.sales_order
        d.cancel()
        self.assertFalse(frappe.db.exists('Sales Order',order_name))
        self.assertEqual(frappe.db.get_value('PZ Sales Contract',d.name,'sales_order'),None)
        self.assertEqual(frappe.db.get_value('PZ Sales Contract',d.name,'cancelled_sales_order_reference'),order_name)

    def test_nominated_accounts_and_unagreed_cash(self):
        d=contract(submit=True,cash_receiving_account=None)
        receipt(d,300,cash=True)
        self.assertEqual(payment_status(d).confirmed,0)
        other=frappe.get_doc(dict(doctype='Account',account_name='PZ Synthetic Other Bank '+frappe.generate_hash(length=5),
            company=COMPANY,parent_account=frappe.db.get_value('Account','PZ Synthetic Bank - PZT','parent_account'),
            account_currency='USD',account_type='Bank',is_group=0)).insert()
        p=receipt(d,300,submit=False)
        p.paid_to=other.name
        p.save().submit()
        p.db_set('clearance_date',today())
        self.assertEqual(payment_status(d).confirmed,0)
        # Bank instructions are text, but naming a Cash ledger there does not
        # nominate it as the agreed cash account or qualify a cash receipt.
        text_bank = contract(submit=True, bank_receiving_account='PZ Synthetic Cash - PZT',
            cash_receiving_account=None)
        receipt(text_bank, 300, cash=True)
        self.assertEqual(payment_status(text_bank).confirmed, 0)
        invalid = contract(insert=False, cash_receiving_account='PZ Synthetic Bank - PZT')
        with self.assertRaises(frappe.ValidationError):
            invalid.insert()

    def test_pre_existing_customer_and_native_receipt_are_not_history_override(self):
        from pz_sales_contract.testing import new_customer
        customer,address,contact=new_customer()
        old_order=frappe.get_doc(dict(doctype='Sales Order',customer=customer,company=COMPANY,
            transaction_date=today(),delivery_date=today(),currency='USD',conversion_rate=1,
            selling_price_list='PZ Synthetic USD',order_type='Sales',customer_address=address.name,
            contact_person=contact.name,items=[dict(item_code='PZ Synthetic Bitumen',qty=10,rate=100,
            delivery_date=today())])).insert()
        old_order.submit()
        old_payment=receipt(frappe._dict(sales_order=old_order.name),300)
        reconcile(old_payment,self.bank_account)
        self.assertFalse(frappe.db.exists('PZ Contract Registry',{'customer':customer}))
        first=contract(customer=customer,submit=True)
        status=payment_status(first)
        self.assertTrue(status.first_contract)
        self.assertTrue(status.payment_draft)
        self.assertEqual(status.confirmed,0)

    def test_submitted_calendar_is_frozen_for_print_and_deadlines(self):
        d=contract()
        d.db_set('terms_version', None)
        d.db_set('terms_snapshot', None)
        d.db_set('contract_scope_version', None)
        d.reload()
        self.complete_legacy_schedule(d)
        d.delivery_date=today()
        d.timezone='Asia/Baghdad'
        d.business_days='Monday,Tuesday,Wednesday,Thursday,Friday'
        d.opens_at='09:00:00'
        d.closes_at='17:00:00'
        d.holiday_list='PZ Synthetic Calendar'
        d.collection_grace=48
        d.grace_unit='Calendar hours'
        d.approval_received='2026-10-01T09:00:00+03:00'
        d.approval_evidence='Synthetic written approval'
        d.save()
        d.submit()
        before=d.advance_deadline
        calendar=frappe.get_doc('Holiday List',d.holiday_list)
        calendar.append('holidays',dict(holiday_date='2026-10-02',description='Later master change'))
        calendar.save()
        d.approval_evidence='Synthetic evidence clarification'
        d.save()
        self.assertEqual(d.advance_deadline,before)
        html=frappe.get_print(d.doctype,d.name,print_format='Standard',no_letterhead=1)
        self.assertNotIn('Later master change',html)
        self.assertIn('Synthetic closure',html)

    def historical_order(self,qty=10,rate=100):
        from pz_sales_contract.testing import new_customer
        customer,address,contact=new_customer()
        order=frappe.get_doc(dict(doctype='Sales Order',customer=customer,company=COMPANY,
            transaction_date=today(),delivery_date=today(),currency='USD',conversion_rate=1,
            selling_price_list='PZ Synthetic USD',order_type='Sales',customer_address=address.name,
            contact_person=contact.name,items=[dict(item_code='PZ Synthetic Bitumen',qty=qty,rate=rate,
            delivery_date=today())])).insert()
        order.submit()
        return order

    def historical_designation(self,order):
        return frappe.get_doc(dict(doctype='PZ Customer History',customer=order.customer,company=order.company,
            sales_order=order.name,prior_contract_evidence='Synthetic prior signed contract and finance migration review',
            bank_receiving_account='PZ Synthetic Bank - PZT',cash_receiving_account='PZ Synthetic Cash - PZT')).insert()

    def test_current_and_history_advances_respect_zero_decimal_precision(self):
        fields=[frappe.get_meta(doctype).get_field('advance_required')
            for doctype in ['PZ Sales Contract','PZ Customer History']]
        previous=[field.precision for field in fields]
        try:
            # Native DocField precision supports "0". Configure only the isolated
            # cached metadata and restore it, without persisting a customization.
            for field in fields: field.precision='0'
            current=contract(submit=True,items=[dict(item_code='PZ Synthetic Bitumen',
                qty=1,uom='Nos',rate=101,grade_master=synthetic_bitumen_grade(),grade='PZ-SYNTHETIC-60-70',packaging='Synthetic drums',
                specification_reference='Synthetic zero-decimal precision QA')])
            self.assertEqual(current.precision('advance_required'),0)
            self.assertEqual(current.advance_required,30)
            self.assertEqual(get_status(current.name).currency_precision,0)
            from bs4 import BeautifulSoup
            printed = BeautifulSoup(frappe.get_print(current.doctype,current.name), 'html.parser')
            totals = {row.select('td')[0].get_text(strip=True): row.select('td')[1].get_text(strip=True)
                for row in printed.select('.totals tr')}
            self.assertEqual(totals['30% advance'], '30')
            receipt(current,29,cash=True)
            self.assertTrue(payment_status(current).payment_draft)
            receipt(current,1,cash=True)
            self.assertFalse(payment_status(current).payment_draft)
            order=self.historical_order(qty=1,rate=101)
            self.assertEqual(order.grand_total,101)
            history=self.historical_designation(order)
            self.assertEqual(history.precision('advance_required'),0)
            self.assertEqual(history.advance_required,30)
            receipt(frappe._dict(sales_order=order.name),30,cash=True)
            history.submit()
            self.assertEqual(history.docstatus,1)
        finally:
            for field,value in zip(fields,previous,strict=True): field.precision=value

    def test_refunded_history_cannot_establish_returning_status(self):
        order=self.historical_order()
        receipt(frappe._dict(sales_order=order.name),300,cash=True)
        outgoing=refund(frappe._dict(sales_order=order.name),300)
        self.assertEqual(frappe.db.get_value('Sales Order',order.name,'advance_paid'),0)
        history=self.historical_designation(order)
        with self.assertRaises(frappe.ValidationError): history.submit()
        outgoing.cancel()
        history.reload()
        history.submit()
        first=contract(customer=order.customer)
        self.assertFalse(payment_status(first).payment_draft)
        refund(frappe._dict(sales_order=order.name),300)
        self.assertFalse(payment_status(first).established_history)
        self.assertTrue(payment_status(first).payment_draft)
        self.assertFalse(payment_status(contract(customer=order.customer)).payment_draft)

    def test_finance_history_establishes_returning_and_cancellation_restores_family(self):
        order=self.historical_order()
        p=receipt(frappe._dict(sales_order=order.name),300)
        bt=reconcile(p,self.bank_account)
        frappe.set_user('pz-finance@example.invalid')
        history=self.historical_designation(order)
        history.submit()
        self.assertEqual(history.owner,'pz-finance@example.invalid')
        self.assertIn(p.name,history.validated_evidence)
        frappe.set_user('Administrator')
        first=contract(customer=order.customer,submit=True)
        status=payment_status(first)
        self.assertTrue(status.established_history)
        self.assertFalse(status.payment_draft)
        bt.cancel()
        self.assertTrue(payment_status(first).payment_draft)
        frappe.set_user('pz-finance@example.invalid')
        history.cancel()
        frappe.set_user('Administrator')
        self.assertTrue(payment_status(first).payment_draft)
        later=contract(customer=order.customer,submit=True)
        self.assertFalse(payment_status(later).payment_draft)

    def test_history_rejects_unpaid_draft_partial_and_cancelled_native_receipts(self):
        order=self.historical_order()
        history=self.historical_designation(order)
        with self.assertRaises(frappe.ValidationError):
            history.submit()
        history.reload()
        draft=receipt(frappe._dict(sales_order=order.name),300,cash=True,submit=False)
        with self.assertRaises(frappe.ValidationError):
            history.submit()
        history.reload()
        draft.delete()
        p=receipt(frappe._dict(sales_order=order.name),299,cash=True)
        with self.assertRaises(frappe.ValidationError):
            history.submit()
        history.reload()
        q=receipt(frappe._dict(sales_order=order.name),1,cash=True)
        q.cancel()
        with self.assertRaises(frappe.ValidationError):
            history.submit()
        history.reload()
        p.cancel()
        self.assertTrue(payment_status(contract(customer=order.customer)).payment_draft)

    def test_sales_user_cannot_designate_history_or_reclassify_current_order(self):
        order=self.historical_order()
        receipt(frappe._dict(sales_order=order.name),300,cash=True)
        frappe.set_user('pz-sales@example.invalid')
        self.assertFalse(frappe.has_permission('PZ Customer History','create'))
        self.assertFalse(frappe.has_permission('PZ Customer History','submit'))
        with self.assertRaises(frappe.PermissionError):
            self.historical_designation(order)
        frappe.set_user('Administrator')
        current=contract(submit=True)
        receipt(current,300,cash=True)
        with self.assertRaises(frappe.ValidationError):
            self.historical_designation(frappe.get_doc('Sales Order',current.sales_order))

    def test_active_history_requires_cancellation_before_replacement(self):
        order=self.historical_order()
        receipt(frappe._dict(sales_order=order.name),300,cash=True)
        first=self.historical_designation(order)
        first.submit()
        second=self.historical_designation(order)
        frappe.db.savepoint('history_replace')
        with self.assertRaises(frappe.ValidationError):
            second.submit()
        frappe.db.rollback(save_point='history_replace')
        second.reload()
        first.cancel()
        second.submit()
        registry=frappe.db.get_value('PZ Contract Registry',{'customer':order.customer},'established_history')
        self.assertEqual(registry,second.name)


    def test_direct_parties_save_print_and_submit_without_contact_address_links(self):
        from pz_sales_contract.parties import PARTY_REQUIRED_FIELDS
        doc = contract(customer_address=None, contact_person=None, seller_address=None,
            customer_name='Entered Buyer <legal>', customer_tax_id='Entered registration',
            contact_display='Entered Representative', buyer_position='Director',
            buyer_email_phone='00971 505 65 1305', seller_name='Edited Seller',
            seller_address_display='Edited Seller Address', seller_email='seller@example.invalid',
            seller_phone='0012345678')
        self.assertEqual(doc.party_entry_version, 'direct-v1')
        for field in ('customer_address', 'contact_person', 'seller_address'):
            self.assertIsNone(doc.get(field))
        for field in PARTY_REQUIRED_FIELDS:
            saved = doc.get(field)
            doc.set(field, '   ')
            with self.assertRaises(frappe.MandatoryError, msg=field):
                doc.save()
            doc.reload()
        doc.save()
        html = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
        from bs4 import BeautifulSoup
        printed = BeautifulSoup(html, 'html.parser')
        # Native Data-field sanitization may normalize input markup on save.
        # Compare the rendered text with the actual persisted snapshot.
        self.assertIn(doc.customer_name, printed.get_text())
        self.assertIsNone(printed.find('legal'))
        for value in ['Entered registration', 'Entered Representative', 'Director',
                '00971 505 65 1305', 'Edited Seller Address', 'seller@example.invalid', '0012345678']:
            self.assertIn(value, html)
        doc.submit()
        order = frappe.get_doc('Sales Order', doc.sales_order)
        self.assertEqual(order.customer, doc.customer)
        self.assertEqual(order.company, doc.company)
        self.assertEqual(order.docstatus, 0)
        order.delivery_date = today()
        for row in order.items:
            row.delivery_date = today()
        order.save().submit()

    def test_direct_party_snapshots_survive_master_changes_and_amendments(self):
        doc = contract(submit=True, submit_sales_order=False)
        recorded = {field: doc.get(field) for field in ('customer_name', 'customer_tax_id',
            'address_display', 'contact_display', 'seller_address_display')}
        frappe.db.set_value('Customer', doc.customer, 'customer_name', 'Changed ERP master name')
        doc.reload()
        self.assertEqual({field: doc.get(field) for field in recorded}, recorded)
        doc.cancel()
        amendment = frappe.copy_doc(doc)
        amendment.docstatus = 0
        amendment.amended_from = doc.name
        amendment.insert()
        self.assertEqual(amendment.party_entry_version, 'direct-v1')
        self.assertEqual({field: amendment.get(field) for field in recorded}, recorded)

    def test_historical_party_text_is_preserved_on_save_until_explicitly_edited(self):
        doc = contract()
        frappe.db.set_value(doc.doctype, doc.name, dict(party_entry_version=None,
            seller_name=None, seller_email=None, seller_phone=None, buyer_phone=None, buyer_email_phone=None))
        doc.reload()
        recorded = {field: doc.get(field) for field in ('customer_name', 'customer_tax_id',
            'address_display', 'contact_display', 'seller_address_display')}
        before = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
        frappe.db.set_value('Customer', doc.customer, 'customer_name', 'Changed ERP buyer')
        doc.save()
        self.assertEqual({field: doc.get(field) for field in recorded}, recorded)
        self.assertEqual(frappe.get_print(doc.doctype, doc.name, print_format='Standard'), before)
        doc.customer_name = 'Explicit historical correction'
        doc.save()
        self.assertEqual(doc.reload().customer_name, 'Explicit historical correction')

        for field, value in [('seller_email', 'edited-historical@example.invalid'),
                ('seller_phone', '001122334455')]:
            doc.set(field, value)
            doc.save()
            html = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
            self.assertIn(value, html)
            self.assertIn('info@petrol-zone.com' if field == 'seller_phone' else '00964 770 000 3737', html)
            doc.set(field, None)
            doc.save()


    def test_historical_party_links_cannot_be_reassigned_through_payloads(self):
        doc = contract()
        customer_address = frappe.db.get_value('Dynamic Link',
            dict(parenttype='Address', link_doctype='Customer', link_name=doc.customer), 'parent')
        contact_person = frappe.db.get_value('Dynamic Link',
            dict(parenttype='Contact', link_doctype='Customer', link_name=doc.customer), 'parent')
        frappe.db.set_value(doc.doctype, doc.name, dict(party_entry_version=None,
            customer_address=customer_address, contact_person=contact_person,
            seller_address='PZ Synthetic Seller-Billing'))
        doc.reload()
        _, unrelated_address, unrelated_contact = new_customer()
        for field, value in [('customer_address', unrelated_address.name),
                ('contact_person', unrelated_contact.name), ('seller_address', unrelated_address.name)]:
            doc.set(field, value)
            with self.assertRaisesRegex(frappe.ValidationError, 'Historical .* cannot be changed'):
                doc.save()
            doc.reload()
        doc.contact_display = 'Explicit historical representative correction'
        doc.save()
        self.assertEqual(doc.contact_person, contact_person)


    def test_optional_buyer_details_save_and_print_cleanly_without_weakening_primary_phone(self):
        from bs4 import BeautifulSoup
        doc = contract(customer_tax_id=None, buyer_email_phone='')
        doc.save()
        html = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
        buyer = BeautifulSoup(html, 'html.parser').select_one('table.details tr td:nth-of-type(2)').get_text()
        self.assertNotIn('Registration / tax / ID:', buyer)
        self.assertNotIn('Email / phone:', buyer)
        self.assertNotIn('Not recorded', buyer)
        self.assertNotIn('None', buyer)
        self.assertIn(doc.buyer_phone, buyer)
        doc.buyer_phone = ''
        with self.assertRaisesRegex(frappe.MandatoryError, 'Buyer phone'):
            doc.save()
        doc.reload()
        doc.submit()
        self.assertEqual(frappe.db.get_value('Sales Order', doc.sales_order, 'docstatus'), 0)


    def test_optional_payment_fields_remain_blank_despite_company_defaults(self):
        from pz_sales_contract.parties import PAYMENT_INSTRUCTION_FIELDS
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults().insert()
        doc = contract(**dict.fromkeys(PAYMENT_INSTRUCTION_FIELDS))
        doc.save()
        for field in PAYMENT_INSTRUCTION_FIELDS:
            self.assertFalse(doc.get(field), field)
        html = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
        self.assertNotIn('<h2>Payment Instructions</h2>', html)
        self.assertNotIn('Cash not agreed', html)
        self.assertNotIn('>None<', html)
        doc.submit()
        self.assertEqual(frappe.db.get_value('Sales Order', doc.sales_order, 'docstatus'), 0)
        self.assertTrue(payment_status(doc).payment_draft)
        self.assertEqual(payment_status(doc).confirmed, 0)

    def test_free_text_bank_is_saved_printed_but_unknown_account_never_confirms_receipts(self):
        field = frappe.get_meta('PZ Sales Contract').get_field('bank_receiving_account')
        self.assertEqual(field.fieldtype, 'Data')
        self.assertFalse(field.options)
        doc = contract(bank_receiving_account='Synthetic free-text bank instructions',
            cash_receiving_account=None, submit=True)
        self.assertEqual(doc.reload().bank_receiving_account, 'Synthetic free-text bank instructions')
        self.assertIn('Synthetic free-text bank instructions', frappe.get_print(doc.doctype, doc.name))
        paid = receipt(doc, 300)
        reconcile(paid, self.bank_account)
        self.assertEqual(payment_status(doc).confirmed, 0)
        self.assertTrue(payment_status(doc).payment_draft)

    def test_new_draft_discount_omitted_null_or_zero_uses_zero_without_creating_order(self):
        for mode in ('omitted', None, 0):
            with self.subTest(discount=mode):
                payload = contract(insert=False).as_dict()
                if mode == 'omitted':
                    payload.pop('discount_amount', None)
                else:
                    payload['discount_amount'] = mode
                payload['items'][0].update(qty=333, rate=350)
                before_orders = frappe.db.count('Sales Order')
                doc = frappe.get_doc(payload).insert()
                doc.save()
                self.assertEqual(doc.discount_amount, 0)
                self.assertEqual(doc.grand_total, 116550)
                self.assertEqual(doc.docstatus, 0)
                self.assertFalse(doc.sales_order)
                self.assertEqual(frappe.db.count('Sales Order'), before_orders)
        for discount in (-1, 116551, 'not-a-number', 'NaN'):
            with self.subTest(discount=discount):
                doc = contract(insert=False, discount_amount=discount)
                doc.items[0].qty = 333
                doc.items[0].rate = 350
                with self.assertRaises(frappe.ValidationError):
                    doc.insert()

    def test_manual_print_draft_is_independent_of_customer_and_payment_in_all_print_routes(self):
        from frappe.www.printview import get_html_and_style
        from frappe.utils.print_format import download_pdf
        native_hooks = frappe.get_hooks

        def delegating_hooks(hook=None, *args, **kwargs):
            if hook == 'pdf_body_html':
                return ['frappe.utils.pdf.pdf_body_html']
            return native_hooks(hook, *args, **kwargs)

        first_saved = contract(print_as_draft=0)
        checked_unpaid = contract(print_as_draft=1)
        unchecked_unpaid = contract(submit=True, submit_sales_order=False, print_as_draft=0)
        checked_paid = contract(submit=True, print_as_draft=1)
        receipt(checked_paid, 300, cash=True)
        unchecked_paid = contract(submit=True, print_as_draft=0)
        receipt(unchecked_paid, 300, cash=True)
        existing_customer_unpaid = contract(customer=first_saved.customer,
            submit=True, submit_sales_order=False, print_as_draft=0)
        cancelled_checked = contract(submit=True, print_as_draft=1)
        cancelled_checked.cancel()
        cases = [
            (first_saved, False, False),
            (checked_unpaid, True, False),
            (unchecked_unpaid, False, False),
            (checked_paid, True, False),
            (unchecked_paid, False, False),
            (existing_customer_unpaid, False, False),
            (cancelled_checked, False, True),
        ]
        with patch('frappe.get_hooks', side_effect=delegating_hooks):
            for doc, marked, cancelled in cases:
                with self.subTest(contract=doc.name):
                    forged = doc.as_dict()
                    forged.update(customer_name='FORGED BUYER', print_as_draft=not marked,
                        docstatus=0 if cancelled else doc.docstatus)
                    preview = get_html_and_style(doc=json.dumps(forged, default=str),
                        print_format='Petrol Zone Sales Contract')['html']
                    with patch('frappe.utils.pdf.get_pdf', return_value=b'%PDF-synthetic-boundary') as binary:
                        download_pdf(doc.doctype, doc.name, format='Petrol Zone Sales Contract',
                            pdf_generator='wkhtmltopdf')
                    binary.assert_called_once()
                    self.assertEqual(frappe.local.response.filecontent, b'%PDF-synthetic-boundary')
                    pdf_html = binary.call_args.args[0]
                    for html in (preview, pdf_html):
                        self.assertNotIn('FORGED BUYER', html)
                        self.assertEqual('>DRAFT<' in html, marked and not cancelled)
                        self.assertEqual('CANCELLED CONTRACT' in html, cancelled)
                        self.assertNotIn('FIRST ADVANCE', html)
                        self.assertNotIn('advance pending', html.lower())
                        self.assertNotIn('Confirmed receipt allocation', html)
                        self.assertNotIn('This printout records ERP receipt', html)
                        self.assertIn('30% advance', html)
                        self.assertIn('70% balance', html)

    def test_v3_terms_and_print_stamp_match_html_custom_print_and_native_pdf_input(self):
        import base64
        from bs4 import BeautifulSoup
        from frappe.www.printview import get_html_and_style
        from frappe.utils.print_format import download_pdf

        doc = contract(print_as_draft=1)
        expected_clauses = json.loads((Path(__file__).resolve().parents[3] / 'terms.json').read_text())
        expected_stamp = 'data:image/png;base64,' + base64.b64encode(
            b'synthetic site-private print fixture'
        ).decode()
        with patch('pz_sales_contract.printing._load_print_stamp', return_value=expected_stamp):
            html_view = get_html_and_style(doc=json.dumps(doc.as_dict(), default=str),
                print_format='Petrol Zone Sales Contract')['html']
            custom_print = frappe.get_print(doc.doctype, doc.name, print_format='Petrol Zone Sales Contract')
            with patch('frappe.utils.pdf.get_pdf', return_value=b'%PDF-synthetic-boundary') as binary:
                download_pdf(doc.doctype, doc.name, format='Petrol Zone Sales Contract',
                    pdf_generator='wkhtmltopdf')
        native_pdf_html = binary.call_args.args[0]

        for rendered in (html_view, custom_print, native_pdf_html):
            soup = BeautifulSoup(rendered, 'html.parser')
            printed_text = soup.get_text()
            for clause in expected_clauses:
                self.assertIn(clause, printed_text)
            self.assertEqual(len(soup.select('section.terms')), 3)
            self.assertEqual(len(soup.select('section.terms p')), 15)
            self.assertEqual(soup.select_one('img.seller-stamp').get('src'), expected_stamp)
            self.assertIn('>DRAFT<', rendered)
            self.assertIn('id="header-html"', rendered)
            self.assertIn('id="footer-html"', rendered)
            self.assertIn('page-break-inside:avoid', rendered)

    def test_print_as_draft_can_be_changed_after_submit_and_is_not_changed_by_receipts(self):
        doc = contract(submit=True, print_as_draft=0)
        self.assertEqual(doc.reload().print_as_draft, 0)
        doc.print_as_draft = 1
        doc.save()
        self.assertEqual(doc.reload().print_as_draft, 1)
        receipt(doc, 300, cash=True)
        self.assertEqual(doc.reload().print_as_draft, 1)
        html = frappe.get_print(doc.doctype, doc.name, print_format='Standard')
        self.assertIn('>DRAFT<', html)
        doc.print_as_draft = 0
        doc.save()
        self.assertEqual(doc.reload().print_as_draft, 0)
        self.assertNotIn('>DRAFT<', frappe.get_print(doc.doctype, doc.name, print_format='Standard'))

    def test_print_as_draft_defaults_unchecked_and_legacy_records_do_not_infer_payment_state(self):
        field = frappe.get_meta('PZ Sales Contract').get_field('print_as_draft')
        self.assertEqual((field.fieldtype, int(field.default or 0)), ('Check', 0))
        legacy = contract()
        legacy.db_set('terms_version', None)
        legacy.db_set('contract_scope_version', None)
        legacy.db_set('terms_snapshot', None)
        self.assertEqual(legacy.reload().print_as_draft, 0)
        html = frappe.get_print(legacy.doctype, legacy.name, print_format='Standard')
        self.assertNotIn('>DRAFT<', html)
        legacy.db_set('print_as_draft', 1)
        self.assertIn('>DRAFT<', frappe.get_print(legacy.doctype, legacy.name, print_format='Standard'))

    def test_contract_template_reloads_print_choice_and_enforces_permissions_and_saved_status(self):
        from pz_sales_contract.printing import get_contract_print_context
        doc = contract(submit=True, print_as_draft=1)
        # The installed include ignores a caller's forged print choice and status.
        template = frappe.get_jenv().from_string(
            '{% include "pz_sales_contract/templates/contract.html" %}')
        html = template.render(doc=doc.as_dict(), print_as_draft=0, payment_draft=False, confirmed=1000)
        self.assertIn('>DRAFT<', html)
        self.assertNotIn('Confirmed receipt allocation', html)
        with self.assertRaises(frappe.DoesNotExistError):
            get_contract_print_context(frappe._dict(doctype=doc.doctype, name='UNSAVED-SYNTHETIC'))
        try:
            frappe.set_user('Guest')
            with self.assertRaises(frappe.PermissionError):
                get_contract_print_context(doc)
        finally:
            frappe.set_user('Administrator')
        doc.cancel()
        previous = frappe.db.get_single_value('Print Settings', 'allow_print_for_cancelled')
        try:
            frappe.db.set_single_value('Print Settings', 'allow_print_for_cancelled', 0)
            forged = doc.as_dict()
            forged.docstatus = 1
            with self.assertRaises(frappe.PermissionError):
                get_contract_print_context(forged)
        finally:
            frappe.db.set_single_value('Print Settings', 'allow_print_for_cancelled', previous)
