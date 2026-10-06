const defaultContractIncoterms = ["EXW", "FOB", "CIF"];
const defaultAdvancePercentage = 30;
const contractChildLookupStates = new WeakMap();
const partyFields = ["seller_name", "seller_address_display", "seller_email", "seller_phone",
  "customer_name", "address_display", "buyer_phone", "contact_display",
  "buyer_position"];
const sellerTextDefaults = { seller_name: "Petrol Zone Company", seller_address_display: "Arbat-Sulaimani, Iraq",
  seller_email: "info@petrol-zone.com", seller_phone: "00964 770 000 3737" };
function usesDirectParties(frm) {
  return frm.doc.party_entry_version === "direct-v1" || (frm.is_new() && !frm.doc.amended_from);
}

function usesUsdEntry(frm) {
  return frm.doc.entry_policy_version === "usd-location-v1" || (frm.is_new() && !frm.doc.amended_from);
}

function contractChildLookupState(row) {
  let state = contractChildLookupStates.get(row);
  if (!state) {
    state = { itemRequest: 0, itemCode: row.item_code || null, gradeRequest: 0, gradeMaster: null };
    contractChildLookupStates.set(row, state);
  }
  return state;
}

function isCurrentContractItemRow(frm, cdt, cdn, row) {
  return Boolean(locals[cdt] && locals[cdt][cdn] === row
    && (frm.doc.items || []).some((candidate) => candidate.name === cdn));
}

