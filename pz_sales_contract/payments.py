"""Live receipt + allocation + bank reconciliation evidence; no editable paid flag."""
from decimal import Decimal

import frappe
from frappe.utils import getdate, nowdate


def number(value):
    return Decimal(str(value or 0))


def refunded_allocations(doc, invoices):
    """Native Customer payouts reduce advance evidence; unsupported refunds fail closed."""
    # A Customer payout's unallocated balance cannot be attributed to one order.
    # This includes a payout partly allocated to an otherwise unrelated order.
    if frappe.db.exists('Payment Entry', dict(docstatus=1, payment_type='Pay',
            party_type='Customer', party=doc.customer, company=doc.company,
            unallocated_amount=('!=',0))):
        return None, []
    unsupported_payout = frappe.db.sql('''
        SELECT pe.name FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` ref ON ref.parent=pe.name AND ref.parenttype='Payment Entry'
        WHERE pe.docstatus=1 AND pe.payment_type='Pay' AND pe.party_type='Customer'
          AND pe.party=%s AND pe.company=%s AND ref.allocated_amount<>0
          AND ref.reference_doctype NOT IN ('Sales Order','Sales Invoice')
        LIMIT 1
    ''', (doc.customer, doc.company))
    if unsupported_payout:
        return None, []
    returns = frappe.db.sql('''
        SELECT si.name FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Item` sii ON sii.parent=si.name AND sii.parenttype='Sales Invoice'
        WHERE si.docstatus=1 AND si.is_return=1 AND si.customer=%(customer)s AND si.company=%(company)s
        GROUP BY si.name
        HAVING MAX(si.return_against) IN %(invoices)s
          OR (COUNT(sii.name)>0 AND SUM(CASE WHEN sii.sales_order=%(order)s THEN 0 ELSE 1 END)=0)
    ''', dict(customer=doc.customer, company=doc.company, order=doc.sales_order,
              invoices=tuple(invoices) or ('',)), pluck=True)
    # Detect payouts against mixed-order/foreign-currency invoices too. Their
    # order share cannot be inferred safely, so they must not be ignored.
    related_invoices = frappe.db.sql('''
        SELECT si.name FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Item` sii ON sii.parent=si.name AND sii.parenttype='Sales Invoice'
        WHERE si.docstatus=1 AND si.customer=%(customer)s AND si.company=%(company)s
        GROUP BY si.name
        HAVING MAX(si.return_against) IN (
            SELECT parent FROM `tabSales Invoice Item`
            WHERE parenttype='Sales Invoice' AND sales_order=%(order)s)
          OR SUM(CASE WHEN sii.sales_order=%(order)s THEN 1 ELSE 0 END)>0
    ''', dict(customer=doc.customer, company=doc.company, order=doc.sales_order), pluck=True)
    # Journal Entries are not qualifying receipts. A native Customer debit plus
    # live Cash/Bank outflow can nevertheless refund an invoice-reconciled
    # advance. Unsupported or unassigned payouts invalidate the evidence.
    journal_refund = frappe.db.sql('''
        SELECT je.name FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` ja ON ja.parent=je.name AND ja.parenttype='Journal Entry'
        WHERE je.docstatus=1 AND je.company=%(company)s
          AND ja.party_type='Customer' AND ja.party=%(customer)s AND ja.debit_in_account_currency>0
          AND ((ja.reference_type='Sales Order' AND ja.reference_name=%(order)s)
            OR (ja.reference_type='Sales Invoice' AND ja.reference_name IN %(related)s)
            OR COALESCE(ja.reference_type,'') NOT IN ('Sales Order','Sales Invoice')
            OR COALESCE(ja.reference_name,'')='')
          AND EXISTS (SELECT 1 FROM `tabGL Entry` gl
              JOIN `tabAccount` account ON account.name=gl.account
              WHERE gl.voucher_type='Journal Entry' AND gl.voucher_no=je.name
                AND gl.company=%(company)s AND gl.is_cancelled=0
                AND gl.credit_in_account_currency>gl.debit_in_account_currency
                AND account.account_type IN ('Cash','Bank'))
        LIMIT 1
    ''', dict(customer=doc.customer, company=doc.company, order=doc.sales_order,
              related=tuple(related_invoices) or ('',)))
    if journal_refund:
        return None, []
    rows = frappe.db.sql('''
        SELECT pe.name, pe.paid_amount, pe.received_amount, pe.paid_to,
               pe.paid_from_account_currency, pe.paid_to_account_currency,
               SUM(ABS(ref.allocated_amount)) AS allocated,
               MAX(CASE WHEN ref.reference_doctype='Sales Invoice'
                   AND (COALESCE(si.currency,'')<>%(currency)s
                     OR ref.reference_name NOT IN %(eligible)s) THEN 1 ELSE 0 END) AS unsupported_invoice
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` ref ON ref.parent=pe.name AND ref.parenttype='Payment Entry'
        LEFT JOIN `tabSales Invoice` si ON ref.reference_doctype='Sales Invoice' AND si.name=ref.reference_name
        WHERE pe.docstatus=1 AND pe.payment_type='Pay' AND pe.party_type='Customer'
          AND pe.party=%(customer)s AND pe.company=%(company)s
          AND ((ref.reference_doctype='Sales Order' AND ref.reference_name=%(order)s)
            OR (ref.reference_doctype='Sales Invoice' AND ref.reference_name IN %(invoices)s))
        GROUP BY pe.name
    ''', dict(customer=doc.customer, company=doc.company, currency=doc.currency,
              order=doc.sales_order, invoices=tuple(related_invoices) or ('',),
              eligible=tuple(invoices+returns) or ('',)), as_dict=True)
    refunded = Decimal('0')
    evidence = []
    for pe in rows:
        allocation = number(pe.allocated)
        if allocation == 0:
            continue
        paid, received = number(pe.paid_amount), number(pe.received_amount)
        if (paid <= 0 or received <= 0 or paid != received or allocation > received
                or pe.unsupported_invoice or pe.paid_from_account_currency != doc.currency
                or pe.paid_to_account_currency != doc.currency):
            return None, []
        gl = number(frappe.db.sql('''
            SELECT SUM(debit_in_account_currency-credit_in_account_currency)
            FROM `tabGL Entry` WHERE voucher_type='Payment Entry' AND voucher_no=%s
              AND company=%s AND account=%s AND account_currency=%s AND is_cancelled=0
              AND party_type='Customer' AND party=%s
        ''', (pe.name, doc.company, pe.paid_to, doc.currency, doc.customer))[0][0])
        if gl < received:
            return None, []
        refunded += allocation
        evidence.append(dict(payment_entry=pe.name, allocated=-float(allocation)))
    return refunded, evidence


