const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname,
  "../pz_sales_contract/sales_contracts/doctype/pz_sales_contract/pz_sales_contract.js"), "utf8");
const profile = {
  currency: "USD", conversion_rate: 1, selling_price_list: "USD Prices",
  seller_signatory: "Approved Seller", bank_receiving_account: "Bank A",
  beneficiary: "Beneficiary A", bank_branch: "Branch A", account_iban: "Account A",
  swift_reference: "Reference A", seller_position: "Approved Position",
  governing_law: "Approved Terms", allowed_incoterms: ["FCA"],
};
const newDoc = (name, extra = {}) => ({
  doctype: "PZ Sales Contract", name, __islocal: 1, company: "Seller", currency: "USD", ...extra,
});
const flush = () => new Promise((resolve) => setImmediate(resolve));

function desk(doc = newDoc("new-1")) {
  const buttons = {}, opened = [], prompts = [];
  const handlers = {}, requests = [], lookups = [], alerts = [], queries = {}, fieldProperties = {};
  const locals = { "PZ Contract Item": {} };
  const frappe = {
    ui: { form: { on: (doctype, events) => { handlers[doctype] = events; } } },
    call: (request) => requests.push(request),
    prompt: (...args) => prompts.push(args),
    db: { get_value: (doctype, name, fields, callback) => lookups.push({ doctype, name, fields, callback }) },
    model: { set_value: (cdt, cdn, fieldname, value) => {
      const row = locals[cdt][cdn];
      if (typeof fieldname === "string") row[fieldname] = value;
      else Object.assign(row, fieldname);
      return Promise.resolve();
    } },
    show_alert: (alert) => alerts.push(alert), user: { has_role: () => false },
    throw: (message) => { throw new Error(message); },
  };
  vm.runInNewContext(script, { frappe, __: (value) => value, Promise, Set, WeakMap, locals, window: { open: (...args) => opened.push(args) } });
  const frm = {
    doc, fields_dict: {}, is_new() { return Boolean(this.doc.__islocal); },
    get_field() { return null; }, refresh_field() {},
    set_df_property(fieldname, property, value) { fieldProperties[`${fieldname}.${property}`] = value; },
    set_query(fieldname, ...args) { queries[fieldname] = args.at(-1); }, set_intro() {}, add_custom_button(label, action) { buttons[label] = action; },
    async set_value(key, value) {
      const values = typeof key === "string" ? { [key]: value } : key;
      for (const [fieldname, next] of Object.entries(values)) {
        if (this.doc[fieldname] === next) continue;
        this.doc[fieldname] = next;
        await handlers["PZ Sales Contract"][fieldname]?.(this);
        if (this.afterSet) await this.afterSet(fieldname);
      }
    },
  };
  const events = handlers["PZ Sales Contract"];
  events.setup(frm);
  return { frm, events, childEvents: handlers["PZ Contract Item"], requests, lookups, locals, alerts, queries, fieldProperties, frappe, buttons, opened, prompts,
    async refresh() { events.refresh(frm); await flush(); },
    async respond(index = requests.length - 1, values = profile) {
      requests[index].callback({ message: values }); await flush();
    },
};
}

test("new simplified contracts hide the specification editor", async () => {
  const ui = desk();
  await ui.refresh();
  assert.equal(ui.fieldProperties["specifications_section.hidden"], true);
  assert.equal(ui.fieldProperties["specifications.hidden"], true);
});

test("legacy contracts retain access to historical specifications", async () => {
  const ui = desk(newDoc("legacy-1", { __islocal: 0, terms_version: null }));
  await ui.refresh();
  assert.equal(ui.fieldProperties["specifications_section.hidden"], false);
  assert.equal(ui.fieldProperties["specifications.hidden"], false);
  assert.equal(ui.fieldProperties["conversion_rate.hidden"], false);
  assert.equal(ui.fieldProperties["selling_price_list.hidden"], false);
});

test("advance split defaults to 30 and previews fractional percentages with money rounding", async () => {
  const ui = desk();
  await ui.refresh();
  ui.frm.doc.items = [{ qty: 1, rate: 100.01 }];
  ui.frm.doc.discount_amount = 0;
  ui.childEvents.qty(ui.frm);
  assert.equal(ui.frm.doc.advance_percentage, 30);
  assert.equal(ui.frm.doc.advance_required, 30);
  assert.equal(ui.frm.doc.balance_required, 70.01);
  assert.equal(ui.fieldProperties["advance_required.label"], "Required advance (30%)");
  assert.equal(ui.fieldProperties["balance_required.label"], "Balance (70%)");

  for (const [percentage, advance, balance] of [
    [50, 50.01, 50], [20, 20, 80.01], [0, 0, 100.01], [100, 100.01, 0], [12.5, 12.5, 87.51],
  ]) {
    ui.frm.doc.advance_percentage = percentage;
    ui.events.advance_percentage(ui.frm);
    assert.equal(ui.frm.doc.advance_required, advance, `${percentage}% advance`);
    assert.equal(ui.frm.doc.balance_required, balance, `${100 - percentage}% balance`);
    assert.equal(ui.fieldProperties["advance_required.label"], `Required advance (${percentage}%)`);
    assert.equal(ui.fieldProperties["balance_required.label"], `Balance (${100 - percentage}%)`);
    assert.equal(Math.round((ui.frm.doc.advance_required + ui.frm.doc.balance_required) * 100) / 100, 100.01);
  }
});

