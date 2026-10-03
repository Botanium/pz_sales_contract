"""Explicit defaults for contracts created after the simplified entry cutover."""
import math

import frappe
from frappe.utils import add_days, getdate

ENTRY_POLICY_VERSION = 'usd-location-v1'

# Exact Item IDs observed on the test site; never infer packaging from substrings.
ITEM_PACKAGING = {
    'Bitumen - Bulk': 'Bulk',
    'Bitumen - Drum': 'Drum',
    'Bitumen - Jumbo': 'Jumbo',
    'Bitumen VG30 Bulk': 'Bulk',
    'Bitumen VG30 Drum': 'Drum',
    'Bitumen VG30 Jumbo Bag': 'Jumbo Bag',
    'Bitumen 60/70 Bulk': 'Bulk',
    'Bitumen 60/70 Drum': 'Drum',
    'Bitumen 50/70 Bulk': 'Bulk',
    'Bitumen VG40 Drum': 'Drum',
    'Bitumen 80/100 Drum': 'Drum',
    'Bitumen 70/100 Bulk': 'Bulk',
    'Bitumen 60/70 Jumbo Bag': 'Jumbo Bag',
    'Bitumen 160/220 Bulk': 'Bulk',
    'Bitumen 50/70 Jumbo Bag': 'Jumbo Bag',
    'Bitumen 40/50 Drum': 'Drum',
    'Bitumen 50/70 Drum': 'Drum',
    'Bitumen 40/50 Bulk': 'Bulk',
    'Bitumen 60/70 Jumbo Bag (WS)': 'Jumbo Bag',
    'Bitumen 35/50 Drum': 'Drum',
}


def uses_entry_policy(doc):
    return doc.get('entry_policy_version') == ENTRY_POLICY_VERSION


def apply_item_packaging(item, previous=None):
    if previous and previous.item_code == item.item_code:
        # The stored value is a historical snapshot for an unchanged Item.
        item.packaging = previous.packaging
        return
    # New and changed Items always use the verified Item ID mapping. Unknown
    # Items stay blank; a stale/forged client value is never printed as fact.
    item.packaging = ITEM_PACKAGING.get(item.item_code)


def usd_conversion_rate(company_currency, transaction_date):
    if company_currency == 'USD':
        return 1
    if not company_currency or not transaction_date:
        frappe.throw('Select a Company and contract date before saving')
    # Match ERPNext's stored selling-rate/date/staleness rules. Do not obtain an
    # unreviewed external rate or manufacture 1 for a non-USD accounting ledger.
    settings = frappe.get_cached_doc('Accounts Settings')
    filters = [
        ['date', '<=', getdate(transaction_date)], ['from_currency', '=', 'USD'],
        ['to_currency', '=', company_currency], ['for_selling', '=', 1],
    ]
    if not settings.get('allow_stale'):
        filters.append(['date', '>', add_days(transaction_date, -(settings.get('stale_days') or 0))])
    rates = frappe.get_all('Currency Exchange', filters=filters,
        fields=['exchange_rate'], order_by='date desc', limit=1)
    rate = float(rates[0].exchange_rate) if rates else 0
    if not math.isfinite(rate) or rate <= 0:
        frappe.throw(f'Configure a valid selling Currency Exchange rate from USD to {company_currency} '
            f'for {transaction_date} before saving this contract')
    return rate


def usd_price_list(company):
    configured = frappe.db.get_value('PZ Contract Defaults', {'company': company}, 'selling_price_list')
    if configured:
        price_list = frappe.get_doc('Price List', configured)
        if price_list.currency != 'USD' or not price_list.enabled or not price_list.selling:
            frappe.throw('Company Contract Defaults must select an enabled USD selling price list')
        price_list.check_permission('read')
        return price_list.name
    native_default = frappe.db.get_single_value('Selling Settings', 'selling_price_list')
    if native_default:
        price_list = frappe.get_doc('Price List', native_default)
        if price_list.currency == 'USD' and price_list.enabled and price_list.selling:
            price_list.check_permission('read')
            return price_list.name
    lists = frappe.get_list('Price List', filters={'currency': 'USD', 'selling': 1, 'enabled': 1},
        pluck='name', limit_page_length=2)
    if len(lists) != 1:
        frappe.throw('Configure an enabled USD selling price list in Company Contract Defaults; '
            'the contract does not choose between missing or multiple price lists')
    return lists[0]


def apply_usd_policy(doc, old=None):
    if not uses_entry_policy(doc):
        return
    if doc.currency != 'USD':
        frappe.throw('New contracts must use USD')
    if old and doc.selling_price_list != old.selling_price_list:
        frappe.throw('selling_price_list is managed by the contract and cannot be edited')
    if old and old.company == doc.company and getdate(old.transaction_date) == getdate(doc.transaction_date):
        # Saved accounting values are snapshots, not live master defaults.
        for field in ('conversion_rate', 'selling_price_list'):
            if doc.get(field) != old.get(field):
                frappe.throw(f'{field} is managed by the contract and cannot be edited')
        return
    company = frappe.get_doc('Company', doc.company)
    company.check_permission('read')
    doc.conversion_rate = usd_conversion_rate(company.default_currency, doc.transaction_date)
    doc.selling_price_list = old.selling_price_list if old else usd_price_list(doc.company)


@frappe.whitelist()
def get_item_details(item_code):
    if not (frappe.has_permission('PZ Sales Contract', 'read')
            or frappe.has_permission('PZ Sales Contract', 'create')):
        frappe.throw('You need permission to read PZ Sales Contracts')
    item = frappe.get_doc('Item', item_code)
    item.check_permission('read')
    if item.disabled or not item.is_sales_item:
        frappe.throw('Choose an enabled sales Item')
    return {key: item.get(key) for key in ('item_name', 'description', 'stock_uom')} | {
        'packaging': ITEM_PACKAGING.get(item.name),
    }


def validate_location(doc, old=None):
    if not uses_entry_policy(doc):
        return
    unchanged = old and old.get('contract_location') == doc.get('contract_location')
    if unchanged and old.get('named_place'):
        doc.named_place = old.named_place
        return
    if not doc.get('contract_location'):
        frappe.throw('Select an Incoterm location, or ask a Contract Manager to add one')
    location = frappe.get_doc('PZ Contract Location', doc.contract_location)
    location.check_permission('read')
    if location.disabled:
        frappe.throw('Choose an enabled Incoterm location')
    doc.named_place = location.location_name


def ensure_starter_locations():
    """Install requested choices once; never overwrite a manager's edits."""
    for key, name in (('PZ-LOC-BANDAR-ABBAS', 'Bandar Abbas'), ('PZ-LOC-MERSIN', 'Mersin, Turkey')):
        if not frappe.db.exists('PZ Contract Location', key) and not frappe.db.exists(
                'PZ Contract Location', {'location_name': name}):
            frappe.get_doc({'doctype': 'PZ Contract Location', 'location_name': name}).insert(
                ignore_permissions=True, set_name=key)
