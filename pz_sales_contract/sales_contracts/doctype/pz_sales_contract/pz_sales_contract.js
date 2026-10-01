const companyDefaultFields = [
  "seller_address",
  "seller_signatory",
  "seller_position",
  "currency",
  "conversion_rate",
  "selling_price_list",
  "delivery_arrangement",
  "transport_responsibility",
  "insurance_responsibility",
  "measurement_basis",
  "timezone",
  "business_days",
  "opens_at",
  "closes_at",
  "holiday_list",
  "notice_channel",
  "collection_grace",
  "grace_unit",
  "collection_arrangement",
  "delay_charges",
  "penalty_basis_cap",
  "cure_period",
  "latent_claim_period",
  "force_majeure_threshold",
  "governing_law",
  "courts",
  "bank_receiving_account",
  "cash_receiving_account",
  "beneficiary",
  "bank_branch",
  "account_iban",
  "swift_reference",
];

const currencyDependentDefaultFields = [
  "conversion_rate",
  "selling_price_list",
  "bank_receiving_account",
  "cash_receiving_account",
  "beneficiary",
  "bank_branch",
  "account_iban",
  "swift_reference",
];

const bankInstructionDefaultFields = ["beneficiary", "bank_branch", "account_iban", "swift_reference"];

function ensureCompanyDefaultsDocument(frm) {
  // Desk reuses one Form instance for every document of this DocType.
  if (frm._pzCompanyDefaultsDocument === frm.doc) return;
  frm._pzCompanyDefaultsDocument = frm.doc;
  frm._pzCompanyDefaultsRequestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
  frm._pzCompanyDefaultsLoadedFor = null;
  frm._pzCompanyDefaultsRequestedFor = null;
  frm._pzCompanyDefaultsCurrencyMismatchFor = null;
  frm._pzCompanyDefaultsConfiguredCurrency = null;
  frm._pzCompanyDefaultsConfiguredBank = null;
  frm._pzCompanyDefaultsHasCurrencyDependentDefaults = false;
  frm._pzCompanyDefaultsAppliedValues = {};
  frm._pzCompanyDefaultTouchedFields = new Set();
  frm._pzCompanyDefaultObservedValues = Object.fromEntries(
    currencyDependentDefaultFields.map((fieldname) => [fieldname, frm.doc[fieldname]])
  );
  frm._pzCollectionGraceTouchedCompany = null;
  frm._pzLastSelectedCompany = frm.doc.company || null;
  frm._pzApplyingCompanyDefaults = false;
  frm._pzClearingCompanySpecificValues = false;
}

function isCurrentDefaultsRequest(frm, doc, company, requestId) {
  return frm.doc === doc && frm.is_new() && !doc.amended_from
    && doc.company === company && requestId === frm._pzCompanyDefaultsRequestId;
}

async function setCurrentDocumentValues(frm, values, isCurrent) {
  // set_value(object) runs field events asynchronously. Recheck before every
  // field so navigating during an event cannot write into the next document.
  for (const [fieldname, value] of Object.entries(values)) {
    if (!isCurrent()) return;
    await frm.set_value(fieldname, value);
  }
}

const requiredChecklistGroups = [
  {
    label: "Customer and dates",
    firstField: "customer",
    fields: ["customer", "company", "transaction_date", "delivery_date"],
  },
  {
    label: "Products and price",
    firstField: "currency",
    fields: ["currency", "conversion_rate", "selling_price_list"],
    table: "items",
  },
  {
    label: "Incoterm and named place",
    firstField: "incoterm",
    fields: ["incoterm", "named_place"],
  },
  {
    label: "Buyer and seller details",
    firstField: "customer_address",
    fields: [
      "customer_address",
      "contact_person",
      "seller_address",
      "seller_signatory",
      "seller_position",
      "buyer_position",
    ],
  },
  {
    label: "Agreed specifications",
    firstField: "specifications",
    table: "specifications",
  },
  {
    label: "Delivery and legal schedule",
    firstField: "delivery_arrangement",
    fields: [
      "delivery_arrangement",
      "transport_responsibility",
      "insurance_responsibility",
      "measurement_basis",
      "timezone",
      "business_days",
      "opens_at",
      "closes_at",
      "holiday_list",
      "notice_channel",
      "collection_grace",
      "grace_unit",
      "collection_arrangement",
      "delay_charges",
      "penalty_basis_cap",
      "cure_period",
      "latent_claim_period",
      "force_majeure_threshold",
      "governing_law",
      "courts",
    ],
  },
  {
    label: "Verified payment instructions",
    firstField: "bank_receiving_account",
    fields: ["bank_receiving_account", "beneficiary", "bank_branch", "account_iban", "swift_reference"],
  },
];