test("quantity, rate, and discount changes recalculate the contract payment preview", async () => {
  const ui = desk();
  await ui.refresh();
  ui.frm.doc.advance_percentage = 50;
  ui.frm.doc.items = [{ qty: 1, rate: 100.01 }];
  ui.frm.doc.discount_amount = 0;
  ui.childEvents.qty(ui.frm);
  assert.deepEqual([ui.frm.doc.advance_required, ui.frm.doc.balance_required], [50.01, 50]);

  ui.frm.doc.items[0].qty = 2;
  ui.childEvents.qty(ui.frm);
  assert.deepEqual([ui.frm.doc.advance_required, ui.frm.doc.balance_required], [100.01, 100.01]);

  ui.frm.doc.items[0].rate = 150.01;
  ui.childEvents.rate(ui.frm);
  assert.deepEqual([ui.frm.doc.advance_required, ui.frm.doc.balance_required], [150.01, 150.01]);

  ui.frm.doc.discount_amount = 30;
  ui.events.discount_amount(ui.frm);
  assert.deepEqual([ui.frm.doc.advance_required, ui.frm.doc.balance_required], [135.01, 135.01]);
});

test("invalid percentages are rejected and historical/amended percentages stay protected", async () => {
  const ui = desk();
  await ui.refresh();
  for (const percentage of [-1, 100.01, Infinity, NaN]) {
    ui.frm.doc.advance_percentage = percentage;
    assert.throws(() => ui.events.advance_percentage(ui.frm), /finite number from 0 to 100/);
    await assert.rejects(ui.events.before_save(ui.frm), /finite number from 0 to 100/);
  }

  const historical = desk(newDoc("old-v4", {
    __islocal: 0, terms_version: "v4", grand_total: 101, advance_percentage: undefined,
  }));
  await historical.refresh();
  assert.equal(historical.frm.doc.advance_percentage, 30);
  assert.equal(historical.frm.doc.advance_required, 30.3);
  assert.equal(historical.frm.doc.balance_required, 70.7);
  assert.equal(historical.fieldProperties["advance_percentage.read_only"], true);

  const amendment = desk(newDoc("amendment", {
    amended_from: "Cancelled Contract", terms_version: "v5", advance_percentage: 50,
  }));
  await amendment.refresh();
  assert.equal(amendment.frm.doc.advance_percentage, 50);
  assert.equal(amendment.fieldProperties["advance_percentage.read_only"], true);
});

for (const version of ["v2", "v3", "v4", "v5", "v6", "v7"]) {
  test(`saved ${version} contracts keep the simplified specification editor hidden`, async () => {
    const ui = desk(newDoc(`${version}-saved`, { __islocal: 0, terms_version: version }));
    await ui.refresh();
    assert.equal(ui.fieldProperties["specifications_section.hidden"], true);
    assert.equal(ui.fieldProperties["specifications.hidden"], true);
  });
}

test("Item lookups ignore stale, cleared, and deleted child rows", async () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "line-1", item_code: "Item A" };
  ui.frm.doc.items = [row]; ui.locals["PZ Contract Item"][row.name] = row;
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  row.item_code = "Item B"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  await ui.respond(1, { item_name: "Item B", description: "B", stock_uom: "Nos", packaging: "Drum" });
  await ui.respond(0, { item_name: "Item A", description: "A", stock_uom: "Kg", packaging: "Bulk" });
  assert.equal(row.item_name, "Item B");
  assert.equal(row.uom, "Nos");
  assert.equal(row.packaging, "Drum");
  row.item_code = "Item C"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  assert.equal(row.packaging, null);
  row.item_code = ""; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  await ui.respond(2, { item_name: "Stale C", stock_uom: "Kg", packaging: "Bulk" });
  assert.equal(row.item_name, null);
  assert.equal(row.packaging, null);
  row.item_code = "Item D"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  ui.frm.doc.items = []; delete ui.locals["PZ Contract Item"][row.name];
  await ui.respond(3, { item_name: "Deleted D", stock_uom: "Kg", packaging: "Bulk" });
  assert.equal(row.item_name, null);
});

test("Grade Link snapshots follow the latest active selection and clearing", () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "grade-line", item_code: "Item A" };
  ui.frm.doc.items = [row]; ui.locals["PZ Contract Item"][row.name] = row;
  row.grade_master = "Grade A"; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  row.grade_master = "Grade B"; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  assert.deepEqual([...ui.lookups[0].fields], ["disabled"]);
  ui.lookups[1].callback({ disabled: 0 });
  ui.lookups[0].callback({ disabled: 0 });
  assert.equal(row.grade, "Grade B");

  row.grade_master = null; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  ui.lookups[1].callback({ disabled: 0 });
  assert.equal(row.grade, null);
});

