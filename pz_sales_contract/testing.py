"""Synthetic fixtures only. Use solely on a disposable test site."""
import frappe
from frappe.utils import today, add_days, getdate
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

COMPANY = 'PZ Synthetic QA'


def setup_fixtures():
    frappe.set_user('Administrator')
    # Fresh ERPNext sites have no setup-wizard tree roots yet. Create only the
    # synthetic-test prerequisites instead of relying on an existing pilot setup.
    for doctype,key,name in [('Customer Group','customer_group_name','All Customer Groups'),
                             ('Territory','territory_name','All Territories'),
                             ('Item Group','item_group_name','All Item Groups')]:
        if not frappe.db.exists(doctype,name):
            frappe.get_doc(dict(doctype=doctype,**{key:name},is_group=1)).insert()
    if not frappe.db.exists('UOM','Nos'):
        frappe.get_doc(dict(doctype='UOM',uom_name='Nos',must_be_whole_number=1)).insert()
    if not frappe.db.exists('Party Type','Customer'):
        frappe.get_doc(dict(doctype='Party Type',party_type='Customer',account_type='Receivable')).insert()
    if not frappe.db.exists('Customer Group','PZ Synthetic Customers'):
        frappe.get_doc(dict(doctype='Customer Group',customer_group_name='PZ Synthetic Customers',parent_customer_group='All Customer Groups',is_group=0)).insert()
    if not frappe.db.exists('Territory','PZ Synthetic Territory'):
        frappe.get_doc(dict(doctype='Territory',territory_name='PZ Synthetic Territory',parent_territory='All Territories',is_group=0)).insert()
    if not frappe.db.exists('Warehouse Type','Transit'):
        frappe.get_doc(dict(doctype='Warehouse Type',name='Transit',description='Standard transit prerequisite for synthetic Company')).insert()
    if not frappe.db.exists('Address Template',{'is_default':1}):
        frappe.get_doc(dict(doctype='Address Template',country='Iraq',is_default=1,
            template='{{ address_line1 }}<br>{{ city }}<br>{{ country }}')).insert()
    if not frappe.db.exists('Company', COMPANY):
        frappe.get_doc(dict(doctype='Company', company_name=COMPANY, abbr='PZT',
            default_currency='USD', country='Iraq', chart_of_accounts='Standard',
            enable_perpetual_inventory=0)).insert()
    year=getdate(today()).year
    if not frappe.db.exists('Fiscal Year', {'year_start_date':f'{year}-01-01','year_end_date':f'{year}-12-31'}):
        frappe.get_doc(dict(doctype='Fiscal Year', year=f'PZ Synthetic {year}',
            year_start_date=f'{year}-01-01', year_end_date=f'{year}-12-31')).insert()
    if not frappe.db.exists('Price List', 'PZ Synthetic USD'):
        frappe.get_doc(dict(doctype='Price List',price_list_name='PZ Synthetic USD',currency='USD',selling=1,enabled=1)).insert()
    if not frappe.db.exists('Incoterm', 'EXW'):
        frappe.get_doc(dict(doctype='Incoterm',incoterm='EXW',title='Ex Works')).insert()
    if not frappe.db.exists('Holiday List','PZ Synthetic Calendar'):
        frappe.get_doc(dict(doctype='Holiday List',holiday_list_name='PZ Synthetic Calendar',
            from_date=f'{year}-01-01',to_date=f'{year+1}-12-31',holidays=[dict(holiday_date=f'{year}-12-25',description='Synthetic closure')])).insert()
    if not frappe.db.exists('Item','PZ Synthetic Bitumen'):
        frappe.get_doc(dict(doctype='Item',item_code='PZ Synthetic Bitumen',item_name='Synthetic Bitumen',
            item_group='All Item Groups',stock_uom='Nos',is_stock_item=0,is_sales_item=1,
            description='Synthetic bitumen fixture; not a customer order')).insert()
    parent=frappe.db.get_value('Account',dict(company=COMPANY,is_group=1,root_type='Asset'), 'name')
    for name,kind in [('PZ Synthetic Bank','Bank'),('PZ Synthetic Cash','Cash')]:
        if not frappe.db.exists('Account',f'{name} - PZT'):
            frappe.get_doc(dict(doctype='Account',account_name=name,company=COMPANY,parent_account=parent,
                account_currency='USD',account_type=kind,is_group=0)).insert()
    if not frappe.db.exists('Bank','PZ Synthetic Bank'):
        frappe.get_doc(dict(doctype='Bank',bank_name='PZ Synthetic Bank')).insert()
    if not frappe.db.exists('Bank Account','PZ Synthetic Reconciliation - PZ Synthetic Bank'):
        ba=frappe.get_doc(dict(doctype='Bank Account',account_name='PZ Synthetic Reconciliation',bank='PZ Synthetic Bank',
            is_company_account=1,company=COMPANY,account='PZ Synthetic Bank - PZT')).insert()
    else:
        ba=frappe.get_doc('Bank Account','PZ Synthetic Reconciliation - PZ Synthetic Bank')
    if not frappe.db.exists('Address','PZ Synthetic Seller-Billing'):
        frappe.get_doc(dict(doctype='Address',address_title='PZ Synthetic Seller',address_type='Billing',
            address_line1='Synthetic test location',city='Synthetic City',country='Iraq',
            links=[dict(link_doctype='Company',link_name=COMPANY)])).insert()
    for email,role in [('pz-sales@example.invalid','Sales User'),('pz-manager@example.invalid','Sales Manager'),('pz-finance@example.invalid','Accounts Manager')]:
        if not frappe.db.exists('User',email):
            frappe.get_doc(dict(doctype='User',email=email,first_name='Synthetic',last_name=role,
                send_welcome_email=0,roles=[dict(role=role)])).insert()
        if role in ['Sales Manager','Accounts Manager']:
            frappe.get_doc('User',email).add_roles('Sales User')
        if role == 'Sales User':
            frappe.get_doc('User',email).add_roles('PZ Sales Contract User')
        elif role == 'Sales Manager':
            frappe.get_doc('User',email).add_roles('PZ Sales Contract Manager')
    return ba.name


