"""Synthetic fixtures only. Use solely on a disposable test site."""
import frappe
from frappe.utils import today, add_days, getdate
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

COMPANY = 'PZ Synthetic QA'
DISPOSABLE_SITE_PREFIXES = ('pz-contract-test.', 'pz-contract-ci.')


def require_disposable_test_site():
    site = getattr(frappe.local, 'site', None)
    if not site or not site.startswith(DISPOSABLE_SITE_PREFIXES) or not frappe.conf.allow_tests:
        frappe.throw('Synthetic contract fixtures run only on dedicated disposable test sites with allow_tests enabled')


def synthetic_bitumen_grade(grade_code='60/70'):
    require_disposable_test_site()
    if not frappe.db.exists('DocType', 'Bitumen Grade'):
        frappe.throw('The Bitumen Grade master must be installed for synthetic contract tests')
    token = grade_code.replace('/', '-')
    synthetic_code = f'PZ-SYNTHETIC-{token}'
    meta = frappe.get_meta('Bitumen Grade')
    code_field = 'grade_code' if meta.has_field('grade_code') else None
    filters = {code_field: synthetic_code} if code_field else {'name': synthetic_code}
    name = frappe.db.get_value('Bitumen Grade', filters, 'name')
    if name and (not meta.has_field('disabled') or not frappe.db.get_value('Bitumen Grade', name, 'disabled')):
        return name

    # Never reuse a real or disabled grade in synthetic tests. When the optional
    # code field is absent, use a stable synthetic document name instead.
    if name:
        synthetic_code = f'{synthetic_code}-{frappe.generate_hash(length=6)}'
    values = {'doctype': 'Bitumen Grade'}
    if code_field:
        values[code_field] = synthetic_code
    else:
        values['name'] = synthetic_code
    if meta.has_field('grade_name'):
        values['grade_name'] = f'Synthetic {grade_code}'
    if meta.has_field('disabled'):
        values['disabled'] = 0
    if meta.has_field('notes'):
        values['notes'] = 'Synthetic test data only'
    return frappe.get_doc(values).insert().name


def ensure_synthetic_grade_prerequisites():
    """Install only missing external Grade prerequisites on disposable test sites."""
    require_disposable_test_site()
    if not frappe.db.exists('DocType', 'Bitumen Grade'):
        frappe.get_doc(dict(
            doctype='DocType', name='Bitumen Grade', module='Sales Contracts',
            custom=1, autoname='field:grade_code', title_field='grade_name',
            fields=[
                dict(fieldname='grade_code', label='Grade Code', fieldtype='Data', reqd=1, unique=1),
                dict(fieldname='grade_name', label='Grade Name', fieldtype='Data', reqd=1),
                dict(fieldname='disabled', label='Disabled', fieldtype='Check'),
                dict(fieldname='notes', label='Notes', fieldtype='Small Text'),
            ],
            permissions=[
                dict(role='PZ Sales Contract User', read=1, select=1),
                dict(role='PZ Sales Contract Manager', read=1, select=1),
            ],
        )).insert(ignore_permissions=True)
        frappe.clear_cache(doctype='Bitumen Grade')

    if not frappe.get_meta('Sales Order Item').has_field('custom_bitumen_grade'):
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        create_custom_fields({
            'Sales Order Item': [dict(
                fieldname='custom_bitumen_grade', label='Bitumen Grade',
                fieldtype='Link', options='Bitumen Grade', insert_after='item_code',
            )],
        }, update=False)
        frappe.clear_cache(doctype='Sales Order Item')


def setup_fixtures():
    require_disposable_test_site()
    frappe.set_user('Administrator')
    if not frappe.db.exists('PZ Contract Location', 'PZ-SYNTHETIC-LOCATION'):
        frappe.get_doc(dict(doctype='PZ Contract Location', location_name='Synthetic pickup point')).insert(
            set_name='PZ-SYNTHETIC-LOCATION')
    # Fresh ERPNext sites have no setup-wizard tree roots yet. Create only the
    # synthetic-test prerequisites instead of relying on an existing pilot setup.
    ensure_synthetic_grade_prerequisites()
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
    frappe.db.set_single_value('Selling Settings', 'selling_price_list', 'PZ Synthetic USD')
    for code, title in [
        ('EXW', 'Ex Works'), ('FOB', 'Free On Board'), ('CIF', 'Cost Insurance and Freight'),
        ('FCA', 'Free Carrier'),
    ]:
        if not frappe.db.exists('Incoterm', code):
            frappe.get_doc(dict(doctype='Incoterm',incoterm=code,title=title)).insert()
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
    require_disposable_test_site()
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


def contract(customer=None, submit=False, insert=True, submit_sales_order=True, **values):
    require_disposable_test_site()
    if not customer:
        customer,address,contact=new_customer()
    else:
        address=frappe.get_doc('Address',frappe.db.get_value('Dynamic Link',dict(parenttype='Address',link_doctype='Customer',link_name=customer),'parent'))
        contact=frappe.get_doc('Contact',frappe.db.get_value('Dynamic Link',dict(parenttype='Contact',link_doctype='Customer',link_name=customer),'parent'))
    d=dict(doctype='PZ Sales Contract',customer=customer,company=COMPANY,
        customer_name='Synthetic Buyer Legal Name', customer_tax_id='SYNTHETIC-ID',
        address_display='Synthetic buyer address', buyer_phone='0000000000',
        contact_display='Synthetic Buyer Representative', buyer_email_phone='0000000000',
        transaction_date=today(),currency='USD',conversion_rate=1,
        selling_price_list='PZ Synthetic USD',customer_address=address.name,contact_person=contact.name,
        seller_address='PZ Synthetic Seller-Billing',seller_signatory='Synthetic Seller',seller_position='Test manager',buyer_position='Test buyer',
        items=[dict(item_code='PZ Synthetic Bitumen',qty=10,uom='Nos',rate=100,
            grade_master=synthetic_bitumen_grade(),grade='PZ-SYNTHETIC-60-70',
            packaging='Synthetic drums',specification_reference='Synthetic specification QA-001')],
        specifications=[],
        discount_amount=0,incoterm='EXW',contract_location='PZ-SYNTHETIC-LOCATION',named_place='Synthetic pickup point',delivery_arrangement='Synthetic signed loading arrangement',
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
    doc=frappe.get_doc(d)
    if insert:
        doc.insert()
    if submit:
        doc.submit()
        if submit_sales_order and doc.sales_order:
            order=frappe.get_doc('Sales Order',doc.sales_order)
            if order.docstatus == 0:
                # Simulate the user's separate Sales Order completion step in
                # tests that exercise submitted-order receipt integrations.
                order.delivery_date=add_days(today(),10)
                for row in order.items:
                    row.delivery_date=order.delivery_date
                order.save().submit()
    return doc


def receipt(doc, amount, cash=False, submit=True):
    require_disposable_test_site()
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
    require_disposable_test_site()
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
    require_disposable_test_site()
    bt=frappe.get_doc(dict(doctype='Bank Transaction',date=today(),deposit=amount or payment.received_amount,
        withdrawal=0,currency='USD',bank_account=bank_account,company=COMPANY,
        description='Synthetic contract reconciliation',transaction_id='SYNTHETIC-'+frappe.generate_hash(length=10))).insert()
    if submit:
        bt.submit()
        bt.add_payment_entries([dict(payment_doctype='Payment Entry',payment_name=payment.name)])
        bt.save()
    return bt