test("packaging is derived after product changes and historical snapshots are preserved", async () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "packaging-line", item_code: "Bitumen - Bulk", packaging: null };
  ui.frm.doc.items = [row]; ui.locals["PZ Contract Item"][row.name] = row;
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  await ui.respond(0, { item_name: row.item_code, stock_uom: "Tonne", packaging: "Bulk" });
  assert.equal(row.packaging, "Bulk");
  row.item_code = "Bitumen - Drum";
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  assert.equal(row.packaging, null, "changing the Item clears the previous packaging snapshot");
  await ui.respond(1, { item_name: row.item_code, stock_uom: "Tonne", packaging: "Drum" });
  assert.equal(row.packaging, "Drum");
  row.item_code = "Unknown product";
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  await ui.respond(2, { item_name: row.item_code, stock_uom: "Tonne", packaging: null });
  assert.equal(row.packaging, null);
  row.item_code = "Bitumen - Drum";
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  ui.frm.doc = newDoc("another-doc", { items: [row] });
  await ui.respond(3, { item_name: "Bitumen - Drum", packaging: "Drum" });
  assert.equal(row.packaging, null, "navigation invalidates the old document response");

  const history = desk(newDoc("saved", { __islocal: 0 }));
  const saved = { ...row, item_code: "Bitumen - Bulk", packaging: "Historical text" };
  history.frm.doc.items = [saved]; history.locals["PZ Contract Item"][saved.name] = saved;
  history.childEvents.item_code(history.frm, saved.doctype, saved.name);
  await history.respond(0, { item_name: saved.item_code, stock_uom: "Tonne", packaging: "Bulk" });
  assert.equal(saved.packaging, "Historical text");
});

test("older saved contracts retain editable currency and their existing named-place entry", async () => {
  const ui = desk(newDoc("legacy", { __islocal: 0, currency: "EUR", conversion_rate: 1.2, named_place: "Old port" }));
  await ui.refresh();
  assert.equal(ui.frm.doc.currency, "EUR");
  assert.equal(ui.frm.doc.conversion_rate, 1.2);
  assert.equal(ui.fieldProperties["currency.read_only"], false);
  assert.equal(ui.fieldProperties["named_place.hidden"], false);
  assert.equal(ui.fieldProperties["contract_location.hidden"], true);
});

test("each New contract loads defaults in a reused Desk form", async () => {
  const ui = desk();
  await ui.refresh(); await ui.respond();
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
  assert.equal(ui.frm.doc.governing_law, undefined, "hidden legal profile terms are not copied into new contracts");
  ui.frm.doc = newDoc("new-2");
  await ui.refresh();
  assert.equal(ui.requests.length, 2);
  await ui.respond();
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
});

test("Incoterm choices are unfiltered and company defaults preserve selections", async () => {
  const ui = desk(newDoc("new-1", {incoterm: "CPT"}));
  assert.deepEqual(Object.keys(ui.queries.incoterm()), []);
  await ui.refresh(); await ui.respond();
  assert.equal(ui.frm.doc.incoterm, "CPT");
  await ui.frm.set_value("company", "Another Seller"); await flush();
  await ui.respond(1, { ...profile, allowed_incoterms: ["DAP"] });
  assert.equal(ui.frm.doc.incoterm, "CPT");
  assert.deepEqual(Object.keys(ui.queries.incoterm()), []);
});

for (const replacement of [newDoc("amendment", { amended_from: "Cancelled Original" }),
  newDoc("saved", { __islocal: 0 }), newDoc("second-new")]) {
  test(`a delayed response cannot change another document: ${replacement.name}`, async () => {
    const ui = desk(); await ui.refresh();
    ui.frm.doc = { ...replacement };
    await ui.refresh(); await ui.respond(0);
    assert.equal(ui.frm.doc.seller_position, undefined);
    assert.equal(ui.frm.doc.bank_receiving_account, undefined);
  });
}

test("switching documents during asynchronous field events stops application", async () => {
  const ui = desk(); await ui.refresh();
  const next = newDoc("next");
  ui.frm.afterSet = () => { ui.frm.doc = next; ui.events.refresh(ui.frm); };
  await ui.respond(0);
  assert.equal(next.bank_receiving_account, undefined);
  assert.equal(next.seller_position, undefined);
});

test("a deliberate alternate bank never receives profile instructions", async () => {
  const ui = desk(); await ui.refresh();
  await ui.frm.set_value("bank_receiving_account", "Bank B");
  await ui.respond();
  assert.equal(ui.frm.doc.bank_receiving_account, "Bank B");
  assert.equal(ui.frm.doc.account_iban, undefined);
  assert.equal(ui.frm.doc.beneficiary, undefined);
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
});

test("changing a copied bank clears only untouched copied instructions", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  await ui.frm.set_value("beneficiary", "Verified Beneficiary B");
  await ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  assert.equal(ui.frm.doc.beneficiary, "Verified Beneficiary B");
  assert.equal(ui.frm.doc.account_iban, null);
  assert.equal(ui.frm.doc.bank_branch, null);
  assert.equal(ui.frm.doc.swift_reference, null);
  assert.ok(!ui.frm.doc.selling_price_list, "price list is resolved on the server");
});

test("native unchanged Link triggers do not turn defaults into explicit overrides", async () => {
  const ui = desk(newDoc("new-1", { selling_price_list: "Generic Prices" }));
  ui.frm.fields_dict.selling_price_list = { df: { __default_value: "Generic Prices" } };
  await ui.refresh();
  ui.events.selling_price_list(ui.frm); // Native trigger_link_fields replays unchanged links.
  await ui.respond();
  assert.equal(ui.frm.doc.selling_price_list, "Generic Prices");
  ui.events.bank_receiving_account(ui.frm);
  await ui.frm.set_value("currency", "EUR"); await flush();
  assert.equal(ui.frm.doc.bank_receiving_account, null);
  assert.equal(ui.frm.doc.account_iban, null);
});

