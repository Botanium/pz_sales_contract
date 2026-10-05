"""User-entered party snapshots, independent of ERP Contact/Address masters."""
import frappe

PAYMENT_INSTRUCTION_FIELDS = {
    'bank_receiving_account': 'Nominated bank receiving account',
    'cash_receiving_account': 'Agreed cash receiving account',
    'beneficiary': 'Account beneficiary',
    'bank_branch': 'Bank / branch',
    'account_iban': 'Currency / account / IBAN',
    'swift_reference': 'SWIFT / payment reference',
}

PARTY_ENTRY_VERSION = 'direct-v1'
PARTY_LINK_FIELDS = ('customer_address', 'seller_address', 'contact_person')
SELLER_DEFAULTS = {
    'seller_name': 'Petrol Zone Company',
    'seller_address_display': 'Arbat-Sulaimani, Iraq',
    'seller_email': 'info@petrol-zone.com',
    'seller_phone': '00964 770 000 3737',
}
PARTY_REQUIRED_FIELDS = {
    'seller_name': 'Seller legal name',
    'seller_address_display': 'Seller address',
    'seller_email': 'Seller email',
    'seller_phone': 'Seller phone',
    'customer_name': 'Customer legal name',
    'address_display': 'Buyer address',
    'buyer_phone': 'Buyer phone',
    'contact_display': 'Buyer representative / signatory name',
    'buyer_position': 'Buyer signatory position',
}


def uses_direct_parties(doc):
    return doc.get('party_entry_version') == PARTY_ENTRY_VERSION


def validate_party_fields(doc):
    if not uses_direct_parties(doc):
        return
    for fieldname in PARTY_LINK_FIELDS:
        doc.set(fieldname, None)
    missing = [label for fieldname, label in PARTY_REQUIRED_FIELDS.items()
        if not str(doc.get(fieldname) or '').strip()]
    if missing:
        frappe.throw('Complete party details: ' + ', '.join(missing), frappe.MandatoryError)
    # The combined buyer field intentionally accepts a phone number alone.
    # Do not apply email-only validation or guess a country/phone format.
