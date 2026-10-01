import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = ROOT / "pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.json"
CONTRACT_PY = ROOT / "pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.py"
CONTRACT_JS = ROOT / "pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.js"
DEFAULTS_JSON = ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_defaults/pz_contract_defaults.json"
DEFAULTS_PY = ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_defaults/pz_contract_defaults.py"
TERMS_JSON = ROOT / "pz_sales_contract/terms.json"


def python_constant(path, name):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def js_string_array(source, pattern):
    match = re.search(pattern, source, re.S)
    if not match:
        raise AssertionError(f"JavaScript array not found: {pattern}")
    return re.findall(r'"([a-z_]+)"', match.group(1))


class TestContractFormDefinition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_JSON.read_text())
        cls.defaults = json.loads(DEFAULTS_JSON.read_text())
        cls.javascript = CONTRACT_JS.read_text()
        cls.controller = CONTRACT_PY.read_text()
        cls.default_controller = DEFAULTS_PY.read_text()

    def test_contract_field_order_is_complete_and_unambiguous(self):
        fieldnames = [field["fieldname"] for field in self.contract["fields"]]
        self.assertEqual(len(fieldnames), len(set(fieldnames)))
        self.assertEqual(len(self.contract["field_order"]), len(set(self.contract["field_order"])))
        self.assertEqual(set(self.contract["field_order"]), set(fieldnames))

    def test_checklist_covers_all_required_contract_and_child_fields(self):
        groups = re.search(r"const requiredChecklistGroups = \[(.*?)\n\];", self.javascript, re.S)
        self.assertIsNotNone(groups)
        group_source = groups.group(1)
        top_level_fields = set()
        for field_list in re.findall(r"fields:\s*\[([^\]]*)\]", group_source, re.S):
            top_level_fields.update(re.findall(r'"([a-z_]+)"', field_list))
        tables = set(re.findall(r'table:\s*"([a-z_]+)"', group_source))

        required_fields = {
            field["fieldname"] for field in self.contract["fields"] if field.get("reqd")
        }
        required_tables = {
            field["fieldname"]
            for field in self.contract["fields"]
            if field.get("reqd") and field["fieldtype"] == "Table"
        }
        self.assertEqual(required_fields - required_tables, required_fields & top_level_fields)
        self.assertEqual(required_tables, required_tables & tables)

        item_required = set(js_string_array(
            self.javascript,
            r"function missingItemFields\(row\) \{\s*const required = \[([^\]]*)\]",
        ))
        spec_required = set(js_string_array(
            self.javascript,
            r"function missingSpecificationFields\(rows, items\) \{\s*if \(!rows\.length\) return 1;\s*const required = \[([^\]]*)\]",
        ))
        for doctype, expected in (
            ("pz_sales_contract/sales_contracts/doctype/pz_contract_item/pz_contract_item.json", item_required),
            ("pz_sales_contract/sales_contracts/doctype/pz_contract_specification/pz_contract_specification.json", spec_required),
        ):
            schema = json.loads((ROOT / doctype).read_text())
            required = {field["fieldname"] for field in schema["fields"] if field.get("reqd")}
            self.assertEqual(required, expected, doctype)

    def test_primary_fields_stay_discoverable_and_advanced_sections_collapse(self):
        field_order = self.contract["field_order"]
        for fieldname in ("customer", "company", "transaction_date", "delivery_date", "items", "incoterm", "named_place"):
            self.assertLess(field_order.index(fieldname), field_order.index("customer_details"))
        fields = {field["fieldname"]: field for field in self.contract["fields"]}
        for fieldname in ("payment", "records", "internal"):
            self.assertEqual(fields[fieldname].get("collapsible"), 1)
        for fieldname in ("parties", "commercial", "delivery", "specs"):
            self.assertFalse(fields[fieldname].get("collapsible"))

    def test_company_defaults_are_one_per_company_and_admin_managed(self):
        permissions = self.defaults["permissions"]
        self.assertEqual({permission["role"] for permission in permissions}, {"System Manager"})
        company = next(field for field in self.defaults["fields"] if field["fieldname"] == "company")
        self.assertTrue(company.get("unique"))
        self.assertEqual(self.defaults["autoname"], "field:company")
        self.assertIn('if old and old.company != self.company:', self.default_controller)

    def test_server_and_client_default_fields_match_and_remain_scoped(self):
        server_fields = list(python_constant(DEFAULTS_PY, "COMPANY_DEFAULT_FIELDS"))
        client_fields = js_string_array(self.javascript, r"const companyDefaultFields = \[([^\]]*)\]")
        self.assertEqual(server_fields, client_fields)

        never_default = {
            "customer", "customer_address", "contact_person", "buyer_position", "items", "grade", "qty",
            "rate", "incoterm", "named_place", "specifications", "discount_amount", "taxes",
        }
        self.assertFalse(never_default & set(server_fields))
        self.assertIn("company", self.default_controller)
        self.assertIn('frappe.has_permission("PZ Sales Contract", "create")', self.default_controller)
        self.assertIn('company_doc.check_permission("read")', self.default_controller)
        self.assertIn('self._apply_company_defaults()', self.controller)
        self.assertIn('def _apply_company_defaults(self):', self.controller)
        self.assertIn('if self.amended_from or not self.company:', self.controller)
        self.assertLess(
            self.controller.index('self._apply_company_defaults()'),
            self.controller.index("frappe.db.sql('SELECT name FROM `tabCustomer`"),
        )
        self.assertIn("'PZ Contract Defaults'", self.controller)

    def test_company_change_resets_company_values_without_erasing_customer_deal(self):
        self.assertIn('if (!company || !frm.is_new() || frm.doc.amended_from) return;', self.javascript)
        self.assertIn('if (!frm.is_new() || frm.doc.amended_from) return;', self.javascript)
        self.assertIn('if (frm.is_new() && !frm.doc.amended_from && frm.doc.company) loadCompanyDefaults(frm);', self.javascript)
        self.assertIn('if (frm.is_new() && !frm.doc.amended_from && frm.doc.company && frappe.user.has_role("System Manager"))', self.javascript)
        self.assertIn('frappe.db.exists("PZ Contract Defaults", company).then((exists) => {', self.javascript)
        self.assertIn('if (exists) frappe.set_route("Form", "PZ Contract Defaults", company);', self.javascript)
        self.assertIn('else frappe.new_doc("PZ Contract Defaults", { company });', self.javascript)
        self.assertIn('const clear = Object.fromEntries([...companyDefaultFields, "seller_address_display"].map((fieldname) => [fieldname, null]));', self.javascript)
        self.assertIn('const initialZeroGrace = fieldname === "collection_grace"', self.javascript)
        self.assertIn('frm._pzCollectionGraceTouchedCompany !== company', self.javascript)
        self.assertIn('frm._pzCollectionGraceTouchedCompany = frm.doc.company;', self.javascript)
        self.assertIn('frm._pzCollectionGraceTouchedCompany = null;', self.javascript)
        self.assertIn('if (previousCompany && previousCompany !== currentCompany) clearCompanySpecificValues(frm);', self.javascript)
        self.assertNotIn('"customer_address"', js_string_array(
            self.javascript,
            r"const companyDefaultFields = \[([^\]]*)\]",
        ))

    def test_specific_company_and_customer_handlers_override_checklist_refresh(self):
        form_handler = re.search(
            r'frappe\.ui\.form\.on\("PZ Sales Contract", \{(.*?)\n\}\);',
            self.javascript,
            re.S,
        )
        self.assertIsNotNone(form_handler)
        source = form_handler.group(1)
        checklist_position = source.index("...registerChecklistEvents()")
        customer_position = source.index("customer(frm)")
        company_position = source.index("company(frm)")
        self.assertLess(checklist_position, customer_position)
        self.assertLess(checklist_position, company_position)
        self.assertIn("frm.set_value({ customer_address: null, contact_person: null });", source)
        self.assertIn("clearCompanySpecificValues(frm)", source)
        self.assertIn("loadCompanyDefaults(frm, currentCompany)", source)

    def test_all_15_print_clauses_are_preserved(self):
        clauses = json.loads(TERMS_JSON.read_text())
        self.assertEqual(len(clauses), 15)
        for number, clause in enumerate(clauses, start=1):
            self.assertTrue(clause.startswith(f"{number}. "))
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        self.assertIn("clauses[start:end]", template)
        self.assertIn("[(0,8),(8,15)]", template)


if __name__ == "__main__":
    unittest.main()