function isMissingValue(fieldname, value) {
  if (value === undefined || value === null || value === "") return true;
  if (fieldname === "conversion_rate") return Number(value) <= 0;
  if (fieldname === "collection_grace") return Number(value) < 0;
  return false;
}

function showCompanyCurrencyMismatch(configuredCurrency, contractCurrency) {
  frappe.show_alert({
    message: configuredCurrency && contractCurrency
      ? __("Company defaults use {0}, but this contract uses {1}. Matching price-list, exchange-rate and receiving-account defaults were not copied. Choose a matching currency, price list, exchange rate and accounts.", [configuredCurrency, contractCurrency])
      : __("Company defaults need a currency before matching price-list, exchange-rate and receiving-account values can be copied. Choose a matching currency, price list, exchange rate and accounts."),
    indicator: "orange",
  });
}

function markCompanyDefaultTouched(frm, fieldname) {
  ensureCompanyDefaultsDocument(frm);
  if (!currencyDependentDefaultFields.includes(fieldname)) return;
  const previous = frm._pzCompanyDefaultObservedValues[fieldname];
  frm._pzCompanyDefaultObservedValues[fieldname] = frm.doc[fieldname];
  // Frappe force-triggers unchanged Link defaults during new-form rendering.
  if (previous === frm.doc[fieldname]
    || frm._pzApplyingCompanyDefaults
    || frm._pzClearingCompanySpecificValues) return;
  frm._pzCompanyDefaultTouchedFields.add(fieldname);
}

function clearCopiedCurrencyDefaults(frm, fields = currencyDependentDefaultFields) {
  ensureCompanyDefaultsDocument(frm);
  const doc = frm.doc, company = doc.company, requestId = frm._pzCompanyDefaultsRequestId;
  const isCurrent = () => isCurrentDefaultsRequest(frm, doc, company, requestId);
  const copied = frm._pzCompanyDefaultsAppliedValues || {};
  const clear = {};
  const clearingValues = {};
  for (const fieldname of fields) {
    if (frm._pzCompanyDefaultTouchedFields.has(fieldname)) continue;
    if (Object.prototype.hasOwnProperty.call(copied, fieldname)
      && frm.doc[fieldname] === copied[fieldname]) {
      clear[fieldname] = null;
      clearingValues[fieldname] = copied[fieldname];
    }
  }
  if (!Object.keys(clear).length) return;
  frm._pzClearingCompanySpecificValues = true;
  return setCurrentDocumentValues(frm, clear, isCurrent).then(() => {
    if (!isCurrent()) return;
    for (const [fieldname, value] of Object.entries(clearingValues)) {
      if (copied[fieldname] === value && frm.doc[fieldname] == null) delete copied[fieldname];
    }
    frm._pzClearingCompanySpecificValues = false;
    if (frm.doc.company && frm._pzCompanyDefaultsCurrencyMismatchFor === frm.doc.company
      && frm.doc.currency === frm._pzCompanyDefaultsConfiguredCurrency) {
      frm._pzCompanyDefaultsCurrencyMismatchFor = null;
      frm._pzCompanyDefaultsLoadedFor = null;
      frm._pzCompanyDefaultsRequestedFor = null;
      loadCompanyDefaults(frm, frm.doc.company);
    }
    renderDailyChecklist(frm);
  }, () => {
    if (!isCurrent()) return;
    frm._pzClearingCompanySpecificValues = false;
    renderDailyChecklist(frm);
  });
}

function isUntouchedFrameworkCurrencyDefault(frm, fieldname) {
  if (frm._pzCompanyDefaultTouchedFields.has(fieldname)) return false;
  const field = frm.fields_dict[fieldname];
  return Boolean(field)
    && field.df.__default_value !== undefined
    && String(frm.doc[fieldname]) === String(field.df.__default_value);
}

function missingItemFields(row) {
  const required = ["item_code", "grade", "packaging", "qty", "uom", "rate", "specification_reference"];
  return required.filter((fieldname) => {
    if (isMissingValue(fieldname, row[fieldname])) return true;
    return ["qty", "rate"].includes(fieldname) && Number(row[fieldname]) <= 0;
  }).length;
}