def allocated_receipts(doc):
    """Shared native receipt checks for current contracts and restricted history."""
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
        refunded, refund_evidence = refunded_allocations(doc, invoices)
        if refunded is None:
            return Decimal('0'), []
        confirmed = max(Decimal('0'), confirmed-refunded)
        evidence.extend(refund_evidence)
    return confirmed, evidence


def history_status(history):
    if history.docstatus != 1 or number(history.advance_required) <= 0:
        return False
    confirmed, _ = allocated_receipts(history)
    return confirmed >= number(history.advance_required)


def payment_status(doc):
    registry = frappe.db.get_value('PZ Contract Registry',{'customer':doc.customer},
        ['first_family','established_history'],as_dict=True)
    first = not registry or not registry.first_family or registry.first_family == doc.first_family
    historical = False
    if registry and registry.established_history:
        history = frappe.get_doc('PZ Customer History',registry.established_history)
        historical = history.customer == doc.customer and history_status(history)
        if historical:
            first = False
    confirmed, evidence = allocated_receipts(doc)
    required = number(doc.advance_required)
    return frappe._dict(first_contract=first, established_history=historical,
        payment_draft=bool(first and (required <= 0 or confirmed < required)),
        required=float(required), confirmed=float(confirmed),
        currency_precision=doc.precision('advance_required'), evidence=evidence)


@frappe.whitelist()
def get_status(name):
    doc = frappe.get_doc('PZ Sales Contract', name)
    doc.check_permission('read')
    return payment_status(doc)