def new_customer():
    customer='PZ Synthetic Customer '+frappe.generate_hash(length=8)
    frappe.get_doc(dict(doctype='Customer',customer_name=customer,customer_type='Company',
        customer_group='PZ Synthetic Customers',territory='PZ Synthetic Territory')).insert()
    address=frappe.get_doc(dict(doctype='Address',address_title=customer,address_type='Billing',
        address_line1='Synthetic customer address',city='Synthetic City',country='Iraq',
        links=[dict(link_doctype='Customer',link_name=customer)])).insert()
    contact=frappe.get_doc(dict(doctype='Contact',first_name='Synthetic',last_name='Buyer',
        email_ids=[dict(email_id='buyer@example.invalid',is_primary=1)],
        links=[dict(link_doctype='Customer',link_name=customer)])).insert()
    return customer,address,contact


def contract(customer=None, submit=False, **values):
    if not customer:
        customer,address,contact=new_customer()
    else:
        address=frappe.get_doc('Address',frappe.db.get_value('Dynamic Link',dict(parenttype='Address',link_doctype='Customer',link_name=customer),'parent'))
        contact=frappe.get_doc('Contact',frappe.db.get_value('Dynamic Link',dict(parenttype='Contact',link_doctype='Customer',link_name=customer),'parent'))
    d=dict(doctype='PZ Sales Contract',customer=customer,company=COMPANY,
        transaction_date=today(),delivery_date=add_days(today(),10),currency='USD',conversion_rate=1,
        selling_price_list='PZ Synthetic USD',customer_address=address.name,contact_person=contact.name,
        seller_address='PZ Synthetic Seller-Billing',seller_signatory='Synthetic Seller',seller_position='Test manager',buyer_position='Test buyer',
        items=[dict(item_code='PZ Synthetic Bitumen',qty=10,uom='Nos',rate=100,grade='60/70',packaging='Synthetic drums',specification_reference='Synthetic specification QA-001')],
        specifications=[dict(item_code='PZ Synthetic Bitumen',property='Penetration',unit='dmm',test_method='Synthetic method',requirement='60-70 (demo only)')],
        discount_amount=0,incoterm='EXW',named_place='Synthetic pickup point',delivery_arrangement='Synthetic signed loading arrangement',
        transport_responsibility='Buyer (synthetic agreement)',insurance_responsibility='Buyer (synthetic agreement)',
        measurement_basis='Synthetic units; no tolerance or price adjustment agreed',timezone='Asia/Baghdad',
        business_days='Monday,Tuesday,Wednesday,Thursday,Friday',opens_at='09:00:00',closes_at='17:00:00',holiday_list='PZ Synthetic Calendar',
        notice_channel='buyer@example.invalid (synthetic)',collection_grace=48,grace_unit='Calendar hours',
        collection_arrangement='Synthetic appointment only',delay_charges='None agreed (synthetic)',penalty_basis_cap='None agreed (synthetic)',
        cure_period='5 calendar days (synthetic)',latent_claim_period='7 calendar days after discovery (synthetic)',
        force_majeure_threshold='30 calendar days (synthetic)',governing_law='Synthetic placeholder; not legal advice or real agreement',courts='Synthetic courts placeholder',
        bank_receiving_account='PZ Synthetic Bank - PZT',cash_receiving_account='PZ Synthetic Cash - PZT',
        beneficiary='SYNTHETIC — DO NOT PAY',bank_branch='SYNTHETIC BANK — NO REAL ACCOUNT',account_iban='USD / SYNTHETIC-NOT-AN-ACCOUNT',swift_reference='SYNTHETIC ONLY')
    d.update(values)
    doc=frappe.get_doc(d).insert()
    if submit:
        doc.submit()
    return doc