function missingSpecificationFields(rows, items) {
  if (!rows.length) return 1;
  const required = ["item_code", "property", "test_method", "requirement"];
  let missing = rows.reduce(
    (count, row) => count + required.filter((fieldname) => isMissingValue(fieldname, row[fieldname])).length,
    0
  );
  const specifiedItems = new Set(rows.map((row) => row.item_code).filter(Boolean));
  const soldItems = new Set((items || []).map((row) => row.item_code).filter(Boolean));
  for (const itemCode of soldItems) if (!specifiedItems.has(itemCode)) missing++;
  return missing;
}

function checklistStatus(doc, group) {
  let missing = (group.fields || []).filter((fieldname) => isMissingValue(fieldname, doc[fieldname])).length;
  if (group.table === "items") {
    const rows = doc.items || [];
    missing += rows.length ? rows.reduce((count, row) => count + missingItemFields(row), 0) : 1;
  } else if (group.table === "specifications") {
    missing += missingSpecificationFields(doc.specifications || [], doc.items || []);
  }
  return {
    missing,
    fieldname: missing ? group.firstField : group.firstField,
  };
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function renderDailyChecklist(frm) {
  const field = frm.fields_dict.daily_sales_guide;
  if (!field) return;

  const rows = requiredChecklistGroups.map((group) => ({
    ...group,
    ...checklistStatus(frm.doc, group),
  }));
  const incomplete = rows.filter((row) => row.missing > 0);
  const missingTotal = incomplete.reduce((total, row) => total + row.missing, 0);
  const summary = missingTotal
    ? `${missingTotal} required detail${missingTotal === 1 ? "" : "s"} still need attention`
    : "All required contract fields are filled";
  const checklist = rows.map((row) => {
    const status = row.missing ? `${row.missing} to complete` : "Complete";
    const color = row.missing ? "text-warning" : "text-success";
    return `<li style="margin:3px 0"><button type="button" class="btn btn-default btn-xs pz-checklist-target" data-fieldname="${escapeHTML(row.firstField)}" style="width:100%;text-align:left"><span>${escapeHTML(row.label)}</span><span class="pull-right ${color}">${escapeHTML(status)}</span></button></li>`;
  }).join("");
  const html = `<div class="alert alert-info pz-contract-checklist" role="status" aria-live="polite"><p style="margin-bottom:6px"><strong>Daily sales flow</strong> <span class="text-muted">${escapeHTML(summary)}</span></p><p style="margin-bottom:8px">Start with the customer, dates, products and price, then choose the Incoterm and named place. Select a checklist item to jump to its details. Advanced terms remain required unless configured defaults have filled them.</p><ul class="list-unstyled" style="margin:0">${checklist}</ul><p class="text-muted" style="margin:8px 0 0">Company defaults are copied into blank fields on new contracts only; confirm every value for this deal. Changing Company clears its seller, account and term values. Existing contracts keep their saved terms.</p></div>`;

  field.$wrapper.html(html);
  field.$wrapper.off("click.pzContractChecklist").on("click.pzContractChecklist", ".pz-checklist-target", (event) => {
    const fieldname = $(event.currentTarget).attr("data-fieldname");
    if (fieldname) frm.scroll_to_field(fieldname, false);
  });
}

function loadCompanyDefaults(frm, expectedCompany, requestId) {
  ensureCompanyDefaultsDocument(frm);
  const company = expectedCompany || frm.doc.company;
  if (!company || !frm.is_new() || frm.doc.amended_from) return;
  const doc = frm.doc;
  if (requestId === undefined) {
    if (frm._pzCompanyDefaultsLoadedFor === company || frm._pzCompanyDefaultsRequestedFor === company) return;
    requestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
    frm._pzCompanyDefaultsRequestId = requestId;
  }
  frm._pzCompanyDefaultsRequestedFor = company;
  const isCurrent = () => isCurrentDefaultsRequest(frm, doc, company, requestId);

  frappe.call({
    method: "pz_sales_contract.sales_contracts.doctype.pz_contract_defaults.pz_contract_defaults.get_company_defaults",
    args: { company },
    callback(response) {
      if (!isCurrent()) return;
      frm._pzCompanyDefaultsLoadedFor = company;
      const configured = response.message || {};
      const values = {};
      const currencyCompatible = !isMissingValue("currency", configured.currency)
        && (isMissingValue("currency", frm.doc.currency) || frm.doc.currency === configured.currency);
      frm._pzCompanyDefaultsCurrencyMismatchFor = currencyCompatible ? null : company;
      frm._pzCompanyDefaultsConfiguredCurrency = configured.currency || null;
      frm._pzCompanyDefaultsConfiguredBank = configured.bank_receiving_account || null;
      const usesProfileBank = Boolean(configured.bank_receiving_account) && (
        isMissingValue("bank_receiving_account", doc.bank_receiving_account)
        || doc.bank_receiving_account === configured.bank_receiving_account
        || isUntouchedFrameworkCurrencyDefault(frm, "bank_receiving_account")
      );
      frm._pzCompanyDefaultsHasCurrencyDependentDefaults = currencyDependentDefaultFields.some(
        (fieldname) => !isMissingValue(fieldname, configured[fieldname])
      );
      if (frm._pzCompanyDefaultsHasCurrencyDependentDefaults && !currencyCompatible) {
        showCompanyCurrencyMismatch(configured.currency, frm.doc.currency);
      }
      for (const fieldname of companyDefaultFields) {
        const dependent = currencyDependentDefaultFields.includes(fieldname);
        const replaceFrameworkDefault = dependent && frm._pzCompanyDefaultsHasCurrencyDependentDefaults
          && isUntouchedFrameworkCurrencyDefault(frm, fieldname);
        if (dependent && !currencyCompatible) {
          if (replaceFrameworkDefault) values[fieldname] = null;
          continue;
        }
        if (bankInstructionDefaultFields.includes(fieldname) && !usesProfileBank) {
          if (replaceFrameworkDefault) values[fieldname] = null;
          continue;
        }
        if (replaceFrameworkDefault && !isMissingValue(fieldname, configured[fieldname])) {
          values[fieldname] = configured[fieldname];
          continue;
        }
        const initialZeroGrace = fieldname === "collection_grace"
          && Number(frm.doc[fieldname]) === 0
          && frm._pzCollectionGraceTouchedCompany !== company;
        if ((isMissingValue(fieldname, frm.doc[fieldname])
          || (fieldname === "collection_grace" && initialZeroGrace))
          && !isMissingValue(fieldname, configured[fieldname])) {
          values[fieldname] = configured[fieldname];
        }
      }
      if (Object.keys(values).length) {
        frm._pzApplyingCompanyDefaults = true;
        setCurrentDocumentValues(frm, values, isCurrent).then(() => {
          if (!isCurrent()) return;
          const applied = Object.fromEntries(Object.entries(values).filter(
            ([fieldname, value]) => frm.doc[fieldname] === value
          ));
          frm._pzCompanyDefaultsAppliedValues = Object.assign(
            {}, frm._pzCompanyDefaultsAppliedValues || {}, applied
          );
          frm._pzApplyingCompanyDefaults = false;
          renderDailyChecklist(frm);
        }, () => {
          if (!isCurrent()) return;
          frm._pzApplyingCompanyDefaults = false;
          renderDailyChecklist(frm);
        });
      } else renderDailyChecklist(frm);
    },
    error() {
      if (!isCurrent()) return;
      frm._pzCompanyDefaultsLoadedFor = company;
      frappe.show_alert({
        message: __("Company defaults were not loaded. You can still enter and validate all required details manually."),
        indicator: "orange",
      });
      renderDailyChecklist(frm);
    },
  });
}

function clearCompanySpecificValues(frm) {
  ensureCompanyDefaultsDocument(frm);
  if (!frm.is_new() || frm.doc.amended_from) return;
  const doc = frm.doc;
  const requestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
  frm._pzCompanyDefaultsRequestId = requestId;
  frm._pzCompanyDefaultsLoadedFor = null;
  frm._pzCompanyDefaultsRequestedFor = null;
  frm._pzCompanyDefaultsCurrencyMismatchFor = null;
  frm._pzCompanyDefaultsConfiguredCurrency = null;
  frm._pzCompanyDefaultsConfiguredBank = null;
  frm._pzCompanyDefaultsHasCurrencyDependentDefaults = false;
  frm._pzCompanyDefaultsAppliedValues = {};
  frm._pzCompanyDefaultTouchedFields = new Set();
  const company = frm.doc.company;
  const isCurrent = () => isCurrentDefaultsRequest(frm, doc, company, requestId);
  const clear = Object.fromEntries([...companyDefaultFields, "seller_address_display"].map((fieldname) => [fieldname, null]));
  frm._pzCollectionGraceTouchedCompany = null;
  frm._pzClearingCompanySpecificValues = true;
  return setCurrentDocumentValues(frm, clear, isCurrent).then(() => {
    if (!isCurrent()) return;
    frm._pzClearingCompanySpecificValues = false;
    if (frm.doc.company === company && requestId === frm._pzCompanyDefaultsRequestId) {
      loadCompanyDefaults(frm, company, requestId);
    }
    renderDailyChecklist(frm);
  }, () => {
    if (!isCurrent()) return;
    frm._pzClearingCompanySpecificValues = false;
    renderDailyChecklist(frm);
  });
}

function registerChecklistEvents() {
  const fields = requiredChecklistGroups.flatMap((group) => group.fields || []);
  for (const group of requiredChecklistGroups) if (group.table) fields.push(group.table);
  fields.push("customer", "company", ...companyDefaultFields);
  return Object.fromEntries([...new Set(fields)].map((fieldname) => [fieldname, (frm) => {
    markCompanyDefaultTouched(frm, fieldname);
    renderDailyChecklist(frm);
  }]));
}

frappe.ui.form.on("PZ Sales Contract", {
  ...registerChecklistEvents(),
  setup(frm) {
    ensureCompanyDefaultsDocument(frm);
    frm.set_query("customer_address", () => ({ query: "frappe.contacts.doctype.address.address.address_query", filters: { link_doctype: "Customer", link_name: frm.doc.customer } }));
    frm.set_query("seller_address", () => ({ query: "frappe.contacts.doctype.address.address.address_query", filters: { link_doctype: "Company", link_name: frm.doc.company } }));
    frm.set_query("contact_person", () => ({ query: "frappe.contacts.doctype.contact.contact.contact_query", filters: { link_doctype: "Customer", link_name: frm.doc.customer } }));
    frm.set_query("item_code", "items", () => ({ filters: { disabled: 0, is_sales_item: 1 } }));
    frm.set_query("bank_receiving_account", () => ({ filters: { company: frm.doc.company, account_type: "Bank", is_group: 0, disabled: 0 } }));
    frm.set_query("cash_receiving_account", () => ({ filters: { company: frm.doc.company, account_type: "Cash", is_group: 0, disabled: 0 } }));
    frm.set_query("selling_price_list", () => ({ filters: { enabled: 1, selling: 1 } }));
  },
  onload(frm) { ensureCompanyDefaultsDocument(frm); },
  refresh(frm) {
    ensureCompanyDefaultsDocument(frm);
    frm.set_intro("The first contract family saved using this app carries DRAFT until the full 30% advance has qualifying bank reconciliation or agreed cash receipt evidence. Finance can register verified prior contracts through PZ Customer History. ERP submission is separate. Save before printing.");
    renderDailyChecklist(frm);
    if (frm.is_new() && !frm.doc.amended_from && frm.doc.company) loadCompanyDefaults(frm);
    if (frm.is_new() && !frm.doc.amended_from && frm.doc.company && frappe.user.has_role("System Manager")) {
      frm.add_custom_button("Company Contract Defaults", () => {
        const company = frm.doc.company;
        frappe.db.get_value("PZ Contract Defaults", { company }, "name").then((response) => {
          if (frm.doc.company !== company) return;
          const name = response.message && response.message.name;
          if (name) frappe.set_route("Form", "PZ Contract Defaults", name);
          else frappe.new_doc("PZ Contract Defaults", { company });
        }).catch(() => frappe.show_alert({
          message: __("Could not check Company Contract Defaults. Please try again."),
          indicator: "orange",
        }));
      }, __("Setup"));
    }
    if (!frm.is_new()) frm.add_custom_button("Advance evidence", () => {
      frappe.call({ method: "pz_sales_contract.payments.get_status", args: { name: frm.doc.name }, callback(r) {
        const s = r.message;
        frappe.msgprint({ title: "Server payment evidence", message: `${s.payment_draft ? "DRAFT — advance pending" : "Advance confirmed / established or later contract"}<br>Confirmed receipt allocation: ${format_currency(s.confirmed, frm.doc.currency, s.currency_precision)}<br>Required advance: ${format_currency(s.required, frm.doc.currency, s.currency_precision)}<br>ERP status: ${["Unsubmitted", "Submitted", "Cancelled"][frm.doc.docstatus]}` });
      } });
    });
  },
  customer(frm) {
    frm.set_value({ customer_address: null, contact_person: null });
    renderDailyChecklist(frm);
  },
  company(frm) {
    ensureCompanyDefaultsDocument(frm);
    const previousCompany = frm._pzLastSelectedCompany || null;
    const currentCompany = frm.doc.company || null;
    frm._pzLastSelectedCompany = currentCompany;
    if (previousCompany && previousCompany !== currentCompany) clearCompanySpecificValues(frm);
    else loadCompanyDefaults(frm, currentCompany);
    renderDailyChecklist(frm);
  },
  currency(frm) {
    ensureCompanyDefaultsDocument(frm);
    renderDailyChecklist(frm);
    if (!frm.is_new() || frm.doc.amended_from || !frm.doc.company
      || frm._pzApplyingCompanyDefaults || frm._pzClearingCompanySpecificValues) return;
    if (frm._pzCompanyDefaultsConfiguredCurrency
      && frm.doc.currency !== frm._pzCompanyDefaultsConfiguredCurrency) {
      frm._pzCompanyDefaultsCurrencyMismatchFor = frm.doc.company;
      if (frm._pzCompanyDefaultsHasCurrencyDependentDefaults) {
        showCompanyCurrencyMismatch(frm._pzCompanyDefaultsConfiguredCurrency, frm.doc.currency);
      }
      clearCopiedCurrencyDefaults(frm);
      return;
    }
    if (frm._pzCompanyDefaultsCurrencyMismatchFor === frm.doc.company
      && frm.doc.currency === frm._pzCompanyDefaultsConfiguredCurrency) {
      frm._pzCompanyDefaultsCurrencyMismatchFor = null;
      frm._pzCompanyDefaultsLoadedFor = null;
      frm._pzCompanyDefaultsRequestedFor = null;
      loadCompanyDefaults(frm, frm.doc.company);
    }
  },
  bank_receiving_account(frm) {
    markCompanyDefaultTouched(frm, "bank_receiving_account");
    renderDailyChecklist(frm);
    if (!frm.is_new() || frm.doc.amended_from
      || frm._pzApplyingCompanyDefaults || frm._pzClearingCompanySpecificValues) return;
    if (frm._pzCompanyDefaultsConfiguredBank
      && frm.doc.bank_receiving_account !== frm._pzCompanyDefaultsConfiguredBank) {
      return clearCopiedCurrencyDefaults(frm, bankInstructionDefaultFields);
    }
  },
  collection_grace(frm) {
    ensureCompanyDefaultsDocument(frm);
    if (!frm._pzApplyingCompanyDefaults && !frm._pzClearingCompanySpecificValues && frm.doc.company) {
      frm._pzCollectionGraceTouchedCompany = frm.doc.company;
    }
    renderDailyChecklist(frm);
  },
  items_add(frm) { renderDailyChecklist(frm); },
  items_remove(frm) { renderDailyChecklist(frm); },
  specifications_add(frm) { renderDailyChecklist(frm); },
  specifications_remove(frm) { renderDailyChecklist(frm); },
});

frappe.ui.form.on("PZ Contract Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.item_code) frappe.db.get_value("Item", row.item_code, ["item_name", "description", "stock_uom"], (r) => {
      frappe.model.set_value(cdt, cdn, { item_name: r.item_name, description: r.description, uom: r.stock_uom });
    });
    renderDailyChecklist(frm);
  },
  grade(frm) { renderDailyChecklist(frm); },
  packaging(frm) { renderDailyChecklist(frm); },
  qty(frm) { renderDailyChecklist(frm); },
  uom(frm) { renderDailyChecklist(frm); },
  rate(frm) { renderDailyChecklist(frm); },
  specification_reference(frm) { renderDailyChecklist(frm); },
});

frappe.ui.form.on("PZ Contract Specification", {
  item_code(frm) { renderDailyChecklist(frm); },
  property(frm) { renderDailyChecklist(frm); },
  test_method(frm) { renderDailyChecklist(frm); },
  requirement(frm) { renderDailyChecklist(frm); },
});
