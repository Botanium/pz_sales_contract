from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from pz_sales_contract.calendar import add_open_hours, schedule


class PZSalesContract(Document):
    def before_insert(self):
        # Customer row lock serialises simultaneous first inserts across all companies.
        frappe.db.sql('SELECT name FROM `tabCustomer` WHERE name=%s FOR UPDATE', self.customer)
        if self.amended_from:
            original = frappe.get_doc(self.doctype, self.amended_from)
            original.check_permission('read')
            if original.docstatus != 2 or original.customer != self.customer or original.company != self.company:
                frappe.throw('Amendments require a cancelled contract with the same customer and company')
            self.first_family = original.first_family
        else:
            self.first_family = frappe.generate_hash(length=20)
        # A locking current read is essential here: ordinary exists() can read
        # an earlier REPEATABLE READ snapshot even after waiting for Customer.
        reservation = frappe.db.sql('SELECT name FROM `tabPZ Contract Registry` WHERE customer=%s FOR UPDATE',self.customer)
        if not reservation:
            frappe.get_doc(dict(doctype='PZ Contract Registry', customer=self.customer,
                first_family=self.first_family)).insert(ignore_permissions=True)

    def validate(self):
        old = self.get_doc_before_save()
        if old:
            for key in ['customer', 'company', 'first_family', 'sales_order', 'amended_from']:
                if self.get(key) != old.get(key):
                    frappe.throw(f'{key} cannot be changed after creation')
        elif self.is_new():
            # Reject forged readonly internal values from REST/import as well as Desk.
            self.sales_order = None
        self.validate_links_and_snapshots()
        self.validate_schedule()
        order = self.build_order()
        order.set_missing_values()
        order.calculate_taxes_and_totals()
        order.set_total_in_words()
        if order.grand_total <= 0 or self.discount_amount < 0 or self.discount_amount > order.total:
            frappe.throw('Contract total must be positive and discount within subtotal')
        self.subtotal = order.total
        self.tax_total = order.total_taxes_and_charges
        self.grand_total = order.grand_total
        precision = self.precision('advance_required') or 2
        quantum = Decimal(10) ** -precision
        self.advance_required = float((Decimal(str(self.grand_total))*Decimal('.30')).quantize(quantum, rounding=ROUND_HALF_UP))
        self.balance_required = self.grand_total - self.advance_required
        self.in_words = order.in_words
        for row, item in zip(self.items, order.items, strict=True):
            row.amount = item.amount
        for row, calculated in zip(self.taxes, order.taxes, strict=True):
            for key in ['tax_amount','tax_amount_after_discount_amount','base_tax_amount',
                        'base_tax_amount_after_discount_amount','total','base_total']:
                row.set(key, calculated.get(key))

    def validate_links_and_snapshots(self):
        customer = frappe.get_doc('Customer', self.customer)
        customer.check_permission('read')
        if customer.disabled:
            frappe.throw('Disabled customers cannot receive contracts')
        self.customer_name, self.customer_tax_id = customer.customer_name, customer.tax_id
        for key, doctype, parenttype, parent in [
            ('customer_address', 'Address', 'Customer', self.customer),
            ('seller_address', 'Address', 'Company', self.company),
            ('contact_person', 'Contact', 'Customer', self.customer)]:
            linked = frappe.get_doc(doctype, self.get(key))
            linked.check_permission('read')
            if not any(link.link_doctype == parenttype and link.link_name == parent for link in linked.links):
                frappe.throw(f'{key} must belong to the selected {parenttype}')
            if doctype == 'Address':
                snapshot = ', '.join(str(linked.get(k)) for k in ['address_line1','address_line2','city','state','pincode','country'] if linked.get(k))
                self.set('address_display' if parenttype == 'Customer' else 'seller_address_display', snapshot)
            else:
                self.contact_display = ' / '.join(str(v) for v in [linked.full_name, linked.designation,
                    linked.email_id, linked.mobile_no or linked.phone] if v)
        frappe.get_doc('Company', self.company).check_permission('read')
        currency = frappe.db.get_value('Company', self.company, 'default_currency')
        if self.conversion_rate <= 0 or (currency == self.currency and self.conversion_rate != 1):
            frappe.throw('Set a valid exchange rate; company currency must use 1')
        price_list = frappe.get_doc('Price List', self.selling_price_list)
        if not price_list.enabled or not price_list.selling or price_list.currency != self.currency:
            frappe.throw('Choose an enabled selling price list in the contract currency')
        for key, kind in [('bank_receiving_account','Bank'),('cash_receiving_account','Cash')]:
            if self.get(key):
                account = frappe.get_doc('Account',self.get(key))
                account.check_permission('read')
                if account.company != self.company or account.account_type != kind or account.is_group or account.disabled:
                    frappe.throw(f'{key} must be an enabled seller {kind} ledger account')
                if (account.account_currency or currency) != self.currency:
                    frappe.throw('Nominated receiving accounts must use the contract currency')
        for item in self.items:
            master = frappe.get_doc('Item', item.item_code)
            master.check_permission('read')
            if master.disabled or not master.is_sales_item or item.qty <= 0 or item.rate <= 0:
                frappe.throw('Choose an enabled sales Item and positive quantity/rate')
            factor = 1 if item.uom == master.stock_uom else next((r.conversion_factor for r in master.uoms if r.uom == item.uom), None)
            if not factor or factor <= 0:
                frappe.throw(f'No ERP UOM conversion exists for {item.item_code}: {item.uom}')
            item.item_name, item.description, item.conversion_factor = master.item_name, master.description, factor
        for row in self.specifications:
            if row.item_code not in {r.item_code for r in self.items}:
                frappe.throw('Specifications must refer to a product in this contract')
        if {r.item_code for r in self.specifications} != {r.item_code for r in self.items}:
            frappe.throw('Enter agreed specifications for every product')
        for tax in self.taxes:
            if tax.charge_type not in ['Actual', 'On Net Total'] or tax.included_in_print_rate or (tax.rate or 0) < 0 or (tax.tax_amount or 0) < 0:
                frappe.throw('This version supports additional Actual or On Net Total taxes/charges only')
            if frappe.db.get_value('Account', tax.account_head, 'company') != self.company:
                frappe.throw('Tax / charge accounts must belong to the seller company')

    def validate_schedule(self):
        old = self.get_doc_before_save()
        if old and old.docstatus == 1 and old.holiday_calendar_snapshot:
            self.holiday_calendar_snapshot = old.holiday_calendar_snapshot
            holiday = frappe._dict(frappe.parse_json(self.holiday_calendar_snapshot))
            holiday.holidays = [frappe._dict(row) for row in holiday.holidays]
        else:
            calendar = frappe.get_doc('Holiday List', self.holiday_list)
            holiday = frappe._dict(name=calendar.name,from_date=str(calendar.from_date),to_date=str(calendar.to_date),
                holidays=[frappe._dict(holiday_date=str(row.holiday_date),description=row.description) for row in calendar.holidays])
            self.holiday_calendar_snapshot = frappe.as_json(holiday)
        holidays = {getdate(r.holiday_date) for r in holiday.holidays}
        try:
            schedule(self, holidays)
            if self.collection_grace < 0:
                raise ValueError('Collection grace cannot be negative')
            for stamp, evidence, target in [('approval_received','approval_evidence','advance_deadline'),('ready_received','ready_evidence','balance_deadline')]:
                self.set(target, None)
                if self.get(stamp):
                    if not self.get(evidence):
                        raise ValueError('Received notices require reliable written delivery evidence')
                    self.set(target, add_open_hours(self.get(stamp),24,self,holidays,getdate(holiday.from_date),getdate(holiday.to_date)))
            self.collection_deadline = None
            if self.ready_received:
                if self.grace_unit == 'Business hours':
                    self.collection_deadline = add_open_hours(self.ready_received,self.collection_grace,self,holidays,getdate(holiday.from_date),getdate(holiday.to_date))
                else:
                    from zoneinfo import ZoneInfo
                    stamp = datetime.fromisoformat(self.ready_received)
                    self.collection_deadline = datetime.fromtimestamp(stamp.timestamp()+self.collection_grace*3600,ZoneInfo(self.timezone)).isoformat()
        except (ValueError, TypeError) as exc:
            frappe.throw(str(exc))

    def build_order(self):
        order = frappe.new_doc('Sales Order')
        for key in ['customer','company','transaction_date','delivery_date','currency','conversion_rate',
                    'selling_price_list','customer_address','contact_person','incoterm']:
            order.set(key, self.get(key))
        order.order_type = 'Sales'
        order.incoterm_place = self.named_place
        order.ignore_pricing_rule = 1
        order.disable_rounded_total = 1
        order.apply_discount_on = 'Net Total'
        order.discount_amount = self.discount_amount
        for row in self.items:
            order.append('items', dict(item_code=row.item_code, item_name=row.item_name,
                description=row.description, qty=row.qty, uom=row.uom, conversion_factor=row.conversion_factor,
                rate=row.rate, delivery_date=self.delivery_date))
        for tax in self.taxes:
            order.append('taxes', {key:tax.get(key) for key in ['charge_type','account_head','description','rate','tax_amount','cost_center']})
        return order

    def on_submit(self):
        # Native permission checks remain in force. A Sales User cannot mint submitted
        # contracts/Sales Orders, even by calling REST directly.
        order = self.build_order()
        order.insert()
        order.submit()
        if abs(order.grand_total-self.grand_total) > 0.000001:
            frappe.throw('Native Sales Order total changed; review contract arithmetic')
        self.db_set('sales_order', order.name)

    def on_trash(self):
        frappe.throw('Keep saved contracts for the audit trail; cancel or amend instead of deleting')

    def on_cancel(self):
        if self.sales_order:
            order = frappe.get_doc('Sales Order', self.sales_order)
            if order.docstatus == 1:
                # Native permission/link checks block cancellation with active downstream
                # receipts, invoices or deliveries. Everything rolls back together.
                order.cancel()

    def before_update_after_submit(self):
        self.validate_schedule()

    def before_print(self, settings=None):
        if self.is_new() or not frappe.db.exists(self.doctype, self.name):
            frappe.throw('Save the contract before printing')