test("new entry resets currency to read-only USD without copying price or FX defaults", async () => {
  const ui = desk(newDoc("new-1", { currency: "EUR" }));
  await ui.refresh(); await ui.respond();
  assert.equal(ui.frm.doc.currency, "USD");
  assert.equal(ui.fieldProperties["currency.read_only"], true);
  assert.equal(ui.fieldProperties["conversion_rate.hidden"], true);
  assert.equal(ui.fieldProperties["selling_price_list.hidden"], true);
  assert.equal(ui.fieldProperties["contract_location.reqd"], true);
  assert.equal(ui.frm.doc.selling_price_list, undefined);
  assert.equal(ui.frm.doc.conversion_rate, undefined);
  ui.frm.doc.currency = "EUR";
  await assert.rejects(ui.events.before_save(ui.frm), /updating|must use USD/);
  await flush();
  await assert.rejects(ui.events.before_save(ui.frm), /must use USD/);
});

test("changing Company clears seller defaults and keeps customer and deal values", async () => {
  const ui = desk(newDoc("new-1", { customer: "Buyer", named_place: "Deal Place" }));
  await ui.refresh(); await ui.respond();
  await ui.frm.set_value("company", "Another Seller"); await flush();
  assert.equal(ui.frm.doc.customer, "Buyer");
  assert.equal(ui.frm.doc.named_place, "Deal Place");
  assert.equal(ui.frm.doc.bank_receiving_account, null);
  assert.equal(ui.frm.doc.seller_position, null);
  await ui.respond(0);
  assert.equal(ui.frm.doc.seller_position, null);
  await ui.respond(1, { ...profile, seller_signatory: "Another Signer" });
  assert.equal(ui.frm.doc.seller_signatory, "Another Signer");
});

test("an amendment retains its seller details without applying current company defaults", async () => {
  const ui = desk(newDoc("amendment", { amended_from: "Cancelled Original", seller_position: "Original Terms" }));
  await ui.refresh(); await ui.frm.set_value("currency", "EUR");
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.frm.doc.seller_position, "Original Terms");
});

test("returning to an unsaved contract preserves copied-bank provenance", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  const first = ui.frm.doc;
  ui.frm.doc = newDoc("second"); await ui.refresh(); await ui.respond();
  ui.frm.doc = first; await ui.refresh();
  if (ui.requests.length > 2) await ui.respond();
  await ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  assert.equal(first.account_iban, null);
  assert.equal(first.bank_branch, null);
});

test("returning to an unsaved contract preserves deliberate generic-value overrides", async () => {
  const ui = desk();
  ui.frm.fields_dict.selling_price_list = { df: { __default_value: "Generic Prices" } };
  await ui.refresh(); await ui.respond();
  await ui.frm.set_value("selling_price_list", "Generic Prices");
  const first = ui.frm.doc;
  ui.frm.doc = newDoc("second"); await ui.refresh(); await ui.respond();
  ui.frm.doc = first; await ui.refresh();
  if (ui.requests.length > 2) await ui.respond();
  assert.equal(first.selling_price_list, "Generic Prices");
});

test("partially applied defaults keep their provenance after navigating away and back", async () => {
  const ui = desk(); await ui.refresh();
  const first = ui.frm.doc;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "account_iban") {
      ui.frm.afterSet = null;
      ui.frm.doc = newDoc("second"); ui.events.refresh(ui.frm);
    }
  };
  await ui.respond(0); await ui.respond(1);
  ui.frm.doc = first; await ui.refresh();
  if (ui.requests.length > 2) await ui.respond();
  await ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  assert.equal(first.account_iban, null);
});

test("native prefilled or duplicated documents preserve explicit zero and generic-value overrides", async () => {
  const ui = desk(newDoc("prefilled", {
    __run_link_triggers: false, collection_grace: 0, selling_price_list: "Generic Prices",
  }));
  ui.frm.fields_dict.selling_price_list = { df: { __default_value: "Generic Prices" } };
  await ui.refresh(); await ui.respond(0, { ...profile, collection_grace: 48 });
  assert.equal(ui.frm.doc.collection_grace, 0);
  assert.equal(ui.frm.doc.selling_price_list, "Generic Prices");
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
});

test("returning finishes interrupted clearing of the previous bank instructions", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  const first = ui.frm.doc;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "beneficiary" && first.beneficiary === null) {
      ui.frm.afterSet = null;
      ui.frm.doc = newDoc("second"); ui.events.refresh(ui.frm);
    }
  };
  await ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  await ui.respond(1);
  ui.frm.doc = first; await ui.refresh();
  if (ui.requests.length > 2) await ui.respond();
  for (const field of ["beneficiary", "bank_branch", "account_iban", "swift_reference"])
    assert.equal(first[field], null, field);
});

test("edits made while defaults are applying remain authoritative", async () => {
  const ui = desk(); await ui.refresh();
  ui.frm.afterSet = async (fieldname) => {
    if (fieldname === "seller_signatory") {
      ui.frm.afterSet = null;
      await ui.frm.set_value("bank_receiving_account", "Bank B");
      await ui.frm.set_value("beneficiary", "Verified Beneficiary B");
    }
  };
  await ui.respond();
  assert.equal(ui.frm.doc.bank_receiving_account, "Bank B");
  assert.equal(ui.frm.doc.beneficiary, "Verified Beneficiary B");
  assert.equal(ui.frm.doc.account_iban, null);
});

