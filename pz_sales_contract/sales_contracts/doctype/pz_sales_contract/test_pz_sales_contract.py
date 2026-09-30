import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from pz_sales_contract.payments import payment_status, get_status
from pz_sales_contract.testing import setup_fixtures, contract, receipt, reconcile, COMPANY

# Every needed record is created explicitly below. Do not recursively import
# optional ERPNext fixtures (Payment Gateway belongs to another app in v16).
IGNORE_TEST_RECORD_DEPENDENCIES = ['Customer','Company','Address','Contact','Currency','Price List',
    'Incoterm','Holiday List','Sales Order','PZ Sales Contract','Item','UOM','Account','Cost Center','Project']


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

    def test_native_arithmetic_and_master_links(self):
        tax_account=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Income'),'name')
        d=contract(discount_amount=100,taxes=[dict(charge_type='On Net Total',account_head=tax_account,description='Synthetic 10%',rate=10)])
        self.assertEqual((d.subtotal,d.tax_total,d.grand_total,d.advance_required),(1000,90,990,297))
        d.submit()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'grand_total'),990)
        self.assertEqual(d.items[0].item_name,'Synthetic Bitumen')
        self.assertIn('Synthetic customer',d.address_display)

    def test_first_and_returning_contracts_and_no_toggle(self):
        first=contract(submit=True)
        self.assertTrue(payment_status(first).payment_draft)
        second=contract(customer=first.customer,submit=True)
        self.assertFalse(payment_status(second).payment_draft)
        first.first_family='forged'
        with self.assertRaises(frappe.ValidationError):
            first.save()

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
        one.cancel()
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
        d=contract(submit=True)
        family=d.first_family
        d.cancel()
        amendment=frappe.copy_doc(d)
        amendment.amended_from=d.name
        amendment.sales_order=None
        amendment.first_family=None
        amendment.insert()
        self.assertEqual(amendment.first_family,family)
        self.assertTrue(payment_status(amendment).payment_draft)
        amendment.submit()
        self.assertNotEqual(amendment.sales_order,d.sales_order)
        self.assertFalse(payment_status(contract(customer=d.customer)).payment_draft)
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc('PZ Sales Contract',d.name,ignore_permissions=True)

    def test_permissions_sales_user_cannot_submit_pay_or_modify_registry(self):
        d=contract()
        frappe.set_user('pz-sales@example.invalid')
        self.assertTrue(frappe.has_permission('PZ Sales Contract','create'))
        self.assertFalse(frappe.has_permission('PZ Sales Contract','submit'))
        self.assertFalse(frappe.has_permission('Payment Entry','submit'))
        self.assertFalse(frappe.has_permission('Bank Transaction','write'))
        self.assertFalse(frappe.has_permission('PZ Contract Registry','write'))
        with self.assertRaises(frappe.PermissionError):
            d.submit()
        self.assertTrue(get_status(d.name).payment_draft)
        frappe.set_user('pz-manager@example.invalid')
        self.assertTrue(frappe.has_permission('PZ Sales Contract','submit'))

    def test_print_standard_forged_payload_and_cancelled(self):
        d=contract(submit=True)
        html=frappe.get_print('PZ Sales Contract',d.name,print_format='Standard')
        self.assertIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',html)
        self.assertIn('15. Authority, Law and Complete Agreement.',html)
        self.assertIn('Appendix A',html)
        self.assertIn('Commercial Schedule',html)
        from frappe.www.printview import get_html_and_style
        forged=d.as_dict()
        forged['customer_name']='FORGED BUYER'
        forged['first_family']='FORGED FAMILY'
        output=get_html_and_style(doc=json.dumps(forged,default=str),print_format='Standard')['html']
        self.assertNotIn('FORGED BUYER',output)
        self.assertIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',output)
        receipt(d,300,cash=True)
        self.assertNotIn('DRAFT — FIRST ADVANCE NOT CONFIRMED',frappe.get_print('PZ Sales Contract',d.name))
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
        si=make_sales_invoice(d.sales_order)
        si.insert()
        si.submit()
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        p=get_payment_entry('Sales Invoice',si.name,party_amount=300,bank_amount=300,bank_account='PZ Synthetic Cash - PZT')
        p.paid_amount=p.received_amount=300
        p.references[0].allocated_amount=300
        p.insert().submit()
        self.assertFalse(payment_status(d).payment_draft)
        si.items[0].db_set('sales_order','UNRELATED-SYNTHETIC-ORDER')
        self.assertTrue(payment_status(d).payment_draft)
