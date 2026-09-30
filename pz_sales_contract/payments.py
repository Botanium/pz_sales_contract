"""Live receipt + allocation + bank reconciliation evidence; no editable paid flag."""
from decimal import Decimal

import frappe
from frappe.utils import getdate, nowdate


def number(value):
    return Decimal(str(value or 0))


def payment_status(doc):
    registry = frappe.db.get_value('PZ Contract Registry', {'customer':doc.customer}, 'first_family')
    first = not registry or registry == doc.first_family
    confirmed = Decimal('0')
    evidence = []
    order_name = doc.sales_order
    order = frappe.db.get_value('Sales Order', order_name,
        ['docstatus', 'customer', 'company', 'currency'], as_dict=True) if order_name else None
    if order and order.docstatus == 1 and (order.customer, order.company, order.currency) == (doc.customer, doc.company, doc.currency):
        # Invoice allocations survive native advance reconciliation. Only invoices wholly
        # attributable to this one order are eligible; mixed-order invoices fail closed.
        invoices = frappe.db.sql('''
            SELECT si.name FROM `tabSales Invoice` si
            JOIN `tabSales Invoice Item` sii ON sii.parent = si.name AND sii.parenttype='Sales Invoice'
            WHERE si.docstatus=1 AND si.is_return=0 AND si.customer=%s
              AND si.company=%s AND si.currency=%s
            GROUP BY si.name
            HAVING SUM(CASE WHEN sii.sales_order=%s THEN 0 ELSE 1 END)=0
        ''', (doc.customer, doc.company, doc.currency, order_name), pluck=True)
        rows = frappe.db.sql('''
            SELECT pe.name, pe.paid_amount, pe.received_amount, pe.paid_to,
                   pe.clearance_date, SUM(ref.allocated_amount) AS allocated
            FROM `tabPayment Entry` pe
            JOIN `tabPayment Entry Reference` ref ON ref.parent=pe.name
              AND ref.parenttype='Payment Entry'
            WHERE pe.docstatus=1 AND pe.payment_type='Receive' AND pe.party_type='Customer'
              AND pe.party=%(customer)s AND pe.company=%(company)s
              AND pe.paid_from_account_currency=%(currency)s
              AND pe.paid_to_account_currency=%(currency)s
              AND ((ref.reference_doctype='Sales Order' AND ref.reference_name=%(order)s)
                OR (ref.reference_doctype='Sales Invoice' AND ref.reference_name IN %(invoices)s))
            GROUP BY pe.name
        ''', dict(customer=doc.customer, company=doc.company, currency=doc.currency,
                  order=order_name, invoices=tuple(invoices) or ('',)), as_dict=True)
        for pe in rows:
            paid, received = number(pe.paid_amount), number(pe.received_amount)
            allocation = number(pe.allocated)
            if paid <= 0 or received <= 0 or paid != received or allocation <= 0 or allocation > paid:
                continue
            account_type = frappe.db.get_value('Account', pe.paid_to, 'account_type')
            nominated = doc.bank_receiving_account if account_type == 'Bank' else doc.cash_receiving_account
            if account_type not in ['Cash', 'Bank'] or pe.paid_to != nominated:
                continue
            if account_type == 'Bank' and (not pe.clearance_date or getdate(pe.clearance_date) > getdate(nowdate())):
                continue
            # Join independent of contract allocation, then group each bank transaction.
            # A receipt is counted only when its whole bank amount is reconciled. Partial
            # bank clearance never attributes an arbitrary part to this specific order.
            cleared = frappe.db.sql('''
                SELECT bt.name, bt.deposit, bt.allocated_amount AS total_allocated,
                       SUM(btp.allocated_amount) AS amount
                FROM `tabBank Transaction` bt
                JOIN `tabBank Transaction Payments` btp ON btp.parent=bt.name
                  AND btp.parenttype='Bank Transaction'
                JOIN `tabBank Account` ba ON ba.name=bt.bank_account
                WHERE bt.docstatus=1 AND bt.company=%s AND ba.company=%s
                  AND bt.currency=%s AND ba.account=%s AND ba.is_company_account=1
                  AND bt.deposit>0 AND COALESCE(bt.withdrawal,0)=0 AND bt.date<=%s
                  AND btp.payment_document='Payment Entry' AND btp.payment_entry=%s
                GROUP BY bt.name
            ''', (doc.company, doc.company, doc.currency, pe.paid_to, nowdate(), pe.name), as_dict=True)
            bank_amount = sum((number(row.amount) for row in cleared
                if number(row.amount) > 0 and number(row.total_allocated) <= number(row.deposit)
                and number(row.amount) <= number(row.deposit)), Decimal('0'))
            gl = number(frappe.db.sql('''
                SELECT SUM(debit_in_account_currency-credit_in_account_currency)
                FROM `tabGL Entry` WHERE voucher_type='Payment Entry' AND voucher_no=%s
                  AND company=%s AND account=%s AND account_currency=%s AND is_cancelled=0
            ''', (pe.name, doc.company, pe.paid_to, doc.currency))[0][0])
            if (account_type == 'Cash' or bank_amount >= received) and gl >= received:
                amount = min(allocation, paid)
                confirmed += amount
                evidence.append(dict(payment_entry=pe.name, allocated=float(amount)))
    required = number(doc.advance_required)
    return frappe._dict(first_contract=first, payment_draft=bool(first and (required <= 0 or confirmed < required)),
                        required=float(required), confirmed=float(confirmed), evidence=evidence)


@frappe.whitelist()
def get_status(name):
    doc = frappe.get_doc('PZ Sales Contract', name)
    doc.check_permission('read')
    return payment_status(doc)