test("returning completes a Company change before loading the new seller defaults", async () => {
  const ui = desk(); await ui.refresh();
  await ui.respond(0, { ...profile, seller_address: "Address A" });
  const first = ui.frm.doc;
  const second = newDoc("second");
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "seller_address" && first.seller_address === null) {
      ui.frm.afterSet = null;
      ui.frm.doc = second; ui.events.refresh(ui.frm);
    }
  };
  await ui.frm.set_value("company", "Another Seller"); await flush();
  assert.equal(first.seller_signatory, profile.seller_signatory);
  assert.equal(second.seller_signatory, undefined);
  assert.equal(ui.requests.filter((request) => request.args.company === "Another Seller").length, 0);
  ui.frm.doc = first; await ui.refresh();
  const nextProfile = {
    ...profile, seller_address: "Address B", seller_signatory: "Signer B",
    seller_position: "Law B", bank_receiving_account: "Bank B",
  };
  assert.equal(ui.requests.at(-1).args.company, "Another Seller");
  await ui.respond(ui.requests.length - 1, nextProfile);
  for (const field of ["seller_signatory", "seller_position", "bank_receiving_account"])
    assert.equal(first[field], nextProfile[field], field);
  assert.equal(second.seller_signatory, undefined);
});

test("a generic-value edit during defaults survives a later currency round trip", async () => {
  const ui = desk();
  ui.frm.fields_dict.selling_price_list = { df: { __default_value: "Generic Prices" } };
  await ui.refresh();
  ui.frm.afterSet = async (fieldname) => {
    if (fieldname === "seller_signatory") {
      ui.frm.afterSet = null;
      await ui.frm.set_value("selling_price_list", "Generic Prices");
    }
  };
  await ui.respond();
  assert.equal(ui.frm.doc.selling_price_list, "Generic Prices");
  await ui.frm.set_value("currency", "EUR"); await flush();
  await ui.frm.set_value("currency", "USD"); await flush();
  await ui.respond();
  assert.equal(ui.frm.doc.selling_price_list, "Generic Prices");
});

for (const editTiming of ["before resuming", "during resumed field events"]) {
  test(`returning preserves fresh Company-field edits ${editTiming}`, async () => {
    const ui = desk(); await ui.refresh();
    await ui.respond(0, { ...profile, seller_address: "Address A", collection_grace: 48 });
    const first = ui.frm.doc;
    ui.frm.afterSet = (fieldname) => {
      if (fieldname === "seller_address" && first.seller_address === null) {
        ui.frm.afterSet = null;
        ui.frm.doc = newDoc("second"); ui.events.refresh(ui.frm);
      }
    };
    await ui.frm.set_value("company", "Another Seller"); await flush();
    ui.frm.doc = first;
    const enterFreshValues = async () => {
      await ui.frm.set_value("seller_signatory", "Deal Signer");
      await ui.frm.set_value("seller_position", "Temporary Edit");
      await ui.frm.set_value("seller_position", profile.seller_position);
      await ui.frm.set_value("bank_receiving_account", "Deal Bank");
      await ui.frm.set_value("collection_grace", 0);
    };
    if (editTiming === "before resuming") await enterFreshValues();
    else ui.frm.afterSet = async (fieldname) => {
      if (fieldname === "seller_signatory" && first.seller_signatory === null) {
        ui.frm.afterSet = null;
        await enterFreshValues();
      }
    };
    await ui.refresh();
    await ui.respond(ui.requests.length - 1, {
      ...profile, seller_address: "Address B", seller_signatory: "Signer B",
      seller_position: "Law B", bank_receiving_account: "Bank B", collection_grace: 24,
    });
    assert.equal(first.seller_address, null);
    assert.equal(first.seller_signatory, "Deal Signer");
    assert.equal(first.seller_position, profile.seller_position);
    assert.equal(first.bank_receiving_account, "Deal Bank");
    assert.equal(first.collection_grace, 0);
    assert.equal(first.account_iban, null);
  });
}

test("refreshes during Company clearing wait for the remaining fields before requesting defaults", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  let finishEvent;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "seller_signatory" && ui.frm.doc.seller_signatory === null) {
      ui.frm.afterSet = null;
      return new Promise((resolve) => { finishEvent = resolve; });
    }
  };
  await ui.frm.set_value("company", "Another Seller"); await flush();
  assert.equal(typeof finishEvent, "function");
  await ui.refresh(); await ui.refresh();
  assert.equal(ui.requests.length, 1);
  finishEvent(); await flush();
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.frm.doc.seller_position, null);
  assert.equal(ui.frm.doc.bank_receiving_account, null);
  await ui.respond(1, { ...profile, seller_signatory: "Signer B" });
  assert.equal(ui.frm.doc.seller_signatory, "Signer B");
});

test("currency changes during bank-instruction clearing are reconciled before saving", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  let finishEvent;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "beneficiary" && ui.frm.doc.beneficiary === null) {
      ui.frm.afterSet = null;
      return new Promise((resolve) => { finishEvent = resolve; });
    }
  };
  const bankChange = ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  await ui.frm.set_value("currency", "EUR");
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  finishEvent(); await bankChange; await flush();
  assert.ok(!ui.frm.doc.conversion_rate);
  assert.ok(!ui.frm.doc.selling_price_list);
  assert.equal(ui.frm.doc.account_iban, null);
  assert.equal(ui.frm.doc.bank_receiving_account, "Bank B");
  assert.equal(ui.frm.doc.currency, "EUR");
  assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
  await assert.rejects(ui.events.before_save(ui.frm), /must use USD/);
  await ui.frm.set_value("currency", "USD"); await flush();
  assert.equal(ui.requests.length, 2);
  await ui.respond(1);
  assert.ok(!ui.frm.doc.selling_price_list, "price list is resolved on the server");
  assert.equal(ui.frm.doc.bank_receiving_account, "Bank B");
  assert.equal(ui.frm.doc.account_iban, null);
});

