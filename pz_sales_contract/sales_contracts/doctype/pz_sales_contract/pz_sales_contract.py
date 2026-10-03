from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from pz_sales_contract.calendar import add_open_hours, schedule
from pz_sales_contract.contract_terms import snapshot_for_new_contract
from pz_sales_contract.sales_contracts.doctype.pz_contract_defaults.pz_contract_defaults import (
    COMPANY_DEFAULT_FIELDS,
    get_allowed_contract_incoterms,
)

ITEM_ONLY_DRAFT_SO_SCOPE = 'item-only-draft-so-v1'

CURRENCY_DEPENDENT_DEFAULT_FIELDS = frozenset({
    'conversion_rate',
    'selling_price_list',
    'bank_receiving_account',
    'cash_receiving_account',
    'beneficiary',
    'bank_branch',
    'account_iban',
    'swift_reference',
})

BANK_INSTRUCTION_DEFAULT_FIELDS = frozenset({
    'beneficiary', 'bank_branch', 'account_iban', 'swift_reference',
})

HISTORICAL_CONTRACT_FIELDS = (
    'delivery_arrangement', 'transport_responsibility', 'insurance_responsibility',
    'measurement_basis', 'timezone', 'business_days', 'opens_at', 'closes_at',
    'holiday_list', 'holiday_calendar_snapshot', 'notice_channel', 'collection_grace',
    'grace_unit', 'collection_arrangement', 'delay_charges', 'penalty_basis_cap',
    'cure_period', 'latent_claim_period', 'force_majeure_threshold', 'governing_law',
    'courts', 'approval_received', 'approval_evidence', 'advance_deadline',
    'ready_received', 'ready_evidence', 'balance_deadline', 'collection_deadline',
)


def grade_snapshot(grade):
    """Use the configured Grade code, falling back to its canonical Link name."""
    meta = frappe.get_meta('Bitumen Grade')
    code = grade.get('grade_code') if meta.has_field('grade_code') else None
    return code or grade.name


