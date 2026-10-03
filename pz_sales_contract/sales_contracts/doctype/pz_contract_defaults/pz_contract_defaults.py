import frappe
from frappe.model.document import Document


DEFAULT_CONTRACT_INCOTERMS = ("EXW", "FOB", "CIF")


COMPANY_DEFAULT_FIELDS = (
    "seller_address",
    "seller_signatory",
    "seller_position",
    "currency",
    "conversion_rate",
    "selling_price_list",
    "bank_receiving_account",
    "cash_receiving_account",
    "beneficiary",
    "bank_branch",
    "account_iban",
    "swift_reference",
)


class PZContractDefaults(Document):
    def validate(self):
        if not self.company:
            return

        old = self.get_doc_before_save()
        if old and old.company != self.company:
            frappe.throw("Company is fixed for this defaults record; create one record for each Company")

        company = frappe.get_doc("Company", self.company)
        company.check_permission("read")
        company_currency = company.default_currency

        if self.seller_address:
            address = frappe.get_doc("Address", self.seller_address)
            address.check_permission("read")
            if not any(
                link.link_doctype == "Company" and link.link_name == self.company
                for link in address.links
            ):
                frappe.throw("Seller address default must be linked to the selected Company")

        if self.conversion_rate not in (None, "", 0) and self.conversion_rate <= 0:
            frappe.throw("Default exchange rate must be positive")
        if self.currency and self.currency == company_currency and self.conversion_rate not in (None, "", 0, 1):
            frappe.throw("Company-currency contracts must use an exchange rate of 1")

        if self.selling_price_list:
            price_list = frappe.get_doc("Price List", self.selling_price_list)
            price_list.check_permission("read")
            if not price_list.enabled or not price_list.selling:
                frappe.throw("Default selling price list must be enabled and for selling")
            if self.currency and price_list.currency != self.currency:
                frappe.throw("Default selling price list must use the selected default currency")

        seen_incoterms = set()
        for row in self.get("additional_incoterms") or []:
            if row.incoterm in DEFAULT_CONTRACT_INCOTERMS:
                frappe.throw(f"{row.incoterm} is already available by default")
            if row.incoterm in seen_incoterms:
                frappe.throw(f"Incoterm {row.incoterm} is listed more than once")
            seen_incoterms.add(row.incoterm)
            incoterm = frappe.get_doc("Incoterm", row.incoterm)
            incoterm.check_permission("read")

        for fieldname, kind in (("bank_receiving_account", "Bank"), ("cash_receiving_account", "Cash")):
            account_name = self.get(fieldname)
            if not account_name:
                continue
            account = frappe.get_doc("Account", account_name)
            account.check_permission("read")
            if account.company != self.company or account.account_type != kind or account.is_group or account.disabled:
                frappe.throw(f"{fieldname} default must be an enabled seller {kind} ledger account")
            if self.currency and (account.account_currency or company_currency) != self.currency:
                frappe.throw("Default nominated receiving accounts must use the selected default currency")


@frappe.whitelist()
def get_company_defaults(company: str):
    """Return this company's optional, non-secret defaults to a contract creator."""
    if not frappe.has_permission("PZ Sales Contract", "create"):
        frappe.throw("You need permission to create a PZ Sales Contract")
    if not isinstance(company, str):
        frappe.throw("Select a Company by name")

    company_doc = frappe.get_doc("Company", company)
    company_doc.check_permission("read")
    values = frappe.db.get_value("PZ Contract Defaults", {"company": company_doc.name}, list(COMPANY_DEFAULT_FIELDS), as_dict=True)
    if not values:
        return {"allowed_incoterms": get_allowed_contract_incoterms(company_doc.name)}
    result = {
        fieldname: values.get(fieldname)
        for fieldname in COMPANY_DEFAULT_FIELDS
        if values.get(fieldname) not in (None, "")
        and not (fieldname == "conversion_rate" and values.get(fieldname) == 0)
    }
    result["allowed_incoterms"] = get_allowed_contract_incoterms(company_doc.name)
    return result


def get_allowed_contract_incoterms(company: str):
    allowed = list(DEFAULT_CONTRACT_INCOTERMS)
    defaults_name = frappe.db.get_value("PZ Contract Defaults", {"company": company}, "name")
    if defaults_name:
        rows = frappe.get_all(
            "PZ Contract Incoterm",
            filters={
                "parent": defaults_name,
                "parenttype": "PZ Contract Defaults",
                "parentfield": "additional_incoterms",
            },
            fields=["incoterm"],
            order_by="idx asc",
        )
        allowed.extend(row.incoterm for row in rows if row.incoterm)
    return list(dict.fromkeys(allowed))


@frappe.whitelist()
def get_allowed_incoterms(company: str):
    """Return allowed native Incoterm records for a contract Company."""
    if not (frappe.has_permission("PZ Sales Contract", "read")
            or frappe.has_permission("PZ Sales Contract", "create")):
        frappe.throw("You need permission to read PZ Sales Contracts")
    if not isinstance(company, str):
        frappe.throw("Select a Company by name")
    company_doc = frappe.get_doc("Company", company)
    company_doc.check_permission("read")
    return get_allowed_contract_incoterms(company_doc.name)