for (const response of ["empty", "failed"]) {
  test(`superseded application and ${response} defaults release the save barrier`, async () => {
    const ui = desk(); await ui.refresh();
    let finishEvent;
    ui.frm.afterSet = (fieldname) => {
      if (fieldname === "seller_signatory") {
        ui.frm.afterSet = null;
        return new Promise((resolve) => { finishEvent = resolve; });
      }
    };
    await ui.respond();
    await ui.frm.set_value("company", "Another Seller"); await flush();
    if (response === "empty") await ui.respond(1, {});
    else { ui.requests[1].error(); await flush(); }
    await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
    finishEvent(); await flush();
    assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
    await ui.events.before_save(ui.frm);
    await ui.frm.set_value("seller_signatory", "Manually Verified Signer");
    await ui.events.before_save(ui.frm);
    assert.equal(ui.frm.doc.seller_signatory, "Manually Verified Signer");
  });
}

test("a failed Company clear is retried by Save without allowing a stale snapshot", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "seller_signatory" && ui.frm.doc.seller_signatory === null) {
      ui.frm.afterSet = null;
      throw new Error("Synthetic field-event failure");
    }
  };
  await ui.frm.set_value("company", "Another Seller"); await flush();
  assert.ok(ui.frm._pzCompanyDefaultsPendingClear);
  assert.equal(ui.frm.doc.seller_position, profile.seller_position);
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  await flush();
  assert.equal(ui.frm.doc.seller_position, null);
  await ui.respond(1, { ...profile, seller_position: "Law B" });
  await ui.events.before_save(ui.frm);
  assert.equal(ui.frm.doc.seller_position, "Law B");
});

test("overlapping clear completions cannot release another operation's save barrier", async () => {
  const ui = desk(); await ui.refresh(); await ui.respond();
  let finishBank, finishCompany;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "beneficiary" && ui.frm.doc.beneficiary === null) {
      ui.frm.afterSet = null;
      return new Promise((resolve) => { finishBank = resolve; });
    }
  };
  const bankChange = ui.frm.set_value("bank_receiving_account", "Bank B"); await flush();
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "seller_signatory" && ui.frm.doc.seller_signatory === null) {
      ui.frm.afterSet = null;
      return new Promise((resolve) => { finishCompany = resolve; });
    }
  };
  await ui.frm.set_value("company", "Another Seller"); await flush();
  finishBank(); await bankChange; await flush();
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  finishCompany(); await flush();
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  await ui.respond(1, {});
  await ui.events.before_save(ui.frm);
  assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
});

test("returning during unfinished work preserves the save barrier without blocking another document", async () => {
  const ui = desk(); await ui.refresh();
  const first = ui.frm.doc;
  let finishEvent;
  ui.frm.afterSet = (fieldname) => {
    if (fieldname === "seller_signatory") {
      ui.frm.afterSet = null;
      return new Promise((resolve) => { finishEvent = resolve; });
    }
  };
  await ui.respond();
  ui.frm.doc = newDoc("second"); await ui.refresh(); await ui.respond(1, {});
  await ui.events.before_save(ui.frm);
  ui.frm.doc = first; await ui.refresh();
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  await ui.respond(2);
  await assert.rejects(ui.events.before_save(ui.frm), /Company details.*updating/);
  finishEvent(); await flush();
  await ui.events.before_save(ui.frm);
  assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
});


test("direct party defaults remain editable and buyer fields never use ERP lookups", async () => {
  const ui = desk(newDoc("party-new", { seller_name: "Explicit Seller" }));
  await ui.refresh();
  assert.equal(ui.frm.doc.seller_name, "Explicit Seller");
  assert.equal(ui.frm.doc.seller_address_display, "Arbat-Sulaimani, Iraq");
  assert.equal(ui.frm.doc.seller_phone, "00964 770 000 3737");
  assert.equal(ui.fieldProperties["buyer_email_phone.reqd"], false);
  assert.equal(ui.queries.customer_address, undefined);
  assert.equal(ui.queries.contact_person, undefined);
  ui.frm.doc.seller_email = "Edited seller contact";
  await ui.refresh();
  assert.equal(ui.frm.doc.seller_email, "Edited seller contact");
  ui.frm.doc.customer_name = "Prior Buyer";
  ui.frm.doc.buyer_email_phone = "00971 505 65 1305";
  await ui.frm.set_value("customer", "Next Customer");
  await flush();
  assert.equal(ui.frm.doc.customer_name, null);
  assert.equal(ui.frm.doc.buyer_email_phone, null);
});

