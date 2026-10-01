import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from pz_sales_contract.payments import payment_status, get_status
from pz_sales_contract.testing import setup_fixtures, contract, receipt, reconcile, COMPANY

# Every needed record is created explicitly below. Do not recursively import
# optional ERPNext fixtures (Payment Gateway belongs to another app in v16).
IGNORE_TEST_RECORD_DEPENDENCIES = ['Customer','Company','Address','Contact','Currency','Price List',
    'Incoterm','Holiday List','Sales Order','PZ Sales Contract','Item','UOM','Account','Cost Center','Project',
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

    def test_native_arithmetic_and_master_links(self):
        tax_account=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Income'),'name')
        d=contract(discount_amount=100,taxes=[dict(charge_type='On Net Total',account_head=tax_account,description='Synthetic 10%',rate=10)])
        self.assertEqual((d.subtotal,d.tax_total,d.grand_total,d.advance_required),(1000,90,990,297))
        self.assertEqual(d.taxes[0].tax_amount_after_discount_amount,90)
        d.submit()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'grand_total'),990)
        self.assertEqual(d.items[0].item_name,'Synthetic Bitumen')
        self.assertIn('Nine Hundred And Ninety',d.in_words)
        self.assertIn('Synthetic customer',d.address_display)

    def test_first_and_returning_contracts_and_no_toggle(self):
        first=contract(submit=True)
        self.assertTrue(payment_status(first).payment_draft)
        second=contract(customer=first.customer,submit=True)
        self.assertFalse(payment_status(second).payment_draft)
        first.first_family='forged'
        with self.assertRaises(frappe.ValidationError):
            first.save()

    def test_print_and_payment_evidence_respect_native_currency_precision(self):
        from bs4 import BeautifulSoup
        previous=frappe.defaults.get_global_default('currency_precision')
        try:
            for digits,rate,total,required,partial,shortfall,balance in [
                (2,100.12,300.36,90.11,90.10,0.01,210.25),
                (3,100.125,300.375,90.113,90.112,0.001,210.262)]:
                with self.subTest(currency_precision=digits):
                    frappe.defaults.set_global_default('currency_precision',str(digits))
                    d=contract(submit=True,items=[dict(item_code='PZ Synthetic Bitumen',qty=3,uom='Nos',
                        rate=rate,grade='60/70',packaging='Synthetic drums',specification_reference='Synthetic precision QA')])
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
        d=contract(submit=True)
        family=d.first_family
        d.cancel()
        self.assertEqual(frappe.db.get_value('Sales Order',d.sales_order,'docstatus'),2)
        amendment=frappe.copy_doc(d)
        amendment.docstatus=0
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

    def test_tax_zero_after_full_net_discount_and_actual_charge(self):
        account=frappe.db.get_value('Account',dict(company=COMPANY,is_group=0,root_type='Income'),'name')
        d=contract(discount_amount=1000,taxes=[
            dict(charge_type='On Net Total',account_head=account,description='Synthetic 10% discounted to zero',rate=10),
            dict(charge_type='Actual',account_head=account,description='Synthetic actual handling',tax_amount=10)])
        self.assertEqual(d.grand_total,10)
        self.assertEqual(d.taxes[0].tax_amount_after_discount_amount,0)
        html=frappe.get_print('PZ Sales Contract',d.name)
        self.assertIn('10.0% / 0.00',html)

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

    def historical_order(self):
        from pz_sales_contract.testing import new_customer
        customer,address,contact=new_customer()
        order=frappe.get_doc(dict(doctype='Sales Order',customer=customer,company=COMPANY,
            transaction_date=today(),delivery_date=today(),currency='USD',conversion_rate=1,
            selling_price_list='PZ Synthetic USD',order_type='Sales',customer_address=address.name,
            contact_person=contact.name,items=[dict(item_code='PZ Synthetic Bitumen',qty=10,rate=100,
            delivery_date=today())])).insert()
        order.submit()
        return order

    def historical_designation(self,order):
        return frappe.get_doc(dict(doctype='PZ Customer History',customer=order.customer,company=order.company,
            sales_order=order.name,prior_contract_evidence='Synthetic prior signed contract and finance migration review',
            bank_receiving_account='PZ Synthetic Bank - PZT',cash_receiving_account='PZ Synthetic Cash - PZT')).insert()

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