class PZSalesContract(Document):
    def _set_defaults(self):
        # Frappe may apply generic user defaults while an amendment is created.
        # Restore blank agreement values so creating an amendment never rewrites
        # the cancelled contract from current user defaults.
        initially_blank = {}
        initially_blank_currency_dependent = set()
        initially_blank_historical = set()
        if self.is_new():
            initially_blank_historical = {
                fieldname for fieldname in HISTORICAL_CONTRACT_FIELDS
                if self.get(fieldname) in (None, '')
            }
        if self.is_new() and self.amended_from:
            for fieldname in COMPANY_DEFAULT_FIELDS:
                value = self.get(fieldname)
                if value in (None, '') or (fieldname == 'conversion_rate' and value == 0):
                    initially_blank[fieldname] = value
        elif self.is_new():
            for fieldname in CURRENCY_DEPENDENT_DEFAULT_FIELDS:
                value = self.get(fieldname)
                if value in (None, '') or (fieldname == 'conversion_rate' and value == 0):
                    initially_blank_currency_dependent.add(fieldname)

        super()._set_defaults()
        self._pz_initially_blank_currency_dependent_defaults = initially_blank_currency_dependent

        if self.amended_from:
            for fieldname, value in initially_blank.items():
                self.set(fieldname, value)
        for fieldname in initially_blank_historical:
            self.set(fieldname, None)

    def before_insert(self):
        self._apply_company_defaults()
        # Customer row lock serialises simultaneous first inserts across all companies.
        frappe.db.sql('SELECT name FROM `tabCustomer` WHERE name=%s FOR UPDATE', self.customer)
        if self.amended_from:
            original = frappe.get_doc(self.doctype, self.amended_from)
            original.check_permission('read')
            original.check_permission('amend')
            if original.docstatus != 2 or original.customer != self.customer or original.company != self.company:
                frappe.throw('Amendments require a cancelled contract with the same customer and company')
            self.first_family = original.first_family
            # Amendments retain the source contract's delivery/tax lifecycle.
            self.contract_scope_version = original.get('contract_scope_version')
        else:
            original = None
            self.first_family = frappe.generate_hash(length=20)
            self.contract_scope_version = ITEM_ONLY_DRAFT_SO_SCOPE
            # New contracts never accept hidden legacy schedule data through
            # Desk defaults, imports, or REST payloads.
            self.delivery_date = None
            self.set('taxes', [])
            self.tax_total = 0
        # Pin the exact clauses used by this contract. Amendments retain the
        # source contract's clause version; historical records without a saved
        # snapshot use the immutable first-version copy when printed.
        self.terms_snapshot = snapshot_for_new_contract(original)
        # A locking current read is essential here: ordinary exists() can read
        # an earlier REPEATABLE READ snapshot even after waiting for Customer.
        reservation = frappe.db.sql('SELECT name, first_family FROM `tabPZ Contract Registry` WHERE customer=%s FOR UPDATE',self.customer)
        if reservation and not reservation[0][1]:
            frappe.db.set_value('PZ Contract Registry',reservation[0][0],'first_family',self.first_family)
        if not reservation:
            frappe.get_doc(dict(doctype='PZ Contract Registry', customer=self.customer,
                first_family=self.first_family)).insert(ignore_permissions=True)

    def _apply_company_defaults(self):
        # Copy configured company values into blanks on creation only. The saved
        # contract remains its own snapshot if the defaults are changed later.
        # Amendments must preserve the cancelled agreement they replace.
        if self.amended_from or not self.company:
            return
        defaults = frappe.db.get_value(
            'PZ Contract Defaults', {'company': self.company}, list(COMPANY_DEFAULT_FIELDS), as_dict=True
        )
        if not defaults:
            return
        # Currency, exchange rate, price list and receiving instructions form one
        # compatibility bundle. Never let a seller's USD bundle become a partial
        # mismatch on a contract whose native/user currency is already INR.
        configured_currency = defaults.get('currency')
        if not self.get('currency') and configured_currency:
            self.currency = configured_currency
        contract_currency = self.get('currency')
        currency_matches = bool(configured_currency) and contract_currency == configured_currency
        initially_blank = getattr(self, '_pz_initially_blank_currency_dependent_defaults', set())
        configured_bundle = any(
            defaults.get(fieldname) not in (None, '')
            and not (fieldname == 'conversion_rate' and defaults.get(fieldname) == 0)
            for fieldname in CURRENCY_DEPENDENT_DEFAULT_FIELDS
        )

        def compatible_injected_value(fieldname, value):
            if not value or not contract_currency:
                return True
            if fieldname == 'selling_price_list':
                price_list = frappe.db.get_value(
                    'Price List', value, ['currency', 'enabled', 'selling'], as_dict=True
                )
                return bool(
                    price_list and price_list.currency == contract_currency
                    and price_list.enabled and price_list.selling
                )
            if fieldname in {'bank_receiving_account', 'cash_receiving_account'}:
                account = frappe.db.get_value(
                    'Account', value,
                    ['company', 'account_type', 'is_group', 'disabled', 'account_currency'],
                    as_dict=True,
                )
                account_currency = (account.account_currency if account else None) or frappe.db.get_value(
                    'Company', self.company, 'default_currency'
                )
                expected_kind = 'Bank' if fieldname == 'bank_receiving_account' else 'Cash'
                return bool(
                    account and account.company == self.company and account.account_type == expected_kind
                    and not account.is_group and not account.disabled and account_currency == contract_currency
                )
            return True

        # A generic Frappe default may have filled a dependent field after the
        # input was constructed. It is replaceable only when that input field
        # was blank. Explicit link values stay authoritative and are validated.
        explicit_dependency_conflict = False
        if configured_bundle and currency_matches:
            for fieldname in CURRENCY_DEPENDENT_DEFAULT_FIELDS - initially_blank:
                value = self.get(fieldname)
                if not value or fieldname == 'conversion_rate':
                    continue
                if fieldname in {'selling_price_list', 'bank_receiving_account', 'cash_receiving_account'} \
                    and not compatible_injected_value(fieldname, value):
                    explicit_dependency_conflict = True
                    break

        if configured_bundle and (not currency_matches or explicit_dependency_conflict):
            # Do not retain unrelated generic FX/list/account defaults beside
            # a mismatched configured bundle. Only values captured as blank
            # input are cleared; explicit payload values are left for strict
            # validation to accept or reject.
            for fieldname in initially_blank:
                self.set(fieldname, None)

        # Instructions identify a particular bank, not just a currency. A
        # deliberate alternate bank needs its own complete instructions.
        profile_bank = defaults.get('bank_receiving_account')
        uses_profile_bank = bool(profile_bank) and (
            self.bank_receiving_account == profile_bank
            or not self.bank_receiving_account
            or 'bank_receiving_account' in initially_blank
        )
        for fieldname in COMPANY_DEFAULT_FIELDS:
            if fieldname in CURRENCY_DEPENDENT_DEFAULT_FIELDS:
                if not configured_bundle:
                    continue
                if not currency_matches or explicit_dependency_conflict:
                    continue
                if fieldname in BANK_INSTRUCTION_DEFAULT_FIELDS and not uses_profile_bank:
                    if fieldname in initially_blank:
                        self.set(fieldname, None)
                    continue
                if fieldname in initially_blank:
                    configured_value = defaults.get(fieldname)
                    if fieldname == 'conversion_rate' and configured_value == 0:
                        configured_value = None
                    if configured_value not in (None, ''):
                        self.set(fieldname, configured_value)
                    elif not compatible_injected_value(fieldname, self.get(fieldname)):
                        self.set(fieldname, None)
                    continue
            blank = self.get(fieldname) in (None, '') or (
                fieldname == 'conversion_rate' and self.get(fieldname) == 0
            )
            configured_value = defaults.get(fieldname)
            if fieldname == 'conversion_rate' and configured_value == 0:
                configured_value = None
            if blank and configured_value not in (None, ''):
                self.set(fieldname, configured_value)

    def validate(self):
        old = self.get_doc_before_save()
        if old:
            for key in ['customer', 'company', 'first_family', 'sales_order', 'amended_from', 'contract_scope_version']:
                if self.get(key) != old.get(key):
                    frappe.throw(f'{key} cannot be changed after creation')
            if self.terms_snapshot != old.terms_snapshot:
                frappe.throw('The contract terms snapshot cannot be changed after creation')
        elif self.is_new():
            # Reject forged readonly internal values from REST/import as well as Desk.
            self.sales_order = None
        if self.uses_item_only_draft_order():
            # A new-scope contract ignores forged values for hidden legacy
            # fields. Taxes and delivery date are completed on its linked SO.
            self.delivery_date = None
            self.set('taxes', [])
            self.tax_total = 0
        elif not self.delivery_date:
            frappe.throw('Legacy contracts require their saved planned delivery date')
        self.validate_links_and_snapshots(old)
        self.validate_schedule()
        self.validate_incoterm(old)
        order = self.build_order()
        order.set_missing_values()
        order.calculate_taxes_and_totals()
        order.set_total_in_words()
        if order.grand_total <= 0 or self.discount_amount < 0 or self.discount_amount > order.total:
            frappe.throw('Contract total must be positive and discount within subtotal')
        self.subtotal = order.total
        self.tax_total = order.total_taxes_and_charges
        self.grand_total = order.grand_total
        precision = self.precision('advance_required')
        if precision is None:
            precision = 2
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

    def validate_links_and_snapshots(self, old=None):
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
        if not self.conversion_rate or self.conversion_rate <= 0 or (currency == self.currency and self.conversion_rate != 1):
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
        self.validate_grade_masters(old)
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
        for tax in self.taxes:
            if tax.charge_type not in ['Actual', 'On Net Total'] or tax.included_in_print_rate or (tax.rate or 0) < 0 or (tax.tax_amount or 0) < 0:
                frappe.throw('This version supports additional Actual or On Net Total taxes/charges only')
            if frappe.db.get_value('Account', tax.account_head, 'company') != self.company:
                frappe.throw('Tax / charge accounts must belong to the seller company')

    def validate_grade_masters(self, old=None, require_active=False):
        historical = old
        if not historical and self.amended_from:
            historical = frappe.get_doc('PZ Sales Contract', self.amended_from)
            historical.check_permission('read')

        def previous_line(row):
            if not historical:
                return None
            return next((previous for previous in historical.items
                if previous.name == row.name
                or (previous.idx == row.idx and previous.item_code == row.item_code)), None)

        grade_doctype_exists = bool(frappe.db.exists('DocType', 'Bitumen Grade'))
        sales_order_grade_field_exists = frappe.get_meta('Sales Order Item').has_field('custom_bitumen_grade')
        for row in self.items:
            previous = previous_line(row)
            unchanged_snapshot = bool(
                previous and previous.item_code == row.item_code
                and previous.grade_master == row.grade_master
                and previous.grade == row.grade
            )
            unchanged_saved_link = bool(old and unchanged_snapshot)
            if row.grade_master:
                if not grade_doctype_exists:
                    if unchanged_saved_link and not require_active:
                        row.grade_master = None
                        continue
                    frappe.throw('The Bitumen Grade master is unavailable; select an installed Grade master before saving new Grade links')
                if not frappe.db.exists('Bitumen Grade', row.grade_master):
                    if unchanged_saved_link and not require_active:
                        row.grade_master = None
                        continue
                    frappe.throw(f'Bitumen Grade {row.grade_master} no longer exists; choose an active Grade master')
                grade = frappe.get_doc('Bitumen Grade', row.grade_master)
                grade.check_permission('read')
                if grade.get('disabled'):
                    if unchanged_saved_link and not require_active:
                        continue
                    frappe.throw(f'Bitumen Grade {row.grade_master} is disabled; choose an active Grade master')
                if not sales_order_grade_field_exists:
                    frappe.throw('Sales Order Item custom_bitumen_grade is required to map contract line Grades')
                if not unchanged_snapshot:
                    row.grade = grade_snapshot(grade)
                continue

            if require_active and previous and previous.grade_master:
                frappe.throw('The saved Bitumen Grade link is unavailable; restore an active Grade master before submitting this contract')
            if not row.grade or not previous or previous.item_code != row.item_code or previous.grade != row.grade:
                frappe.throw('Choose a Bitumen Grade master for each new contract line; existing free-text Grade snapshots are retained for history')

    def validate_incoterm(self, old=None):
        if old and old.incoterm == self.incoterm:
            return
        allowed = set(get_allowed_contract_incoterms(self.company))
        if self.amended_from:
            original = frappe.get_doc('PZ Sales Contract', self.amended_from)
            original.check_permission('read')
            if original.incoterm:
                allowed.add(original.incoterm)
        if self.incoterm not in allowed:
            frappe.throw('Choose EXW, FOB, CIF, or an Incoterm enabled for this seller company')
        incoterm = frappe.get_doc('Incoterm', self.incoterm)
        incoterm.check_permission('read')

    def validate_schedule(self):
        required_inputs = (
            'timezone', 'business_days', 'opens_at', 'closes_at', 'holiday_list',
            'collection_grace', 'grace_unit',
        )
        if any(self.get(fieldname) in (None, '') for fieldname in required_inputs):
            # These fields remain as historical contract data, but the Desk form
            # no longer requires a new schedule or an approval/ready record.
            return
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
        fields = ['customer','company','transaction_date','currency','conversion_rate',
                  'selling_price_list','customer_address','contact_person','incoterm']
        if not self.uses_item_only_draft_order():
            fields.insert(3, 'delivery_date')
        for key in fields:
            order.set(key, self.get(key))
        order.order_type = 'Sales'
        order.named_place = self.named_place
        order.ignore_pricing_rule = 1
        order.disable_rounded_total = 1
        order.apply_discount_on = 'Net Total'
        order.discount_amount = self.discount_amount
        for row in self.items:
            item = dict(item_code=row.item_code, item_name=row.item_name,
                description=row.description, qty=row.qty, uom=row.uom, conversion_factor=row.conversion_factor,
                rate=row.rate)
            if not self.uses_item_only_draft_order():
                item['delivery_date'] = self.delivery_date
            if row.grade_master:
                item['custom_bitumen_grade'] = row.grade_master
            order.append('items', item)
        if not self.uses_item_only_draft_order():
            for tax in self.taxes:
                order.append('taxes', {key:tax.get(key) for key in ['charge_type','account_head','description','rate','tax_amount','cost_center']})
        return order

    def uses_item_only_draft_order(self):
        return self.get('contract_scope_version') == ITEM_ONLY_DRAFT_SO_SCOPE

    def on_submit(self):
        # Native permission checks remain in force. A Sales User cannot mint submitted
        # contracts/Sales Orders, even by calling REST directly.
        self.validate_grade_masters(self.get_doc_before_save(), require_active=True)
        order = self.build_order()
        if self.uses_item_only_draft_order():
            # ERPNext requires Delivery Date to insert a Sales Order, even
            # though the user is meant to provide that value after this step.
            # Bypass that one insert-time check, then immediately turn the
            # native bypass back off. The order remains Draft and a later save
            # or submit still requires a real user-entered delivery date.
            order.skip_delivery_note = 1
        order.insert()
        if self.uses_item_only_draft_order():
            order.db_set('skip_delivery_note', 0, update_modified=False)
            order.skip_delivery_note = 0
        else:
            order.submit()
        total_to_compare = order.net_total if self.uses_item_only_draft_order() else order.grand_total
        if abs(total_to_compare-self.grand_total) > 0.000001:
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
            elif order.docstatus == 0:
                # A cancelled contract must not leave a manually submittable
                # linked draft Sales Order behind. Use native delete permission;
                # failure rolls the contract cancellation back as one transaction.
                order.check_permission('delete')
                reference = order.name
                frappe.delete_doc('Sales Order', reference)
                self.db_set('cancelled_sales_order_reference', reference)
                self.db_set('sales_order', None)

    def before_update_after_submit(self):
        self.validate_schedule()

    def before_print(self, settings=None):
        if self.is_new() or not frappe.db.exists(self.doctype, self.name):
            frappe.throw('Save the contract before printing')