test("historical party snapshots get neither defaults nor new mandatory fields", async () => {
  const ui = desk(newDoc("historical-party", { __islocal: 0, customer_name: "Saved Buyer", seller_address_display: "Saved Address" }));
  await ui.refresh();
  assert.equal(ui.frm.doc.customer_name, "Saved Buyer");
  assert.equal(ui.frm.doc.seller_address_display, "Saved Address");
  assert.equal(ui.frm.doc.seller_name, undefined);
  assert.equal(ui.fieldProperties["buyer_email_phone.reqd"], false);
});

test("cargo readiness is optional calendar days, with a clear no-advance omission", async () => {
  const ui = desk();
  await ui.refresh();
  assert.equal(ui.frm.doc.cargo_ready_within_days, undefined);
  assert.equal(ui.fieldProperties["cargo_ready_within_days.hidden"], false);
  assert.equal(ui.fieldProperties["cargo_ready_within_days.read_only"], false);
  assert.match(ui.fieldProperties["cargo_ready_within_days.description"], /calendar days/);
  for (const value of ["", 0, 30, 50, 60, 137]) {
    ui.frm.doc.cargo_ready_within_days = value;
    ui.events.cargo_ready_within_days(ui.frm);
  }
  for (const value of [-1, 1.5, "invalid", Infinity, 2147483648]) {
    ui.frm.doc.cargo_ready_within_days = value;
    assert.throws(() => ui.events.cargo_ready_within_days(ui.frm), /whole number/);
  }
  ui.frm.doc.advance_percentage = 0;
  ui.events.advance_percentage(ui.frm);
  assert.match(ui.fieldProperties["cargo_ready_within_days.description"], /0% advance.*omitted/);
});

test("cargo readiness is visible for history and read-only after submission", async () => {
  for (const version of [null, "v1", "v2", "v3", "v4", "v5"]) {
    const ui = desk(newDoc("old", { __islocal: 0, terms_version: version }));
    await ui.refresh();
    assert.equal(ui.fieldProperties["cargo_ready_within_days.hidden"], false);
  }
  for (const extra of [{ docstatus: 1 }, { docstatus: 2 }]) {
    const ui = desk(newDoc("v6", { __islocal: 0, terms_version: "v6", ...extra }));
    await ui.refresh();
    assert.equal(ui.fieldProperties["cargo_ready_within_days.read_only"], true);
  }
});

test("saved pre-v6 drafts expose cargo readiness without changing their terms version", async () => {
  for (const version of [null, "v1", "v2", "v3", "v4", "v5"]) {
    const ui = desk(newDoc("saved-draft", { __islocal: 0, docstatus: 0, terms_version: version }));
    await ui.refresh();
    assert.equal(ui.fieldProperties["cargo_ready_within_days.hidden"], false);
    assert.equal(ui.fieldProperties["cargo_ready_within_days.read_only"], false);
    assert.equal(ui.frm.doc.terms_version, version);
  }
});

test("terms preview never edits the document; explicit draft edit copies saved wording", async () => {
  const ui = desk(newDoc("saved-draft", { __islocal: 0, docstatus: 0, terms_version: "v5" }));
  let preview;
  ui.frm.fields_dict.contract_terms_preview = { $wrapper: { html(value) { preview = value; } } };
  ui.frappe.xcall = async () => ({ text: "1. Original saved wording", html: "<p>1. Original saved wording</p>" });
  await ui.refresh();
  assert.match(preview, /Original saved wording/);
  assert.equal(ui.frm.doc.contract_terms_text, undefined);
  await ui.events.edit_contract_terms(ui.frm);
  assert.equal(ui.frm.doc.contract_terms_text, "1. Original saved wording");
  assert.equal(ui.fieldProperties["contract_terms_text.hidden"], false);
  ui.frm.doc.contract_terms_text = "Custom wording";
  ui.frm.doc.advance_percentage = 50;
  ui.events.advance_percentage(ui.frm);
  assert.equal(ui.frm.doc.contract_terms_text, "Custom wording");
  ui.frm.doc.docstatus = 1;
  await ui.refresh();
  assert.equal(ui.fieldProperties["contract_terms_text.read_only"], true);
  assert.equal(ui.fieldProperties["edit_contract_terms.hidden"], true);
});

test("late terms preview cannot overwrite a newer edit or a different form", async () => {
  const ui = desk();
  let reply;
  ui.frm.fields_dict.contract_terms_preview = { $wrapper: { html() {} } };
  ui.frappe.xcall = () => new Promise(resolve => { reply = resolve; });
  const pending = ui.events.edit_contract_terms(ui.frm);
  ui.frm.doc.contract_terms_text = "User text entered while loading";
  reply({ text: "Old terms", html: "<p>Old terms</p>" });
  await pending;
  assert.equal(ui.frm.doc.contract_terms_text, "User text entered while loading");
});

test("clearing custom terms requests the original fallback, and amendment previews identify their source", async () => {
  const ui = desk(newDoc("saved", { __islocal: 0, terms_version: "v5", contract_terms_text: "Saved custom wording" }));
  const calls = [];
  let preview;
  ui.frm.fields_dict.contract_terms_preview = { $wrapper: { html(value) { preview = value; } } };
  ui.frappe.xcall = async (_method, args) => {
    calls.push(args);
    return args.use_original_terms ? { text: "Original v5", html: "<p>Original v5</p>" } : { text: "Saved custom wording", html: "<p>Saved custom wording</p>" };
  };
  await ui.refresh();
  await ui.frm.set_value("contract_terms_text", "");
  assert.equal(calls.at(-1).use_original_terms, 1);
  assert.match(preview, /Original v5/);
  await ui.events.edit_contract_terms(ui.frm);
  assert.equal(ui.frm.doc.contract_terms_text, "Original v5");
  ui.frm.doc = newDoc("new-amendment", { amended_from: "cancelled-v5", terms_version: "v5" });
  await ui.events.edit_contract_terms(ui.frm);
  assert.equal(calls.at(-1).amended_from, "cancelled-v5");
  assert.equal(calls.at(-1).name, null);
});