def receipt(doc, amount, cash=False, submit=True):
    payment=get_payment_entry('Sales Order',doc.sales_order,party_amount=amount,
        bank_amount=amount,bank_account=f'PZ Synthetic {"Cash" if cash else "Bank"} - PZT')
    payment.reference_no='SYNTHETIC-'+frappe.generate_hash(length=6)
    payment.reference_date=today()
    payment.paid_amount=amount
    payment.received_amount=amount
    payment.references[0].allocated_amount=amount
    payment.insert()
    if submit:
        payment.submit()
    return payment


def refund(doc, amount, reference_doctype='Sales Order', reference_name=None, allocations=None):
    payment=get_payment_entry(reference_doctype,reference_name or doc.sales_order,
        party_amount=amount,bank_amount=amount,bank_account='PZ Synthetic Cash - PZT')
    if payment.payment_type == 'Receive':
        payment.payment_type='Pay'
        payment.paid_from,payment.paid_to=payment.paid_to,payment.paid_from
    payment.reference_no='SYNTHETIC-REFUND-'+frappe.generate_hash(length=6)
    payment.reference_date=today()
    payment.paid_amount=payment.received_amount=amount
    if allocations is not None:
        payment.set('references', [])
        for doctype,name,allocated in allocations:
            payment.append('references',dict(reference_doctype=doctype,reference_name=name,
                allocated_amount=allocated))
    payment.insert()
    payment.submit()
    return payment


def reconcile(payment, bank_account, amount=None, submit=True):
    bt=frappe.get_doc(dict(doctype='Bank Transaction',date=today(),deposit=amount or payment.received_amount,
        withdrawal=0,currency='USD',bank_account=bank_account,company=COMPANY,
        description='Synthetic contract reconciliation',transaction_id='SYNTHETIC-'+frappe.generate_hash(length=10))).insert()
    if submit:
        bt.submit()
        bt.add_payment_entries([dict(payment_doctype='Payment Entry',payment_name=payment.name)])
        bt.save()
    return bt