def validate_item_only_sales_order_before_submit(doc, method=None):
    """Keep manually completed new-scope Sales Orders within their contract."""
    contract_name = frappe.db.get_value('PZ Sales Contract', {'sales_order': doc.name}, 'name')
    if not contract_name:
        return
    contract = frappe.get_doc('PZ Sales Contract', contract_name)
    if contract.get('contract_scope_version') != ITEM_ONLY_DRAFT_SO_SCOPE:
        return
    contract.check_permission('read')
    if contract.docstatus != 1 or contract.sales_order != doc.name:
        frappe.throw('The linked contract must be submitted before this Sales Order')
    if doc.get('skip_delivery_note') or not doc.get('delivery_date'):
        frappe.throw('Enter the delivery date on the Sales Order before submitting it')

    immutable_fields = (
        'customer', 'company', 'transaction_date', 'currency', 'conversion_rate',
        'selling_price_list', 'customer_address', 'contact_person', 'incoterm', 'named_place',
    )
    for fieldname in immutable_fields:
        if doc.get(fieldname) != contract.get(fieldname):
            frappe.throw(f'Sales Order {fieldname} must match the linked contract')
    if doc.order_type != 'Sales' or doc.apply_discount_on != 'Net Total':
        frappe.throw('Sales Order type and discount basis must match the linked contract')
    if Decimal(str(doc.discount_amount or 0)) != Decimal(str(contract.discount_amount or 0)):
        frappe.throw('Sales Order discount must match the linked contract')

    if len(doc.items) != len(contract.items):
        frappe.throw('Sales Order product lines must match the linked contract')
    for sales_item, contract_item in zip(doc.items, contract.items, strict=True):
        values = (
            sales_item.item_code == contract_item.item_code,
            Decimal(str(sales_item.qty or 0)) == Decimal(str(contract_item.qty or 0)),
            sales_item.uom == contract_item.uom,
            Decimal(str(sales_item.conversion_factor or 0)) == Decimal(str(contract_item.conversion_factor or 0)),
            Decimal(str(sales_item.rate or 0)) == Decimal(str(contract_item.rate or 0)),
            sales_item.get('custom_bitumen_grade') == contract_item.get('grade_master'),
        )
        if not all(values):
            frappe.throw('Sales Order product, Grade, quantity, UOM, and rate must match the linked contract')

    doc.calculate_taxes_and_totals()
    if abs(Decimal(str(doc.net_total or 0)) - Decimal(str(contract.grand_total or 0))) > Decimal('0.000001'):
        frappe.throw('Sales Order discounted item total must match the linked contract; review item discounts')
