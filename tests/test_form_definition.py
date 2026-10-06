import ast
import hashlib
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
CONTRACT_TERMS_PY = ROOT / "pz_sales_contract/contract_terms.py"
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

    def test_print_as_draft_is_manual_and_defaults_off(self):
        field = next(field for field in self.contract["fields"] if field["fieldname"] == "print_as_draft")
        self.assertEqual((field["label"], field["fieldtype"], field["default"]),
            ("Print as Draft", "Check", "0"))
        self.assertTrue(field.get("no_copy"))
        self.assertTrue(field.get("allow_on_submit"))
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        self.assertIn("elif doc.print_as_draft", template)
        self.assertIn("<div class=\"draft\">DRAFT</div>", template)
        for obsolete in ("payment_draft", "FIRST ADVANCE NOT CONFIRMED", "Confirmed receipt allocation"):
            self.assertNotIn(obsolete, template)
        self.assertNotIn("payment_status(doc)", (ROOT / "pz_sales_contract/printing.py").read_text())
        self.assertNotIn("Payment status reflects ERP receipt", template)
        self.assertNotIn("This printout records ERP receipt", template)
        self.assertNotIn("Advance evidence", self.javascript)
        self.assertNotIn("advance has qualifying", self.javascript)

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
            r"function missingItemFields\(row, historicGradeAllowed\) \{\s*const required = \[([^\]]*)\]",
        ))
        item_schema = json.loads((ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_item/pz_contract_item.json").read_text())
        item_required_fields = {field["fieldname"] for field in item_schema["fields"] if field.get("reqd")}
        self.assertEqual(item_required_fields, item_required)
        grade_master = next(field for field in item_schema["fields"] if field["fieldname"] == "grade_master")
        self.assertEqual((grade_master["fieldtype"], grade_master["options"], grade_master.get("in_list_view")),
            ("Link", "Bitumen Grade", 1))
        historical_grade = next(field for field in item_schema["fields"] if field["fieldname"] == "grade")
        self.assertEqual(historical_grade["fieldtype"], "Data")
        self.assertTrue(historical_grade.get("read_only"))
        self.assertIn('required.push("grade_master")', self.javascript)
        self.assertIn('custom_bitumen_grade', self.controller)
        self.assertIn("return code or grade.name", self.controller)
        self.assertIn("meta.has_field('grade_code')", self.controller)
        self.assertIn('gradeMaster, ["disabled"]', self.javascript)
        synthetic_fixtures = (ROOT / "pz_sales_contract/testing.py").read_text()
        self.assertIn("code_field = 'grade_code' if meta.has_field('grade_code') else None", synthetic_fixtures)
        self.assertIn("def require_disposable_test_site():", synthetic_fixtures)
        self.assertIn("not frappe.conf.allow_tests", synthetic_fixtures)
        fixture_setup = synthetic_fixtures.split("def setup_fixtures():", 1)[1].split("\ndef new_customer", 1)[0]
        self.assertIn("require_disposable_test_site()", fixture_setup)

        specification_schema = json.loads((ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_specification/pz_contract_specification.json").read_text())
        specification_required_fields = {
            field["fieldname"] for field in specification_schema["fields"] if field.get("reqd")
        }
        self.assertEqual(specification_required_fields, {"item_code", "property", "test_method", "requirement"})
        self.assertNotIn("specification_reference", item_required_fields)
        self.assertNotIn("specification_reference", item_schema["field_order"])
        historical_reference = next(field for field in item_schema["fields"] if field["fieldname"] == "specification_reference")
        self.assertEqual(historical_reference.get("hidden"), 1)
        self.assertEqual(historical_reference.get("read_only"), 1)

    def test_empty_specifications_do_not_print_an_empty_appendix(self):
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        simplified = template.split("{% if simple_print %}", 1)[1].split("{% else %}", 1)[0]
        legacy = template.split("{% if simple_print %}", 1)[1].split("{% else %}", 1)[1].rsplit("{% endif %}", 1)[0]
        self.assertNotIn("Appendix A", simplified)
        self.assertNotIn("Commercial Schedule", simplified)
        self.assertNotIn("Order and Collection Record", simplified)
        self.assertNotIn("24 business hours", simplified.lower())
        self.assertNotIn("charge", simplified.lower())
        self.assertIn("applicable taxes, if any", simplified.lower())
        self.assertIn("{% if doc.specifications %}<h2>Appendix A · Agreed Product Specification</h2>", legacy)
        self.assertNotIn("No agreed product specifications are recorded", template)
        self.assertNotIn("specification_reference", template)

    def test_contract_terms_are_versioned_with_simplified_active_copy(self):
        snapshot = next(field for field in self.contract["fields"] if field["fieldname"] == "terms_snapshot")
        self.assertEqual((snapshot["fieldtype"], snapshot.get("hidden"), snapshot.get("read_only")), ("Long Text", 1, 1))
        version = next(field for field in self.contract["fields"] if field["fieldname"] == "terms_version")
        self.assertEqual((version["fieldtype"], version.get("hidden"), version.get("read_only")), ("Data", 1, 1))
        frozen_terms = json.loads((ROOT / "pz_sales_contract/terms_versions/v1.json").read_text())
        canonical_v1 = json.dumps(frozen_terms, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(
            hashlib.sha256(canonical_v1.encode("utf-8")).hexdigest(),
            python_constant(CONTRACT_TERMS_PY, "LEGACY_TERMS_V1_SHA256"),
        )
        v2_terms = json.loads((ROOT / "pz_sales_contract/terms_versions/v2.json").read_text())
        canonical_v2 = json.dumps(v2_terms, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(
            hashlib.sha256(canonical_v2.encode("utf-8")).hexdigest(),
            python_constant(CONTRACT_TERMS_PY, "ARCHIVED_TERMS_V2_SHA256"),
        )
        v3_terms = json.loads((ROOT / "pz_sales_contract/terms_versions/v3.json").read_text())
        canonical_v3 = json.dumps(v3_terms, ensure_ascii=False, separators=(",", ":"))
        v3_digest = hashlib.sha256(canonical_v3.encode("utf-8")).hexdigest()
        self.assertEqual(v3_digest, python_constant(CONTRACT_TERMS_PY, "ARCHIVED_TERMS_V3_SHA256"))
        v4_terms = json.loads((ROOT / "pz_sales_contract/terms_versions/v4.json").read_text())
        canonical_v4 = json.dumps(v4_terms, ensure_ascii=False, separators=(",", ":"))
        v4_digest = hashlib.sha256(canonical_v4.encode("utf-8")).hexdigest()
        self.assertEqual(v4_digest, python_constant(CONTRACT_TERMS_PY, "CURRENT_TERMS_V4_SHA256"))
        active_terms = json.loads(TERMS_JSON.read_text())
        self.assertEqual(active_terms, v4_terms)
        self.assertEqual(v4_terms, frozen_terms)
        self.assertNotEqual(v4_terms, v3_terms)
        self.assertEqual(len(active_terms), 15)
        self.assertTrue(all(isinstance(clause, str) for clause in active_terms))
        self.assertNotEqual(active_terms, v2_terms)
        self.assertIn("Commercial Schedule", active_terms[0])
        self.assertIn("24 business hours", active_terms[2])
        self.assertIn("outside those hours", active_terms[3])
        self.assertIn("outside business hours", v3_terms[3])
        self.assertIn("latent defects", active_terms[8])
        self.assertIn("governing-law and court fields", active_terms[14])
        terms_source = CONTRACT_TERMS_PY.read_text()
        self.assertIn("_legacy_terms_snapshot()", terms_source)
        new_contract_path = terms_source.split("def clauses_for_contract", 1)[0]
        self.assertIn("return raw", new_contract_path)
        self.assertIn("CURRENT_TERMS_VERSION", new_contract_path)
        self.assertIn("_snapshot_for_version(original.get('terms_version'))", new_contract_path)
        self.assertIn("clauses_for_contract(doc)", (ROOT / "pz_sales_contract/printing.py").read_text())
        self.assertIn("simple_print = doc.get('terms_version') in SIMPLE_PRINT_TERMS_VERSIONS", (ROOT / "pz_sales_contract/printing.py").read_text())
        self.assertEqual(python_constant(CONTRACT_TERMS_PY, "CURRENT_TERMS_VERSION"), "v4")
        self.assertIn("'v2', 'v3', CURRENT_TERMS_VERSION", terms_source)
        self.assertIn('frm.set_df_property("specifications", "hidden", simplifiedContract)', self.javascript)
        self.assertIn("Product specification rows are not part of the simplified contract version", self.controller)
        review_copy = (ROOT / "docs/contract-print-copy-review.md").read_text()
        self.assertIn("## Exact v4 contract terms", review_copy)
        self.assertIn("The archived v3 list and its digest are unchanged", review_copy)
        self.assertIn("Terms-to-form input gaps", review_copy)

    def test_stamp_is_optional_print_asset_not_a_contract_field(self):
        fieldnames = {field["fieldname"] for field in self.contract["fields"]}
        self.assertNotIn("stamp", fieldnames)
        self.assertNotIn("stamp_image", fieldnames)
        printing = (ROOT / "pz_sales_contract/printing.py").read_text()
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        self.assertIn("def _load_print_stamp(private_files_path):", printing)
        self.assertIn("if not stamp_path.is_file():", printing)
        self.assertIn("frappe.get_site_path('private', 'files')", printing)
        self.assertIn("stamp=_load_print_stamp(frappe.get_site_path('private', 'files'))", printing)
        self.assertIn("{% if stamp %}<td class=\"seller-stamp-cell\"><img class=\"seller-stamp\"", template)
        self.assertIn("Petrol Zone Company stamp", template)

    def test_primary_fields_stay_discoverable_and_advanced_sections_collapse(self):
        field_order = self.contract["field_order"]
        for fieldname in ("customer", "company", "transaction_date", "items", "incoterm", "named_place"):
            self.assertLess(field_order.index(fieldname), field_order.index("customer_details"))
        fields = {field["fieldname"]: field for field in self.contract["fields"]}
        for fieldname in ("delivery_date", "taxes", "tax_total"):
            self.assertEqual(fields[fieldname].get("hidden"), 1)
            self.assertFalse(fields[fieldname].get("reqd"))
        self.assertIn("enter delivery date on the linked Sales Order", fields["delivery_date"].get("description", ""))
        self.assertIn("record applicable taxes on the linked Sales Order", fields["taxes"].get("description", ""))
        for fieldname in ("payment", "records", "internal"):
            self.assertEqual(fields[fieldname].get("collapsible"), 1)
        for fieldname in ("parties", "commercial", "delivery", "specs"):
            self.assertFalse(fields[fieldname].get("collapsible"))

    def test_new_entry_controls_and_packaging_start_hidden_in_doctype_metadata(self):
        contract_fields = {field["fieldname"]: field for field in self.contract["fields"]}
        for fieldname in ("conversion_rate", "selling_price_list"):
            self.assertEqual(contract_fields[fieldname].get("hidden"), 1)
            self.assertFalse(contract_fields[fieldname].get("reqd"))
        self.assertIn('frm.set_df_property(fieldname, "hidden", usdEntry)', self.javascript)

        item_schema = json.loads((ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_item/pz_contract_item.json").read_text())
        packaging = next(field for field in item_schema["fields"] if field["fieldname"] == "packaging")
        self.assertEqual(packaging.get("hidden"), 1)
        self.assertEqual(packaging.get("read_only"), 1)
        self.assertFalse(packaging.get("reqd"))
        self.assertFalse(packaging.get("in_list_view"))
        legacy_required = python_constant(CONTRACT_PY, "LEGACY_REQUIRED_ITEM_FIELDS")
        self.assertNotIn("packaging", legacy_required)

        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        self.assertEqual(template.count("{% if row.packaging %} · {{ row.packaging|e }}{% endif %}"), 2)

    def test_new_scope_policy_keeps_historical_contract_values_and_protects_sales_order(self):
        fields = {field["fieldname"]: field for field in self.contract["fields"]}
        for fieldname in ("contract_scope_version", "cancelled_sales_order_reference"):
            self.assertEqual(fields[fieldname].get("hidden"), 1)
            self.assertTrue(fields[fieldname].get("read_only"))
        self.assertIn("ITEM_ONLY_DRAFT_SO_SCOPE", self.controller)
        self.assertIn("validate_item_only_sales_order_before_submit", (ROOT / "pz_sales_contract/hooks.py").read_text())
        self.assertIn("clear_default_taxes_on_initial_item_only_sales_order", (ROOT / "pz_sales_contract/hooks.py").read_text())
        self.assertIn("order.skip_delivery_note = 1", self.controller)
        self.assertIn("order.db_set('skip_delivery_note', 0", self.controller)
        self.assertIn("if order.docstatus == 0", self.controller)
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        self.assertIn("if not is_item_only_draft", template)
        self.assertIn("not included in this contract total", template)
        self.assertIn("doc.print_as_draft", template)
        self.assertNotIn("LINKED SALES ORDER DRAFT", template)
        self.assertNotIn("payment_draft", template)

    def test_company_defaults_are_one_per_company_and_admin_managed(self):
        permissions = self.defaults["permissions"]
        self.assertEqual({permission["role"] for permission in permissions}, {"System Manager"})
        company = next(field for field in self.defaults["fields"] if field["fieldname"] == "company")
        self.assertTrue(company.get("unique"))
        self.assertEqual(self.defaults["autoname"], "field:company")
        self.assertIn('if old and old.company != self.company:', self.default_controller)

    def test_incoterm_choices_reuse_native_master_and_company_defaults(self):
        extra = next(field for field in self.defaults["fields"] if field["fieldname"] == "additional_incoterms")
        self.assertEqual(extra["fieldtype"], "Table")
        self.assertEqual(extra["options"], "PZ Contract Incoterm")
        child = json.loads((ROOT / "pz_sales_contract/sales_contracts/doctype/pz_contract_incoterm/pz_contract_incoterm.json").read_text())
        incoterm = next(field for field in child["fields"] if field["fieldname"] == "incoterm")
        self.assertEqual((incoterm["fieldtype"], incoterm["options"]), ("Link", "Incoterm"))
        self.assertIn('DEFAULT_CONTRACT_INCOTERMS = ("EXW", "FOB", "CIF")', self.default_controller)
        self.assertIn('get_allowed_contract_incoterms(self.company)', self.controller)
        self.assertIn('get_allowed_incoterms', self.javascript)
        self.assertIn('defaultContractIncoterms = ["EXW", "FOB", "CIF"]', self.javascript)

    def test_removed_sections_are_optional_hidden_and_keep_their_schema(self):
        fields = {field["fieldname"]: field for field in self.contract["fields"]}
        for fieldname in (
            "delivery_terms", "delivery_arrangement", "transport_responsibility",
            "insurance_responsibility", "measurement_basis", "timezone", "business_days",
            "opens_at", "closes_at", "holiday_list", "holiday_calendar_snapshot",
            "notice_channel", "collection_grace", "grace_unit", "collection_arrangement",
            "delay_charges", "penalty_basis_cap", "cure_period", "latent_claim_period",
            "force_majeure_threshold", "governing_law", "courts", "records",
            "approval_received", "approval_evidence", "advance_deadline", "ready_received",
            "ready_evidence", "balance_deadline", "collection_deadline",
        ):
            self.assertIn(fieldname, fields)
            self.assertEqual(fields[fieldname].get("hidden"), 1, fieldname)
            self.assertFalse(fields[fieldname].get("reqd"), fieldname)
        self.assertEqual(fields["specifications"]["depends_on"], "eval:doc.specifications && doc.specifications.length > 0")
        self.assertNotIn("missingSpecificationFields", self.javascript)
        self.assertNotIn("specification_reference", js_string_array(
            self.javascript,
            r"function missingItemFields\(row, historicGradeAllowed\) \{\s*const required = \[([^\]]*)\]",
        ))

    def test_server_and_client_default_fields_match_and_remain_scoped(self):
        server_fields = list(python_constant(DEFAULTS_PY, "COMPANY_DEFAULT_FIELDS"))
        client_fields = js_string_array(self.javascript, r"const companyDefaultFields = \[([^\]]*)\]")
        self.assertEqual(server_fields, client_fields)

        never_default = {
            "customer", "customer_address", "contact_person", "buyer_position", "items", "grade", "qty",
            "rate", "incoterm", "named_place", "specifications", "discount_amount", "taxes",
        }
        self.assertFalse(never_default & set(server_fields))
        hidden_legal_defaults = {
            "delivery_arrangement", "transport_responsibility", "insurance_responsibility",
            "measurement_basis", "timezone", "business_days", "opens_at", "closes_at",
            "holiday_list", "notice_channel", "collection_grace", "grace_unit",
            "collection_arrangement", "delay_charges", "penalty_basis_cap", "cure_period",
            "latent_claim_period", "force_majeure_threshold", "governing_law", "courts",
        }
        self.assertFalse(hidden_legal_defaults & set(server_fields))
        self.assertIn("HISTORICAL_CONTRACT_FIELDS", self.controller)
        self.assertIn("for fieldname in initially_blank_historical:", self.controller)
        self.assertIn("company", self.default_controller)
        self.assertIn('frappe.has_permission("PZ Sales Contract", "create")', self.default_controller)
        self.assertIn('company_doc.check_permission("read")', self.default_controller)
        self.assertIn('self._apply_company_defaults()', self.controller)
        self.assertIn('def _apply_company_defaults(self):', self.controller)
        self.assertIn('if self.amended_from or not self.company:', self.controller)
        set_defaults = re.search(r"    def _set_defaults\(self\):(.*?)\n    def before_insert", self.controller, re.S)
        self.assertIsNotNone(set_defaults)
        self.assertIn('if self.is_new() and self.amended_from:', set_defaults.group(1))
        self.assertLess(set_defaults.group(1).index('initially_blank[fieldname] = value'), set_defaults.group(1).index('super()._set_defaults()'))
        self.assertIn('for fieldname, value in initially_blank.items():', set_defaults.group(1))
        self.assertIn('self.set(fieldname, value)', set_defaults.group(1))
        self.assertIn('initially_blank_currency_dependent.add(fieldname)', set_defaults.group(1))
        self.assertIn('initially_blank_historical = {', set_defaults.group(1))
        self.assertLess(
            set_defaults.group(1).index('initially_blank_historical = {'),
            set_defaults.group(1).index('super()._set_defaults()'),
        )
        self.assertLess(
            set_defaults.group(1).index('initially_blank_currency_dependent.add(fieldname)'),
            set_defaults.group(1).index('super()._set_defaults()'),
        )
        self.assertIn('self._pz_initially_blank_currency_dependent_defaults = initially_blank_currency_dependent', set_defaults.group(1))
        capture_block = set_defaults.group(1).split('initially_blank_currency_dependent = set()', 1)[1].split('super()._set_defaults()', 1)[0]
        self.assertNotIn('"currency"', capture_block)
        self.assertIn('CURRENCY_DEPENDENT_DEFAULT_FIELDS = frozenset({', self.controller)
        self.assertIn('currency_matches = bool(configured_currency) and contract_currency == configured_currency', self.controller)
        self.assertIn('explicit_dependency_conflict = False', self.controller)
        self.assertIn('for fieldname in CURRENCY_DEPENDENT_DEFAULT_FIELDS - initially_blank:', self.controller)
        self.assertIn('if not currency_matches or explicit_dependency_conflict:', self.controller)
        currency_field = next(field for field in self.contract["fields"] if field["fieldname"] == "currency")
        self.assertIn("New contracts use USD", currency_field["description"])
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
        self.assertIn('frappe.db.get_value("PZ Contract Defaults", { company }, "name").then((response) => {', self.javascript)
        self.assertIn('if (name) frappe.set_route("Form", "PZ Contract Defaults", name);', self.javascript)
        self.assertIn('else frappe.new_doc("PZ Contract Defaults", { company });', self.javascript)
        self.assertIn('.filter((fieldname) => !(usesUsdEntry(frm) && fieldname === "currency"))', self.javascript)
        self.assertIn('const currencyCompatible = !isMissingValue("currency", configured.currency)', self.javascript)
        self.assertIn('function isUntouchedFrameworkCurrencyDefault(frm, fieldname)', self.javascript)
        self.assertIn('field.df.__default_value !== undefined', self.javascript)
        self.assertIn('if (replaceFrameworkDefault) values[fieldname] = null;', self.javascript)
        self.assertIn('Choose a matching currency, price list, exchange rate and accounts.', self.javascript)
        self.assertIn('frm._pzCompanyDefaultsCurrencyMismatchFor === frm.doc.company', self.javascript)
        self.assertIn('frm.doc.currency === frm._pzCompanyDefaultsConfiguredCurrency', self.javascript)
        self.assertIn('loadCompanyDefaults(frm, frm.doc.company);', self.javascript)
        self.assertIn('if (doc[fieldname] === value) applied[fieldname] = value;', self.javascript)
        self.assertIn('if (frm._pzCompanyDefaultTouchedFields.has(fieldname)) continue;', self.javascript)
        self.assertIn('if (copied[fieldname] === value && frm.doc[fieldname] == null) delete copied[fieldname];', self.javascript)
        clear_currency_defaults = re.search(r"function clearCopiedCurrencyDefaults\(frm, fields = currencyDependentDefaultFields\) \{(.*?)\n\}", self.javascript, re.S).group(1)
        self.assertLess(clear_currency_defaults.index('setCurrentDocumentValues(frm, clear, isCurrent)'), clear_currency_defaults.index('delete copied[fieldname]'))
        self.assertIn('frm._pzCompanyDefaultsCurrencyMismatchFor === frm.doc.company', clear_currency_defaults)
        self.assertIn('showCompanyCurrencyMismatch(frm._pzCompanyDefaultsConfiguredCurrency, frm.doc.currency);', self.javascript)
        self.assertIn('markCompanyDefaultTouched(frm, fieldname);', self.javascript)
        self.assertNotIn('const initialZeroGrace', self.javascript)
        self.assertNotIn('_pzCollectionGraceTouchedCompany', self.javascript)
        self.assertIn('if (previousCompany && previousCompany !== currentCompany) clearCompanySpecificValues(frm);', self.javascript)
        self.assertNotIn('"customer_address"', js_string_array(
            self.javascript,
            r"const companyDefaultFields = \[([^\]]*)\]",
        ))

    def test_currency_defaults_are_copied_only_as_a_compatible_bundle(self):
        self.assertIn("'selling_price_list',", self.controller)
        self.assertIn("'bank_receiving_account',", self.controller)
        self.assertIn("'cash_receiving_account',", self.controller)
        self.assertIn("'beneficiary',", self.controller)
        self.assertIn("'account_iban',", self.controller)
        self.assertIn('contract_currency = self.get(\'currency\')', self.controller)
        self.assertIn('contract_currency = self.get(\'currency\')', self.controller)
        self.assertIn('currency_matches = bool(configured_currency) and contract_currency == configured_currency', self.controller)
        self.assertIn('const currencyDependentDefaultFields = [', self.javascript)
        self.assertIn('frm.doc.currency === configured.currency', self.javascript)
        self.assertIn('if (isMissingValue(fieldname, frm.doc[fieldname])', self.javascript)

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
        currency_position = source.index("currency(frm)")
        self.assertLess(checklist_position, customer_position)
        self.assertLess(checklist_position, company_position)
        self.assertLess(checklist_position, currency_position)
        self.assertIn('"customer_name", "customer_tax_id", "address_display", "buyer_phone"', source)
        self.assertIn("clearCompanySpecificValues(frm)", source)
        self.assertIn("loadCompanyDefaults(frm, currentCompany)", source)

    def test_all_15_legacy_clauses_remain_in_the_frozen_print(self):
        clauses = json.loads((ROOT / "pz_sales_contract/terms_versions/v1.json").read_text())
        self.assertEqual(len(clauses), 15)
        for number, clause in enumerate(clauses, start=1):
            self.assertTrue(clause.startswith(f"{number}. "))
        template = (ROOT / "pz_sales_contract/templates/contract.html").read_text()
        legacy = template.split("{% if simple_print %}", 1)[1].split("{% else %}", 1)[1]
        self.assertIn("clauses[start:end]", legacy)
        self.assertIn("[(0,8),(8,15)]", legacy)


if __name__ == "__main__":
    unittest.main()
