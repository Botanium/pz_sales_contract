import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_timedelta, today

from pz_sales_contract.payments import payment_status, get_status
from pz_sales_contract.contract_terms import clauses_for_contract, snapshot_for_new_contract
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
    grade_snapshot,
)

# Every needed record is created explicitly below. Do not recursively import
# optional ERPNext fixtures (Payment Gateway belongs to another app in v16).
IGNORE_TEST_RECORD_DEPENDENCIES = ['Customer','Company','Address','Contact','Currency','Price List',
    'Incoterm','Bitumen Grade','Holiday List','Sales Order','PZ Sales Contract','Item','UOM','Account','Cost Center','Project',
    'Location','Branch','Department']


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
        self.assertIn('Nine Hundred And Ninety',d.in_words)
        self.assertIn('Synthetic customer',d.address_display)
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
        d = contract()
        self.assertEqual(d.terms_snapshot, active_snapshot)
        self.assertEqual(clauses_for_contract(d), json.loads(active_snapshot))

        source_with_snapshot = SimpleNamespace(get=lambda key: active_snapshot if key == 'terms_snapshot' else None)
        self.assertEqual(snapshot_for_new_contract(source_with_snapshot), active_snapshot)

        legacy_source = SimpleNamespace(get=lambda key: None)
        self.assertEqual(snapshot_for_new_contract(legacy_source), frozen_snapshot)
        self.assertEqual(clauses_for_contract(legacy_source), json.loads(frozen_snapshot))

        d.terms_snapshot = '[]'
        with self.assertRaises(frappe.ValidationError):
            d.save()

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

        actual_defaults = frappe.get_doc(dict(doctype='PZ Sales Contract', company=COMPANY))
        native_defaults = frappe.get_doc(dict(doctype='PZ Sales Contract', company=COMPANY))
        Document._set_defaults(native_defaults)
        actual_defaults._set_defaults()
        for fieldname in COMPANY_DEFAULT_FIELDS:
            self.assertEqual(actual_defaults.get(fieldname), native_defaults.get(fieldname), fieldname)

        doc = contract()
        self.assertEqual(doc.currency, 'USD')
        self.assertEqual(doc.seller_signatory, 'Synthetic Seller')
        self.assertEqual(doc.bank_receiving_account, 'PZ Synthetic Bank - PZT')
        self.assertEqual(doc.governing_law, 'Synthetic placeholder; not legal advice or real agreement')

    def test_hidden_schedule_defaults_are_not_copied_to_new_contracts(self):
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults().insert()
        doc = contract(insert=False, **{fieldname: None for fieldname in HISTORICAL_CONTRACT_FIELDS})
        doc.insert()
        for fieldname in HISTORICAL_CONTRACT_FIELDS:
            self.assertIsNone(doc.get(fieldname), fieldname)

    def test_company_defaults_fill_blanks_preserve_overrides_and_snapshot(self):
        self.clear_synthetic_company_defaults()
        for price_list_name, currency in [('PZ Synthetic INR', 'INR'), ('PZ Synthetic EUR', 'EUR')]:
            if not frappe.db.exists('Price List', price_list_name):
                frappe.get_doc(dict(doctype='Price List', price_list_name=price_list_name,
                    currency=currency, selling=1, enabled=1)).insert()
        inr_bank = self.synthetic_company_account('PZ Synthetic INR Bank', 'Bank', 'INR')
        inr_cash = self.synthetic_company_account('PZ Synthetic INR Cash', 'Cash', 'INR')
        eur_bank = self.synthetic_company_account('PZ Synthetic EUR Bank', 'Bank', 'EUR')
        eur_list = 'PZ Synthetic EUR'
        inr_list = 'PZ Synthetic INR'
        settings = self.synthetic_company_defaults(
            currency='INR', conversion_rate=130, selling_price_list=inr_list,
            bank_receiving_account=inr_bank, cash_receiving_account=inr_cash,
            account_iban='INR / SYNTHETIC-NOT-AN-ACCOUNT',
        ).insert()
        customer, _, _ = new_customer()
        blank_fields = {fieldname: None for fieldname in COMPANY_DEFAULT_FIELDS}
        overrides = {
            'seller_signatory': 'Synthetic one-off seller override',
            'delivery_arrangement': 'Synthetic deal-specific delivery override',
            'bank_receiving_account': self.synthetic_alternate_bank_account('INR'),
            'beneficiary': 'SYNTHETIC DEAL-SPECIFIC BENEFICIARY',
            'bank_branch': 'SYNTHETIC DEAL-SPECIFIC BANK',
            'account_iban': 'INR / SYNTHETIC-DEAL-SPECIFIC-ACCOUNT',
            'swift_reference': 'SYNTHETIC DEAL-SPECIFIC REFERENCE',
        }
        doc = contract(customer=customer, insert=False, **(blank_fields | overrides))
        self.assertTrue(frappe.db.exists('PZ Contract Defaults', COMPANY))
        self.assertEqual(frappe.db.get_value('PZ Contract Defaults', COMPANY, 'currency'), settings.currency)
        doc.insert()
        self.assertEqual(doc.currency, settings.currency)
        self.assertEqual(doc.conversion_rate, settings.conversion_rate)
        self.assertEqual(doc.selling_price_list, settings.selling_price_list)
        for fieldname in COMPANY_DEFAULT_FIELDS:
            expected = overrides.get(fieldname, settings.get(fieldname))
            if expected is not None:
                actual = doc.get(fieldname)
                if fieldname in ('opens_at', 'closes_at'):
                    actual, expected = get_timedelta(actual), get_timedelta(expected)
                self.assertEqual(actual, expected, fieldname)

        explicit_zero_grace = contract(customer=customer, **(blank_fields | {'collection_grace': 0}))
        self.assertEqual(explicit_zero_grace.collection_grace, 0)

        # Explicit currency-incompatible price lists/accounts are never
        # overwritten or accompanied by a partially copied profile bundle.
        explicit_bad_list = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'INR', 'conversion_rate': 130, 'selling_price_list': 'PZ Synthetic USD',
        }))
        frappe.db.savepoint('explicit_bad_list_company_defaults')
        with self.assertRaises(frappe.ValidationError):
            explicit_bad_list.insert()
        frappe.db.rollback(save_point='explicit_bad_list_company_defaults')
        self.assertEqual(explicit_bad_list.selling_price_list, 'PZ Synthetic USD')
        self.assertEqual(explicit_bad_list.conversion_rate, 130)
        self.assertIsNone(explicit_bad_list.bank_receiving_account)

        explicit_bad_account = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'INR', 'conversion_rate': 130, 'selling_price_list': inr_list,
            'bank_receiving_account': 'PZ Synthetic Bank - PZT',
        }))
        frappe.db.savepoint('explicit_bad_account_company_defaults')
        with self.assertRaises(frappe.ValidationError):
            explicit_bad_account.insert()
        frappe.db.rollback(save_point='explicit_bad_account_company_defaults')
        self.assertEqual(explicit_bad_account.bank_receiving_account, 'PZ Synthetic Bank - PZT')
        self.assertIsNone(explicit_bad_account.cash_receiving_account)

        # A different native currency must not receive a partial INR bundle.
        settings.currency = 'USD'
        settings.conversion_rate = 1
        settings.selling_price_list = 'PZ Synthetic USD'
        settings.bank_receiving_account = 'PZ Synthetic Bank - PZT'
        settings.cash_receiving_account = 'PZ Synthetic Cash - PZT'
        settings.account_iban = 'USD / SYNTHETIC-NOT-AN-ACCOUNT'
        settings.save()
        incompatible_native = contract(customer=customer, insert=False, **blank_fields)
        frappe.db.savepoint('incompatible_native_currency_defaults')
        with self.assertRaises(frappe.ValidationError):
            incompatible_native.insert()
        frappe.db.rollback(save_point='incompatible_native_currency_defaults')
        self.assertEqual(incompatible_native.currency, 'INR')
        self.assertEqual(incompatible_native.seller_signatory, settings.seller_signatory)
        self.assertIsNone(incompatible_native.conversion_rate)
        self.assertIsNone(incompatible_native.selling_price_list)
        self.assertIsNone(incompatible_native.bank_receiving_account)
        self.assertIsNone(incompatible_native.cash_receiving_account)
        self.assertIsNone(incompatible_native.account_iban)

        # An intentional USD deal with a coherent explicit bundle stays intact.
        explicit_usd = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'USD', 'conversion_rate': 1, 'selling_price_list': 'PZ Synthetic USD',
            'bank_receiving_account': 'PZ Synthetic Bank - PZT',
        }))
        explicit_usd.insert()
        self.assertEqual((explicit_usd.currency, explicit_usd.selling_price_list,
            explicit_usd.bank_receiving_account), ('USD', 'PZ Synthetic USD', 'PZ Synthetic Bank - PZT'))

        # A different-currency deal must still supply all mandatory payment
        # instructions. The USD profile must not complete an EUR bundle.
        incomplete_eur = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'EUR', 'conversion_rate': 1.2, 'selling_price_list': eur_list,
        }))
        frappe.db.savepoint('incomplete_eur_company_defaults')
        with self.assertRaises(frappe.MandatoryError):
            incomplete_eur.insert()
        frappe.db.rollback(save_point='incomplete_eur_company_defaults')
        self.assertIsNone(incomplete_eur.bank_receiving_account)
        self.assertIsNone(incomplete_eur.account_iban)

        # A complete, deliberate EUR deal keeps its own receiving instructions.
        eur_instructions = {
            'bank_receiving_account': eur_bank, 'cash_receiving_account': None,
            'beneficiary': 'SYNTHETIC EUR BENEFICIARY',
            'bank_branch': 'SYNTHETIC EUR BRANCH',
            'account_iban': 'EUR / SYNTHETIC-NOT-AN-ACCOUNT',
            'swift_reference': 'SYNTHETIC EUR REFERENCE',
        }
        explicit_eur = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'EUR', 'conversion_rate': 1.2, 'selling_price_list': eur_list,
        } | eur_instructions))
        explicit_eur.insert()
        self.assertEqual((explicit_eur.currency, explicit_eur.selling_price_list), ('EUR', eur_list))
        for fieldname, expected in eur_instructions.items():
            self.assertEqual(explicit_eur.get(fieldname), expected, fieldname)
        mismatched_eur = contract(customer=customer, insert=False, **(blank_fields | {
            'currency': 'EUR', 'conversion_rate': 1.2, 'selling_price_list': 'PZ Synthetic USD',
            'bank_receiving_account': None, 'cash_receiving_account': None,
        }))
        frappe.db.savepoint('mismatched_eur_currency_defaults')
        with self.assertRaises(frappe.ValidationError):
            mismatched_eur.insert()
        frappe.db.rollback(save_point='mismatched_eur_currency_defaults')
        self.assertEqual(mismatched_eur.currency, 'EUR')
        self.assertEqual(mismatched_eur.selling_price_list, 'PZ Synthetic USD')

        # Restore an aligned setup for the later snapshot-change assertions.
        settings.currency = 'INR'
        settings.conversion_rate = 130
        settings.selling_price_list = inr_list
        settings.bank_receiving_account = inr_bank
        settings.cash_receiving_account = inr_cash
        settings.account_iban = 'INR / SYNTHETIC-NOT-AN-ACCOUNT'
        settings.save()

        saved_law = doc.governing_law
        settings.governing_law = 'Synthetic changed setting — not a contract amendment'
        settings.save()
        doc.reload().save()
        self.assertEqual(doc.governing_law, saved_law)

        self.assertEqual(frappe.db.get_value('PZ Contract Defaults', COMPANY, 'currency'), settings.currency)
        self.assertEqual(frappe.db.get_value('PZ Contract Defaults', COMPANY, 'selling_price_list'), settings.selling_price_list)
        later = contract(**({fieldname: None for fieldname in COMPANY_DEFAULT_FIELDS}))
        self.assertEqual(later.currency, settings.currency)
        self.assertEqual(later.selling_price_list, settings.selling_price_list)
        self.assertEqual(later.governing_law, 'Synthetic placeholder; not legal advice or real agreement')

        # Legacy legal profile values are retained in settings, but are no
        # longer copied invisibly into new contracts.
        from frappe.model.document import Document

        saved_profile = {fieldname: settings.get(fieldname) for fieldname in COMPANY_DEFAULT_FIELDS}
        for fieldname in (
            'currency', 'conversion_rate', 'selling_price_list',
            'bank_receiving_account', 'cash_receiving_account',
            'beneficiary', 'bank_branch', 'account_iban', 'swift_reference',
        ):
            settings.set(fieldname, None)
        settings.save()
        initial = dict(doctype='PZ Sales Contract', company=COMPANY)
        native_defaults = frappe.get_doc(initial)
        Document._set_defaults(native_defaults)
        legal_only = frappe.get_doc(initial)
        Document._set_defaults(legal_only)
        dependent_before = {
            fieldname: native_defaults.get(fieldname)
            for fieldname in (
                'currency', 'conversion_rate', 'selling_price_list',
                'bank_receiving_account', 'cash_receiving_account',
                'beneficiary', 'bank_branch', 'account_iban', 'swift_reference',
            )
        }
        legal_fields = (
            'delivery_arrangement', 'transport_responsibility', 'insurance_responsibility',
            'measurement_basis', 'timezone', 'business_days', 'opens_at', 'closes_at',
            'holiday_list', 'notice_channel', 'collection_grace', 'grace_unit',
            'collection_arrangement', 'delay_charges', 'penalty_basis_cap', 'cure_period',
            'latent_claim_period', 'force_majeure_threshold', 'governing_law', 'courts',
        )
        legal_before = {fieldname: legal_only.get(fieldname) for fieldname in legal_fields}
        legal_only._apply_company_defaults()
        for fieldname, value in dependent_before.items():
            self.assertEqual(legal_only.get(fieldname), value, fieldname)
        self.assertEqual(legal_only.seller_signatory, saved_profile['seller_signatory'])
        for fieldname, value in legal_before.items():
            self.assertEqual(legal_only.get(fieldname), value, fieldname)
        for fieldname, value in saved_profile.items():
            settings.set(fieldname, value)
        settings.save()

    def test_alternate_bank_requires_its_own_payment_instructions(self):
        self.clear_synthetic_company_defaults()
        self.synthetic_company_defaults().insert()
        alternate_bank = self.synthetic_alternate_bank_account()
        blank_instructions = dict.fromkeys(
            ('beneficiary', 'bank_branch', 'account_iban', 'swift_reference')
        )
        doc = contract(insert=False, bank_receiving_account=alternate_bank, **blank_instructions)
        frappe.db.savepoint('alternate_bank_instructions')
        with self.assertRaises(frappe.MandatoryError):
            doc.insert()
        frappe.db.rollback(save_point='alternate_bank_instructions')
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
        with self.assertRaises(frappe.ValidationError):
            contract(customer=customer, seller_address=None)
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
                    for key,value in [('Subtotal',total),('Total · USD',total),('30% advance',required),('70% balance',balance)]:
                        self.assertEqual(totals[key],f'{value:.{digits}f}')
                    self.assertIn(f'30% advance: {required:.{digits}f}',soup.get_text())
                    self.assertIn(f'Confirmed receipt allocation: {partial:.{digits}f}',soup.get_text())
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
        d=contract(submit=True, seller_signatory=None, cash_receiving_account=None)
        self.assertEqual(d.seller_signatory, 'Synthetic approved signer at creation')
        self.assertIsNone(d.cash_receiving_account)
        settings.seller_signatory = 'Synthetic later default; never rewrite an agreed contract'
        settings.cash_receiving_account = 'PZ Synthetic Cash - PZT'
        settings.save()
        family=d.first_family
        d.cancel()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'docstatus'),2)
        amendment=frappe.copy_doc(d)
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
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'docstatus'),1)

    def test_print_standard_forged_payload_and_cancelled(self):
        d=contract(submit=True)
        html=frappe.get_print('PZ Sales Contract',d.name,print_format='Standard')
        self.assertIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',html)
        clauses = json.loads((Path(__file__).resolve().parents[3] / 'terms.json').read_text())
        self.assertEqual(len(clauses), 15)
        for number, clause in enumerate(clauses, start=1):
            heading = clause.split('. ', 1)[1].split('. ', 1)[0]
            self.assertIn(f'{number}. {heading}.', html)
        self.assertIn('Appendix A',html)
        self.assertIn('Commercial Schedule',html)
        from frappe.www.printview import get_html_and_style
        forged=d.as_dict()
        forged['customer_name']='FORGED BUYER'
        forged['first_family']='FORGED FAMILY'
        output=get_html_and_style(doc=json.dumps(forged,default=str),print_format='Standard')['html']
        self.assertNotIn('FORGED BUYER',output)
        self.assertIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',output)
        paid=receipt(d,300,cash=True)
        self.assertNotIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',frappe.get_print('PZ Sales Contract',d.name))
        paid.cancel()
        d.cancel()
        self.assertIn('CANCELLED CONTRACT',frappe.get_print('PZ Sales Contract',d.name))

    def test_schedule_deadlines_not_clock_days(self):
        year=frappe.utils.getdate(today()).year
        d=contract(approval_received=f'{year}-10-05T16:00:00+03:00',approval_evidence='Synthetic written approval and acceptance')
        self.assertEqual(d.advance_deadline,f'{year}-10-08T16:00:00+03:00')
        with self.assertRaises(frappe.ValidationError):
            contract(approval_received=f'{year}-10-05T16:00:00')

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
        d=contract(discount_amount=100,submit=True,submit_sales_order=False)
        self.assertEqual((d.grand_total,d.advance_required,d.balance_required),(900,270,630))
        order=frappe.get_doc('Sales Order',d.sales_order)
        order.delivery_date=add_days(today(),10)
        for item in order.items:
            item.delivery_date=order.delivery_date
        order.append('taxes',dict(charge_type='On Net Total',account_head=account,
            description='Synthetic 10%',rate=10))
        order.append('taxes',dict(charge_type='Actual',account_head=account,
            description='Synthetic actual handling',tax_amount=10))
        order.save().submit()
        self.assertEqual(order.net_total,900)
        self.assertEqual(order.grand_total,1000)
        self.assertEqual(frappe.db.get_value('PZ Sales Contract',d.name,'tax_total'),0)
        html=frappe.get_print('PZ Sales Contract',d.name)
        self.assertIn('not included in this contract total',html)
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
        invalid=frappe.copy_doc(d)
        invalid.docstatus=0
        invalid.bank_receiving_account='PZ Synthetic Cash - PZT'
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
        d=contract(submit=True,approval_received='2026-10-01T09:00:00+03:00',approval_evidence='Synthetic written approval')
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
            self.assertIn('30% advance: 30',frappe.get_print(current.doctype,current.name))
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