test("descriptions survive refresh, Item changes, clears and late lookup replies", async () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "described-line", item_code: "Item A", description: "Hand written\nProduct wording" };
  ui.frm.doc.items = [row]; ui.locals[row.doctype][row.name] = row;
  await ui.refresh();
  assert.equal(row.description, "Hand written\nProduct wording");
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  row.description = "Edited while lookup is pending";
  await ui.respond(ui.requests.length - 1, { item_name: "Item A", description: "Master A", stock_uom: "Kg" });
  assert.equal(row.description, "Edited while lookup is pending");
  row.item_code = "Item B";
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  await ui.respond(ui.requests.length - 1, { item_name: "Item B", description: "Master B", stock_uom: "Kg" });
  assert.equal(row.description, "Edited while lookup is pending");
  row.item_code = ""; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  assert.equal(row.description, "Edited while lookup is pending");
});

test("blank printing selects a saved legal context without saving or serializing the form", async () => {
  for (const extra of [{}, { __islocal: 0, docstatus: 0 }, { __islocal: 0, docstatus: 1 }]) {
    const ui = desk(newDoc("PRIVATE-CONTRACT", { customer_name: "PRIVATE-BUYER", items: [{ description: "PRIVATE-PRODUCT", rate: 987654 }], ...extra }));
    await ui.refresh();
    const before = JSON.stringify(ui.frm.doc);
    const calls = ui.requests.length;
    ui.buttons["Print Blank Template"]();
    assert.equal(ui.opened.length, 0);
    const [fields, callback, title, label] = ui.prompts[0];
    assert.equal(title, "Print Blank Template");
    assert.equal(label, "Preview Blank Template");
    assert.equal(fields[0].fieldname, "source_contract");
    assert.equal(fields[0].fieldtype, "Link");
    assert.equal(fields[0].options, "PZ Sales Contract");
    assert.equal(fields[0].reqd, 1);
    assert.equal(fields[0].default, ui.frm.is_new() ? undefined : ui.frm.doc.name);
    assert.match(fields[0].description, /terms and Incoterm/);
    assert.match(fields[0].description, /Unsaved changes are not used/);
    callback({ source_contract: "CHOSEN/CONTRACT & EXW" });
    assert.deepEqual(ui.opened, [["/api/method/pz_sales_contract.printing.print_blank_template?source_contract=CHOSEN%2FCONTRACT%20%26%20EXW", "_blank", "noopener,noreferrer"]]);
    assert.equal(JSON.stringify(ui.frm.doc), before);
    assert.equal(ui.requests.length, calls);
  }
});

test("Word download opens only a saved contract and never saves or serializes form data", async () => {
  const fresh = desk();
  await fresh.refresh();
  assert.equal(fresh.buttons["Download Word (.docx)"], undefined);
  for (const status of [0, 1, 2]) {
    const ui = desk(newDoc("SC/1 & word", { __islocal: 0, docstatus: status, customer_name: "PRIVATE BUYER" }));
    await ui.refresh();
    const before = JSON.stringify(ui.frm.doc);
    const calls = ui.requests.length;
    ui.buttons["Download Word (.docx)"]();
    assert.deepEqual(ui.opened, [["/api/method/pz_sales_contract.word_export.download_word?name=SC%2F1%20%26%20word", "_blank", "noopener,noreferrer"]]);
    assert.equal(JSON.stringify(ui.frm.doc), before);
    assert.equal(ui.requests.length, calls);
    ui.frm.is_dirty = () => true;
    assert.throws(() => ui.buttons["Download Word (.docx)"](), /Save your changes/);
    assert.equal(ui.opened.length, 1);
  }
});

test("blank Word downloads use the same saved-source chooser on new, draft and submitted forms", async () => {
  for (const extra of [{}, { __islocal: 0, docstatus: 0 }, { __islocal: 0, docstatus: 1 }]) {
    const ui = desk(newDoc("UNSAVED PRIVATE CONTRACT", { ...extra, customer_name: "PRIVATE BUYER" }));
    await ui.refresh();
    const before = JSON.stringify(ui.frm.doc);
    const calls = ui.requests.length;
    ui.buttons["Download Blank Word (.docx)"]();
    const [fields, callback, title, label] = ui.prompts[0];
    assert.equal(title, "Download Blank Word (.docx)");
    assert.equal(label, "Download Word (.docx)");
    assert.equal(fields[0].default, ui.frm.is_new() ? undefined : ui.frm.doc.name);
    assert.equal(fields[0].options, "PZ Sales Contract");
    callback({ source_contract: "SAVED/SOURCE & EXW" });
    assert.deepEqual(ui.opened, [["/api/method/pz_sales_contract.word_export.download_blank_word?source_contract=SAVED%2FSOURCE%20%26%20EXW", "_blank", "noopener,noreferrer"]]);
    assert.equal(JSON.stringify(ui.frm.doc), before);
    assert.equal(ui.requests.length, calls);
  }
});
