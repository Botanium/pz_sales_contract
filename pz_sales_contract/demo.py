"""Synthetic evidence generation. Refuses to run outside disposable app test sites."""
import io
import json
import subprocess
import sys
from pathlib import Path

import frappe
from pypdf import PdfReader
from pz_sales_contract.testing import setup_fixtures, contract, receipt, new_customer, synthetic_bitumen_grade


def ensure_disposable():
    if not frappe.local.site.startswith(('pz-contract-test.', 'pz-contract-ci.')) or not frappe.conf.allow_tests:
        frappe.throw('Synthetic evidence tools run only on the dedicated disposable contract test site')
    frappe.set_user('Administrator')
    frappe.flags.in_test=True


def concurrency():
    ensure_disposable()
    setup_fixtures()
    customer,_,_=new_customer()
    frappe.db.commit()
    code='''import sys,frappe
frappe.init(site=sys.argv[1]);frappe.connect();frappe.set_user('Administrator')
from pz_sales_contract.testing import contract
for attempt in range(3):
    try:
        contract(customer=sys.argv[2]);frappe.db.commit();print(attempt);break
    except frappe.QueryDeadlockError:
        frappe.db.rollback()
        if attempt==2: raise
frappe.destroy()
'''
    children=[subprocess.Popen([sys.executable,'-c',code,frappe.local.site,customer],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
    retries=0
    for child in children:
        out,err=child.communicate(timeout=45)
        if child.returncode:
            raise RuntimeError(err.decode())
        retries+=int(out.decode().strip())
    frappe.db.rollback()
    names=frappe.get_all('PZ Sales Contract',filters={'customer':customer},pluck='name')
    families=[frappe.db.get_value('PZ Sales Contract',name,'first_family') for name in names]
    reserved=frappe.db.get_value('PZ Contract Registry',{'customer':customer},'first_family')
    if len(names)!=2 or families.count(reserved)!=1:
        raise RuntimeError('Concurrent first-family reservation failed')
    if frappe.db.count('PZ Contract Registry',{'customer':customer})!=1:
        raise RuntimeError('Duplicate customer reservation')
    return {'concurrent_inserts':2,'registries':1,'first_families':1,'transaction_retries':retries,'result':'PASS'}


def export():
    ensure_disposable()
    setup_fixtures()
    frappe.db.set_single_value('Print Settings','allow_print_for_draft',1)
    frappe.db.set_single_value('Print Settings','allow_print_for_cancelled',1)
    output=Path('/tmp/pz-contract-evidence');output.mkdir(exist_ok=True)
    first=contract(submit=True,print_as_draft=1)
    results=[]
    def save(label,doc,expected_draft):
        html=frappe.get_print('PZ Sales Contract',doc.name,print_format='Petrol Zone Sales Contract',no_letterhead=1)
        pdf=frappe.get_print('PZ Sales Contract',doc.name,print_format='Petrol Zone Sales Contract',no_letterhead=1,as_pdf=True)
        reader=PdfReader(io.BytesIO(pdf))
        text=' '.join(page.extract_text() or '' for page in reader.pages)
        if ('DRAFT' in text)!=bool(doc.print_as_draft):
            raise RuntimeError('Incorrect manual print Draft state in PDF')
        if expected_draft:
            if not all('DRAFT' in (page.extract_text() or '') for page in reader.pages):
                raise RuntimeError('Draft header missing from continuation page')
        if 'Amount in words: None' in text:
            raise RuntimeError('Missing amount in words')
        for expected in ['1. Contract Documents','2. Contract Amount and Payment Split',
            'Signatures','Payment Instructions','Contract Amount','PZ-SYNTHETIC-60-70']:
            if expected not in text:
                raise RuntimeError('Missing PDF content: '+expected)
        (output/(label+'.pdf')).write_bytes(pdf)
        (output/(label+'.html')).write_text(html)
        results.append({'file':label+'.pdf','pages':len(reader.pages),'contract':doc.name,'print_as_draft':bool(doc.print_as_draft)})
    save('Petrol-Zone-Synthetic-Operator-Marked-DRAFT',first,True)
    receipt(first,first.advance_required,cash=True)
    save('Petrol-Zone-Synthetic-Paid-Still-Operator-Marked-DRAFT',first,True)
    first.print_as_draft=0
    first.save()
    save('Petrol-Zone-Synthetic-Paid-Operator-Unmarked',first,False)
    later=contract(customer=first.customer,submit=True)
    save('Petrol-Zone-Synthetic-Returning-Customer',later,False)
    previous=frappe.db.get_single_value('Selling Settings','allow_multiple_items')
    frappe.db.set_single_value('Selling Settings','allow_multiple_items',1)
    grade_master = synthetic_bitumen_grade()
    long=contract(items=[dict(item_code='PZ Synthetic Bitumen',qty=1,uom='Nos',rate=10,
        grade_master=grade_master,grade='PZ-SYNTHETIC-60-70',packaging='Synthetic drums',
        specification_reference='Synthetic long-order QA') for _ in range(30)],submit=True)
    long.print_as_draft=1
    long.save()
    save('Petrol-Zone-Synthetic-Long-Operator-Marked-DRAFT',long,True)
    frappe.db.set_single_value('Selling Settings','allow_multiple_items',previous)
    frappe.db.commit()
    (output/'manifest.json').write_text(json.dumps(results,indent=2))
    return results