const companyDefaultFields = [
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
const optionalPaymentFields = ["bank_receiving_account", "cash_receiving_account", ...bankInstructionDefaultFields];

function parsedAdvancePercentage(value) {
  if (value === undefined || value === null || value === "") return defaultAdvancePercentage;
  const percentage = Number(value);
  return Number.isFinite(percentage) && percentage >= 0 && percentage <= 100 ? percentage : null;
}

function hasFixedHistoricalSplit(frm) {
  return !(frm.is_new() && !frm.doc.amended_from) && frm.doc.terms_version !== "v5";
}

function percentageLabel(value) {
  return Number(value).toFixed(4).replace(/\.?0+$/, "");
}

function contractMoneyPrecision(frm) {
  const field = frm.get_field?.("advance_required");
  const configured = field?.df?.precision;
  if (configured !== undefined && configured !== null && configured !== "") {
    const precision = Number(configured);
    if (Number.isInteger(precision) && precision >= 0 && precision <= 9) return precision;
  }
  const globalPrecision = Number(frappe.defaults?.get_default?.("currency_precision"));
  return Number.isInteger(globalPrecision) && globalPrecision >= 0 && globalPrecision <= 9
    ? globalPrecision : 2;
}

function roundContractMoney(value, precision) {
  const factor = 10 ** precision;
  const scaled = Number(value) * factor;
  if (!Number.isFinite(scaled)) return null;
  return Math.sign(scaled) * Math.floor(Math.abs(scaled) + 0.5 + Number.EPSILON * Math.abs(scaled)) / factor;
}

function contractTotalForPaymentPreview(frm, precision) {
  const itemOnly = frm.doc.contract_scope_version === "item-only-draft-so-v1"
    || (frm.is_new() && !frm.doc.amended_from);
  if (!itemOnly) {
    const total = Number(frm.doc.grand_total);
    return Number.isFinite(total) ? roundContractMoney(total, precision) : null;
  }
  const subtotal = (frm.doc.items || []).reduce((sum, row) => {
    const quantity = Number(row.qty || 0), rate = Number(row.rate || 0);
    if (!Number.isFinite(quantity) || !Number.isFinite(rate)) return sum;
    return sum + (roundContractMoney(quantity * rate, precision) || 0);
  }, 0);
  const discount = Number(frm.doc.discount_amount || 0);
  if (!Number.isFinite(discount)) return null;
  return roundContractMoney(subtotal - discount, precision);
}

function updatePaymentPreview(frm, rejectInvalid = false) {
  const advancePercentage = hasFixedHistoricalSplit(frm)
    ? defaultAdvancePercentage : parsedAdvancePercentage(frm.doc.advance_percentage);
  if (advancePercentage === null) {
    if (rejectInvalid) frappe.throw(__("Advance percentage must be a finite number from 0 to 100."));
    return;
  }
  const balancePercentage = 100 - advancePercentage;
  frm.set_df_property("advance_required", "label", `Required advance (${percentageLabel(advancePercentage)}%)`);
  frm.set_df_property("balance_required", "label", `Balance (${percentageLabel(balancePercentage)}%)`);
  const precision = contractMoneyPrecision(frm);
  const contractTotal = contractTotalForPaymentPreview(frm, precision);
  if (contractTotal === null) return;
  const advance = roundContractMoney(contractTotal * advancePercentage / 100, precision);
  if (advance === null) return;
  frm.doc.advance_required = advance;
  frm.doc.balance_required = roundContractMoney(contractTotal - advance, precision);
  frm.refresh_field?.("advance_required");
  frm.refresh_field?.("balance_required");
}

function ensureCompanyDefaultsDocument(frm) {
  // Desk reuses one Form, including when revisiting cached unsaved documents.
  if (frm._pzCompanyDefaultsDocument === frm.doc) return;
  const states = frm._pzCompanyDefaultsStates || (frm._pzCompanyDefaultsStates = new WeakMap());
  const previous = states.get(frm._pzCompanyDefaultsDocument);
  if (previous) {
    for (const key of Object.keys(previous)) previous[key] = frm[key];
    if (frm._pzCompanyDefaultsWork.size) {
      previous._pzCompanyDefaultsLoadedFor = null;
    }
  }
  let state = states.get(frm.doc);
  if (!state) {
    state = {
      _pzCompanyDefaultsLoadedFor: null,
      _pzCompanyDefaultsCurrencyMismatchFor: null,
      _pzCompanyDefaultsConfiguredCurrency: null,
      _pzCompanyDefaultsConfiguredBank: null,
      _pzCompanyDefaultsHasCurrencyDependentDefaults: false,
      _pzCompanyDefaultsAppliedValues: {},
      _pzCompanyDefaultsPendingClear: null,
      _pzCompanyDefaultsWork: new Set(),
      _pzCompanyDefaultWrites: {},
      _pzCompanyDefaultEditRevisions: {},
      _pzCompanyDefaultTouchedFields: new Set(),
      _pzCompanyDefaultObservedValues: Object.fromEntries(
        companyDefaultFields.map((fieldname) => [fieldname, frm.doc[fieldname]])
      ),
      _pzContractIncoterms: [...defaultContractIncoterms],
      // Native Duplicate and Quick Entry mark their existing values as prefilled.
      _pzCompanyDefaultsPrefilled: frm.doc.__run_link_triggers === false,
      _pzLastSelectedCompany: frm.doc.company || null,
    };
    states.set(frm.doc, state);
  }
  Object.assign(frm, state);
  frm._pzCompanyDefaultsDocument = frm.doc;
  frm._pzCompanyDefaultsRequestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
  frm._pzCompanyDefaultsRequestedFor = null;
}

async function withCompanyDefaultsWork(frm, run) {
  // Keep the original document's work tracked even if Desk navigates away.
  // A token covers the whole operation, including dependent reconciliation.
  const work = frm._pzCompanyDefaultsWork;
  const operation = {};
  work.add(operation);
  try {
    return await run();
  } finally {
    work.delete(operation);
  }
}

function isCurrentDefaultsRequest(frm, doc, company, requestId) {
  return frm.doc === doc && frm.is_new() && !doc.amended_from
    && doc.company === company && requestId === frm._pzCompanyDefaultsRequestId;
}

async function setCurrentDocumentValues(frm, values, isCurrent, didSet = () => {}) {
  // set_value(object) runs field events asynchronously. Recheck before every
  // field so navigating during an event cannot write into the next document.
  const doc = frm.doc;
  const before = Object.fromEntries(Object.keys(values).map((fieldname) => [fieldname, doc[fieldname]]));
  const writes = frm._pzCompanyDefaultWrites;
  const revisions = frm._pzCompanyDefaultEditRevisions;
  const beforeRevisions = { ...revisions };
  for (const [fieldname, value] of Object.entries(values)) {
    if (!isCurrent()) return;
    // A user can edit a later field while an earlier Link event awaits AJAX.
    if (doc[fieldname] !== before[fieldname]
      || revisions[fieldname] !== beforeRevisions[fieldname]) continue;
    const write = { value };
    writes[fieldname] = write;
    try {
      await frm.set_value(fieldname, value);
      didSet(fieldname, value);
    } finally {
      if (writes[fieldname] === write) delete writes[fieldname];
    }
  }
}

const requiredChecklistGroups = [
  {
    label: "Customer and contract date",
    firstField: "customer",
    fields: ["customer", "company", "transaction_date"],
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
    firstField: "customer_name",
    fields: [
      "seller_signatory",
      "seller_position",
      "buyer_position",
    ],
  },
];

function isMissingValue(fieldname, value) {
  if (value === undefined || value === null || value === "") return true;
  if (fieldname === "conversion_rate") return Number(value) <= 0;
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
  if (!companyDefaultFields.includes(fieldname)) return;
  const previous = frm._pzCompanyDefaultObservedValues[fieldname];
  frm._pzCompanyDefaultObservedValues[fieldname] = frm.doc[fieldname];
  // Frappe force-triggers unchanged Link defaults during new-form rendering.
  // Ignore only our write to this field. A different field (or a different
  // value in this field) can be deliberately edited while its event awaits.
  const write = frm._pzCompanyDefaultWrites[fieldname];
  if (previous === frm.doc[fieldname] || (write && write.value === frm.doc[fieldname])) return;
  frm._pzCompanyDefaultTouchedFields.add(fieldname);
  const revisions = frm._pzCompanyDefaultEditRevisions;
  revisions[fieldname] = (revisions[fieldname] || 0) + 1;
  return true;
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
  return withCompanyDefaultsWork(frm, () => setCurrentDocumentValues(frm, clear, isCurrent).then(() => {
    if (!isCurrent()) return;
    for (const [fieldname, value] of Object.entries(clearingValues)) {
      if (copied[fieldname] === value && frm.doc[fieldname] == null) delete copied[fieldname];
    }
    let next;
    if (frm.doc.company && frm._pzCompanyDefaultsCurrencyMismatchFor === frm.doc.company
      && frm.doc.currency === frm._pzCompanyDefaultsConfiguredCurrency) {
      frm._pzCompanyDefaultsCurrencyMismatchFor = null;
      frm._pzCompanyDefaultsLoadedFor = null;
      frm._pzCompanyDefaultsRequestedFor = null;
      next = loadCompanyDefaults(frm, frm.doc.company);
    }
    renderDailyChecklist(frm);
    // A user may have changed currency during a bank-only clear (or vice
    // versa). Reconcile again before releasing this operation's save barrier.
    return next || reconcileCopiedCompanyDefaults(frm);
  }, () => {
    if (!isCurrent()) return;
    renderDailyChecklist(frm);
  }));
}

function isUntouchedFrameworkCurrencyDefault(frm, fieldname) {
  if (frm._pzCompanyDefaultsPrefilled) return false;
  if (frm._pzCompanyDefaultTouchedFields.has(fieldname)) return false;
  const field = frm.fields_dict[fieldname];
  return Boolean(field)
    && field.df.__default_value !== undefined
    && String(frm.doc[fieldname]) === String(field.df.__default_value);
}

function reconcileCopiedCompanyDefaults(frm) {
  if (!frm.is_new() || frm.doc.amended_from) return;
  if (frm._pzCompanyDefaultsConfiguredCurrency
    && frm.doc.currency !== frm._pzCompanyDefaultsConfiguredCurrency) {
    frm._pzCompanyDefaultsCurrencyMismatchFor = frm.doc.company;
    return clearCopiedCurrencyDefaults(frm);
  }
  if (frm._pzCompanyDefaultsConfiguredBank
    && frm.doc.bank_receiving_account !== frm._pzCompanyDefaultsConfiguredBank) {
    return clearCopiedCurrencyDefaults(frm, bankInstructionDefaultFields);
  }
}

function missingItemFields(row, historicGradeAllowed) {
  const required = ["item_code", "qty", "uom", "rate"];
  if (!row.grade_master && !(historicGradeAllowed && row.grade)) required.push("grade_master");
  return required.filter((fieldname) => {
    if (isMissingValue(fieldname, row[fieldname])) return true;
    return ["qty", "rate"].includes(fieldname) && Number(row[fieldname]) <= 0;
  }).length;
}

function checklistStatus(doc, group) {
  const newEntry = doc.entry_policy_version === "usd-location-v1" || (doc.__islocal && !doc.amended_from);
  let fields = group.fields || [];
  if (group.firstField === "customer_name" && (doc.party_entry_version === "direct-v1" || (doc.__islocal && !doc.amended_from))) fields = [...fields, ...partyFields];
  if (newEntry) fields = fields.filter((fieldname) => !["conversion_rate", "selling_price_list", "named_place"].includes(fieldname));
  if (newEntry && group.firstField === "incoterm") fields = [...fields, "contract_location"];
  let missing = [...new Set(fields)].filter((fieldname) => isMissingValue(fieldname, doc[fieldname])).length;
  if (group.table === "items") {
    const rows = doc.items || [];
    const historicGradeAllowed = !doc.__islocal || Boolean(doc.amended_from);
    missing += rows.length ? rows.reduce(
      (count, row) => count + missingItemFields(row, historicGradeAllowed), 0
    ) : 1;
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
  const html = `<div class="alert alert-info pz-contract-checklist" role="status" aria-live="polite"><p style="margin-bottom:6px"><strong>Daily sales flow</strong> <span class="text-muted">${escapeHTML(summary)}</span></p><p style="margin-bottom:8px">Start with the customer, dates, products and price, then choose the Incoterm and named place. Select a checklist item to jump to its details.</p><ul class="list-unstyled" style="margin:0">${checklist}</ul><p class="text-muted" style="margin:8px 0 0">Company defaults are copied into blank fields on new contracts only; confirm every value for this deal. Changing Company clears its seller and account values. Existing contracts keep their saved terms.</p></div>`;

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
  // A suspended Company change must finish clearing its old seller snapshot
  // before any new profile can be requested or applied.
  if (frm._pzCompanyDefaultsPendingClear) return;
  const doc = frm.doc;
  if (requestId === undefined) {
    if (frm._pzCompanyDefaultsLoadedFor === company || frm._pzCompanyDefaultsRequestedFor === company) return;
    requestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
    frm._pzCompanyDefaultsRequestId = requestId;
  }
  frm._pzCompanyDefaultsRequestedFor = company;
  const isCurrent = () => isCurrentDefaultsRequest(frm, doc, company, requestId);

  return withCompanyDefaultsWork(frm, () => new Promise((resolve) => {
    let responseHandled = false;
    const finishWithoutDefaults = () => {
      if (responseHandled) return;
      responseHandled = true;
      resolve();
      if (!isCurrent()) return;
      frm._pzCompanyDefaultsLoadedFor = company;
      frappe.show_alert({
        message: __("Company defaults were not loaded. You can still enter and validate all required details manually."),
        indicator: "orange",
      });
      renderDailyChecklist(frm);
    };
    frappe.call({
      method: "pz_sales_contract.sales_contracts.doctype.pz_contract_defaults.pz_contract_defaults.get_company_defaults",
      args: { company },
      callback(response) {
        if (responseHandled) return;
        responseHandled = true;
        resolve((async () => {
          if (!isCurrent()) return;
          frm._pzCompanyDefaultsLoadedFor = company;
          const configured = response.message || {};
          frm._pzContractIncoterms = [...new Set([
            ...defaultContractIncoterms,
            ...(Array.isArray(configured.allowed_incoterms) ? configured.allowed_incoterms : []),
          ])];
          if (doc.incoterm && !frm._pzContractIncoterms.includes(doc.incoterm)) {
            await frm.set_value("incoterm", null);
            if (!isCurrent()) return;
            frappe.show_alert({
              message: __("Choose an Incoterm allowed for the selected company."),
              indicator: "orange",
            });
          }
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
            if (fieldname === "seller_address") continue;
            // A user-cleared optional field must survive a late defaults response.
            if (optionalPaymentFields.includes(fieldname)
              && frm._pzCompanyDefaultTouchedFields.has(fieldname)) continue;
            if (usesUsdEntry(frm) && ["currency", "conversion_rate", "selling_price_list"].includes(fieldname)) continue;
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
            if (isMissingValue(fieldname, frm.doc[fieldname])
              && !isMissingValue(fieldname, configured[fieldname])) {
              values[fieldname] = configured[fieldname];
            }
          }
          if (Object.keys(values).length) {
            const applied = frm._pzCompanyDefaultsAppliedValues;
            await setCurrentDocumentValues(frm, values, isCurrent, (fieldname, value) => {
              // Keep provenance even if a field event navigated to another form.
              if (doc[fieldname] === value) applied[fieldname] = value;
            }).then(() => {
              if (!isCurrent()) return;
              const next = reconcileCopiedCompanyDefaults(frm);
              renderDailyChecklist(frm);
              return next;
            }, () => {
              if (!isCurrent()) return;
              renderDailyChecklist(frm);
            });
          } else renderDailyChecklist(frm);
        })());
      },
      error: finishWithoutDefaults,
      // Frappe handles some server errors (including deadlocks/timeouts)
      // without calling error. Final completion must still settle that fetch.
      // Once callback owns the application promise, always must not release it.
      always: finishWithoutDefaults,
    });
  }));
}

function loadContractIncoterms(frm) {
  const company = frm.doc.company;
  if (!company || (frm.is_new() && !frm.doc.amended_from)) return;
  const doc = frm.doc;
  const requestId = (frm._pzContractIncotermsRequestId || 0) + 1;
  frm._pzContractIncotermsRequestId = requestId;
  frappe.call({
    method: "pz_sales_contract.sales_contracts.doctype.pz_contract_defaults.pz_contract_defaults.get_allowed_incoterms",
    args: { company },
    callback(response) {
      if (frm.doc !== doc || frm.doc.company !== company
        || frm._pzContractIncotermsRequestId !== requestId) return;
      const configured = Array.isArray(response.message) ? response.message : [];
      frm._pzContractIncoterms = [...new Set([...defaultContractIncoterms, ...configured])];
    },
  });
}

function clearCompanySpecificValues(frm) {
  ensureCompanyDefaultsDocument(frm);
  if (!frm.is_new() || frm.doc.amended_from) return;
  const doc = frm.doc;
  const clear = Object.fromEntries([...companyDefaultFields]
    .filter((fieldname) => !(usesUsdEntry(frm) && fieldname === "currency"))
    .map((fieldname) => [fieldname, null]));
  frm._pzCompanyDefaultsPendingClear = {
    company: doc.company,
    before: Object.fromEntries(Object.keys(clear).map((fieldname) => [fieldname, doc[fieldname]])),
  };
  const requestId = (frm._pzCompanyDefaultsRequestId || 0) + 1;
  frm._pzCompanyDefaultsRequestId = requestId;
  frm._pzCompanyDefaultsLoadedFor = null;
  frm._pzCompanyDefaultsRequestedFor = null;
  frm._pzCompanyDefaultsCurrencyMismatchFor = null;
  frm._pzCompanyDefaultsConfiguredCurrency = null;
  frm._pzCompanyDefaultsConfiguredBank = null;
  frm._pzCompanyDefaultsHasCurrencyDependentDefaults = false;
  frm._pzCompanyDefaultsAppliedValues = {};
  frm._pzContractIncoterms = [...defaultContractIncoterms];
  frm._pzCompanyDefaultTouchedFields = new Set();
  frm._pzCompanyDefaultEditRevisions = {};
  frm._pzCompanyDefaultWrites = {};
  frm._pzCompanyDefaultObservedValues = { ...frm._pzCompanyDefaultsPendingClear.before };
  return resumeCompanySpecificClear(frm);
}

function resumeCompanySpecificClear(frm) {
  ensureCompanyDefaultsDocument(frm);
  if (!frm.is_new() || frm.doc.amended_from) return;
  const pending = frm._pzCompanyDefaultsPendingClear;
  if (!pending) return;
  if (pending.company !== frm.doc.company) return clearCompanySpecificValues(frm);
  const doc = frm.doc;
  const company = frm.doc.company;
  const requestId = frm._pzCompanyDefaultsRequestId;
  if (pending.requestId === requestId) return pending.promise;
  const isCurrent = () => isCurrentDefaultsRequest(frm, doc, company, requestId)
    && frm._pzCompanyDefaultsPendingClear === pending;
  const clear = {};
  for (const [fieldname, value] of Object.entries(pending.before)) {
    // Retain the original snapshot across navigation. Values entered after
    // the Company change, including edits back to the old value, are explicit.
    if (!frm._pzCompanyDefaultTouchedFields.has(fieldname) && doc[fieldname] === value) {
      clear[fieldname] = null;
    }
  }
  pending.requestId = requestId;
  pending.promise = withCompanyDefaultsWork(frm, () => setCurrentDocumentValues(frm, clear, isCurrent).then(() => {
    if (!isCurrent()) return;
    frm._pzCompanyDefaultsPendingClear = null;
    if (frm.doc.company === company && requestId === frm._pzCompanyDefaultsRequestId) {
      renderDailyChecklist(frm);
      return loadCompanyDefaults(frm, company, requestId);
    }
    renderDailyChecklist(frm);
  }, () => {
    if (!isCurrent()) return;
    pending.requestId = null;
    renderDailyChecklist(frm);
  }));
  return pending.promise;
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
    frm.set_query("incoterm", () => ({ filters: { name: ["in", [...new Set([
      ...(frm._pzContractIncoterms || defaultContractIncoterms),
      ...((!frm.is_new() || frm.doc.amended_from) && frm.doc.incoterm ? [frm.doc.incoterm] : []),
    ])]] } }));
    frm.set_query("item_code", "items", () => ({ filters: { disabled: 0, is_sales_item: 1 } }));
    frm.set_query("grade_master", "items", () => ({ filters: { disabled: 0 } }));
    frm.set_query("contract_location", () => ({ filters: { disabled: 0 } }));
    frm.set_query("cash_receiving_account", () => ({ filters: { company: frm.doc.company, account_type: "Cash", is_group: 0, disabled: 0 } }));
    frm.set_query("selling_price_list", () => ({ filters: { enabled: 1, selling: 1 } }));
  },
  onload(frm) { ensureCompanyDefaultsDocument(frm); },
  async before_save(frm) {
    ensureCompanyDefaultsDocument(frm);
    const advancePercentage = parsedAdvancePercentage(frm.doc.advance_percentage);
    if (advancePercentage === null) frappe.throw(__("Advance percentage must be a finite number from 0 to 100."));
    if (hasFixedHistoricalSplit(frm) && advancePercentage !== defaultAdvancePercentage) {
      frappe.throw(__("Historical contract versions retain their original 30% advance and 70% balance."));
    }
    if (frm.doc.advance_percentage === undefined || frm.doc.advance_percentage === null || frm.doc.advance_percentage === "") {
      frm.doc.advance_percentage = defaultAdvancePercentage;
    }
    updatePaymentPreview(frm);
    if (!frm.is_new() || frm.doc.amended_from) return;
    if (!frm._pzCompanyDefaultsWork.size) {
      // Retry a failed/interrupted clear, or reconcile an edit made during a
      // different field's asynchronous event, before allowing serialization.
      if (frm._pzCompanyDefaultsPendingClear) resumeCompanySpecificClear(frm);
      else reconcileCopiedCompanyDefaults(frm);
    }
    if (frm._pzCompanyDefaultsPendingClear || frm._pzCompanyDefaultsWork.size) {
      frappe.throw(__("Company details are still updating. Wait for the update to finish, check the values, then save again."));
    }
    if (usesUsdEntry(frm) && frm.doc.currency !== "USD") frappe.throw(__("New contracts must use USD."));
    // Always return a promise. A synchronous handler would make ScriptManager
    // wait for unrelated AJAX after this check and reopen the save race.
  },
  refresh(frm) {
    ensureCompanyDefaultsDocument(frm);
    if (hasFixedHistoricalSplit(frm)
      || frm.doc.advance_percentage === undefined || frm.doc.advance_percentage === null || frm.doc.advance_percentage === "") {
      frm.doc.advance_percentage = defaultAdvancePercentage;
      frm.refresh_field?.("advance_percentage");
    }
    updatePaymentPreview(frm);
    const directParties = usesDirectParties(frm);
    for (const field of ["customer_tax_id", "buyer_email_phone", ...optionalPaymentFields]) frm.set_df_property(field, "reqd", false);
    for (const field of partyFields) frm.set_df_property(field, "reqd", directParties || field === "buyer_position");
    if (frm.is_new() && !frm.doc.amended_from && frm._pzPartyDefaultsDoc !== frm.doc) {
      frm._pzPartyDefaultsDoc = frm.doc;
      const values = Object.fromEntries(Object.entries(sellerTextDefaults).filter(([field]) => !frm.doc[field]));
      frm.set_value(values);
    }
    const usdEntry = usesUsdEntry(frm);
    frm.set_df_property("currency", "read_only", usdEntry);
    for (const fieldname of ["conversion_rate", "selling_price_list", "named_place"]) {
      frm.set_df_property(fieldname, "hidden", usdEntry);
    }
    frm.set_df_property("named_place", "reqd", !usdEntry);
    frm.set_df_property("contract_location", "hidden", !usdEntry);
    frm.set_df_property("contract_location", "reqd", usdEntry);
    if (usdEntry && frm.doc.currency !== "USD") frm.set_value("currency", "USD");
    const simplifiedContract = ["v2", "v3", "v4", "v5"].includes(frm.doc.terms_version) || (frm.is_new() && !frm.doc.amended_from);
    const advancePercentageEditable = (frm.is_new() && !frm.doc.amended_from)
      || (frm.doc.terms_version === "v5" && Number(frm.doc.docstatus || 0) === 0 && !frm.doc.amended_from);
    frm.set_df_property("advance_percentage", "read_only", !advancePercentageEditable);
    const displayAdvancePercentage = hasFixedHistoricalSplit(frm)
      ? defaultAdvancePercentage : (parsedAdvancePercentage(frm.doc.advance_percentage) ?? defaultAdvancePercentage);
    frm.set_df_property("advance_required", "label", `Required advance (${percentageLabel(displayAdvancePercentage)}%)`);
    frm.set_df_property("balance_required", "label", `Balance (${percentageLabel(100 - displayAdvancePercentage)}%)`);
    frm.set_df_property("specifications_section", "hidden", simplifiedContract);
    frm.set_df_property("specifications", "hidden", simplifiedContract);
    for (const row of frm.doc.items || []) {
      contractChildLookupState(row).gradeMaster = row.grade_master || null;
    }
    renderDailyChecklist(frm);
    const doc = frm.doc;
    Promise.resolve(resumeCompanySpecificClear(frm)).then(() => {
      if (frm.doc !== doc || frm._pzCompanyDefaultsPendingClear) return;
      return reconcileCopiedCompanyDefaults(frm);
    }).then(() => {
      if (frm.doc !== doc) return;
      if (frm.is_new() && !frm.doc.amended_from && frm.doc.company) loadCompanyDefaults(frm);
      else if (frm.doc.company) loadContractIncoterms(frm);
    });
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
  },
  customer(frm) {
    if (frm.is_new() && !frm.doc.amended_from) {
      frm.set_value(Object.fromEntries(["customer_name", "customer_tax_id", "address_display", "buyer_phone",
        "contact_display", "buyer_position", "buyer_email_phone"].map((field) => [field, null])));
    }
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
    markCompanyDefaultTouched(frm, "currency");
    renderDailyChecklist(frm);
    if (!frm.is_new() || frm.doc.amended_from || !frm.doc.company
      || frm._pzCompanyDefaultsWork.size) return;
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
  advance_percentage(frm) {
    if (hasFixedHistoricalSplit(frm) && parsedAdvancePercentage(frm.doc.advance_percentage) !== defaultAdvancePercentage) {
      frappe.throw(__("Historical contract versions retain their original 30% advance and 70% balance."));
    }
    updatePaymentPreview(frm, true);
  },
  discount_amount(frm) { updatePaymentPreview(frm); renderDailyChecklist(frm); },
  grand_total(frm) { updatePaymentPreview(frm); },
  bank_receiving_account(frm) {
    markCompanyDefaultTouched(frm, "bank_receiving_account");
    renderDailyChecklist(frm);
    if (!frm.is_new() || frm.doc.amended_from
      || frm._pzCompanyDefaultsWork.size) return;
    if (frm._pzCompanyDefaultsConfiguredBank
      && frm.doc.bank_receiving_account !== frm._pzCompanyDefaultsConfiguredBank) {
      return clearCopiedCurrencyDefaults(frm, bankInstructionDefaultFields);
    }
  },
  collection_grace(frm) {
    renderDailyChecklist(frm);
  },
  contract_location(frm) { renderDailyChecklist(frm); },
  items_add(frm) { updatePaymentPreview(frm); renderDailyChecklist(frm); },
  items_remove(frm) { updatePaymentPreview(frm); renderDailyChecklist(frm); },
  specifications_add(frm) { renderDailyChecklist(frm); },
  specifications_remove(frm) { renderDailyChecklist(frm); },
});

