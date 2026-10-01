from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.model.document import Document

from pz_sales_contract.payments import allocated_receipts


class PZCustomerHistory(Document):
    def validate(self):
        order = frappe.get_doc('Sales Order',self.sales_order)
        order.check_permission('read')
        if order.docstatus != 1 or order.customer != self.customer or order.company != self.company:
            frappe.throw('History requires a submitted matching Customer/Company Sales Order')
        # The designation is for pre-app contracts, never a way to bypass a current one.
        if frappe.db.exists('PZ Sales Contract',{'sales_order':order.name}):
            frappe.throw('Historical order must predate this app contract workflow')
        self.currency = order.currency
        precision = self.precision('advance_required')
        quantum = Decimal(10) ** -(2 if precision is None else precision)
        self.advance_required = float((Decimal(str(order.grand_total))*Decimal('.30')).quantize(quantum,rounding=ROUND_HALF_UP))
        if self.advance_required <= 0:
            frappe.throw('Historical contract must have a positive required advance')
        for key,kind in [('bank_receiving_account','Bank'),('cash_receiving_account','Cash')]:
            if self.get(key):
                account=frappe.get_doc('Account',self.get(key))
                account.check_permission('read')
                if account.company != self.company or account.account_type != kind or account.is_group or account.disabled:
                    frappe.throw('Historical receiving account must be an enabled matching seller Bank/Cash account')
                if (account.account_currency or frappe.db.get_value('Company',self.company,'default_currency')) != self.currency:
                    frappe.throw('Historical receiving account currency must match the order')

    def before_submit(self):
        confirmed,evidence=allocated_receipts(self)
        if confirmed < Decimal(str(self.advance_required)):
            frappe.throw('Historical designation requires the full 30% advance with qualifying native receipt evidence')
        self.validated_evidence=frappe.as_json(dict(confirmed=float(confirmed),required=self.advance_required,receipts=evidence))

    def on_submit(self):
        frappe.db.sql('SELECT name FROM `tabCustomer` WHERE name=%s FOR UPDATE',self.customer)
        rows=frappe.db.sql('SELECT name, established_history FROM `tabPZ Contract Registry` WHERE customer=%s FOR UPDATE',self.customer)
        if rows:
            registry,current=rows[0]
            status=frappe.db.sql('SELECT docstatus FROM `tabPZ Customer History` WHERE name=%s FOR UPDATE',current) if current else []
            if status and status[0][0]==1:
                frappe.throw('Cancel the existing historical designation before replacing it')
            frappe.db.set_value('PZ Contract Registry',registry,'established_history',self.name)
        else:
            frappe.get_doc(dict(doctype='PZ Contract Registry',customer=self.customer,established_history=self.name)).insert(ignore_permissions=True)

    def on_trash(self):
        frappe.throw('Keep historical designations for their finance audit trail; cancel instead of deleting')