frappe.ui.form.on("PZ Contract Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const state = contractChildLookupState(row);
    const requestId = ++state.itemRequest;
    const itemCode = row.item_code;
    const doc = frm.doc;
    // Product changes cannot carry packaging from the previous product. Clear
    // immediately, even if the new lookup fails or the Item is removed.
    const current = () => frm.doc === doc && isCurrentContractItemRow(frm, cdt, cdn, row)
      && state.itemRequest === requestId && row.item_code === itemCode;
    const previousItem = state.itemCode;
    state.itemCode = itemCode || null;
    if (previousItem !== itemCode) frappe.model.set_value(cdt, cdn, "packaging", null);
    if (!itemCode) {
      frappe.model.set_value(cdt, cdn, { item_name: null, description: null, uom: null });
      renderDailyChecklist(frm);
      return;
    }
    const packagingBeforeLookup = row.packaging;
    const fillPackaging = previousItem !== itemCode || (usesUsdEntry(frm) && !row.packaging);
    frappe.call({ method: "pz_sales_contract.entry_policy.get_item_details", args: { item_code: itemCode }, callback(response) {
      const r = response.message;
      if (!isCurrentContractItemRow(frm, cdt, cdn, row)
        || !current() || !r) return;
      const values = { item_name: r.item_name, description: r.description, uom: r.stock_uom };
      if (fillPackaging && row.packaging === packagingBeforeLookup && r.packaging) values.packaging = r.packaging;
      // Separate writes keep a navigation/item-change event from applying the
      // rest of an obsolete response to a reused child-row name.
      (async () => {
        for (const [fieldname, value] of Object.entries(values)) {
          if (!current()) return;
          if (fieldname === "packaging" && row.packaging !== packagingBeforeLookup) continue;
          await frappe.model.set_value(cdt, cdn, fieldname, value);
        }
      })();
    } });
    renderDailyChecklist(frm);
  },
  grade_master(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const state = contractChildLookupState(row);
    const previousGradeMaster = state.gradeMaster;
    const gradeMaster = row.grade_master || null;
    state.gradeMaster = gradeMaster;
    const requestId = ++state.gradeRequest;
    if (!gradeMaster) {
      if (previousGradeMaster) frappe.model.set_value(cdt, cdn, "grade", null);
      renderDailyChecklist(frm);
      return;
    }
    frappe.db.get_value("Bitumen Grade", gradeMaster, ["disabled"], (r) => {
      if (!isCurrentContractItemRow(frm, cdt, cdn, row)
        || state.gradeRequest !== requestId || row.grade_master !== gradeMaster || !r) return;
      if (r.disabled) {
        frappe.show_alert({ message: __("This Bitumen Grade is disabled. Choose an active Grade."), indicator: "orange" });
        return;
      }
      // The canonical Link name is always available; the server snapshots
      // grade_code when that optional field exists on the master.
      frappe.model.set_value(cdt, cdn, "grade", gradeMaster);
    });
  },
  qty(frm) { updatePaymentPreview(frm); renderDailyChecklist(frm); },
  uom(frm) { renderDailyChecklist(frm); },
  rate(frm) { updatePaymentPreview(frm); renderDailyChecklist(frm); },
  specification_reference(frm) { renderDailyChecklist(frm); },
});

frappe.ui.form.on("PZ Contract Specification", {
  item_code(frm) { renderDailyChecklist(frm); },
  property(frm) { renderDailyChecklist(frm); },
  test_method(frm) { renderDailyChecklist(frm); },
  requirement(frm) { renderDailyChecklist(frm); },
});
