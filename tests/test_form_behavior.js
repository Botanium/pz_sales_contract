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
  swift_reference: "Reference A", governing_law: "Approved Terms",
};
const newDoc = (name, extra = {}) => ({
  doctype: "PZ Sales Contract", name, __islocal: 1, company: "Seller", currency: "USD", ...extra,
});
const flush = () => new Promise((resolve) => setImmediate(resolve));

function desk(doc = newDoc("new-1")) {
  const handlers = {}, requests = [], alerts = [];
  const frappe = {
    ui: { form: { on: (doctype, events) => { handlers[doctype] = events; } } },
    call: (request) => requests.push(request),
    show_alert: (alert) => alerts.push(alert), user: { has_role: () => false },
  };
  vm.runInNewContext(script, { frappe, __: (value) => value, Promise, Set });
  const frm = {
    doc, fields_dict: {}, is_new() { return Boolean(this.doc.__islocal); },
    set_query() {}, set_intro() {}, add_custom_button() {},
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
  return { frm, events, requests, alerts,
    async refresh() { events.refresh(frm); await flush(); },
    async respond(index = requests.length - 1, values = profile) {
      requests[index].callback({ message: values }); await flush();
    },
  };
}

test("each New contract loads defaults in a reused Desk form", async () => {
  const ui = desk();
  await ui.refresh(); await ui.respond();
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
  ui.frm.doc = newDoc("new-2");
  await ui.refresh();
  assert.equal(ui.requests.length, 2);
  await ui.respond();
  assert.equal(ui.frm.doc.seller_signatory, profile.seller_signatory);
});

for (const replacement of [newDoc("amendment", { amended_from: "Cancelled Original" }),
  newDoc("saved", { __islocal: 0 }), newDoc("second-new")]) {
  test(`a delayed response cannot change another document: ${replacement.name}`, async () => {
    const ui = desk(); await ui.refresh();
    ui.frm.doc = { ...replacement };
    await ui.refresh(); await ui.respond(0);
    assert.equal(ui.frm.doc.governing_law, undefined);
    assert.equal(ui.frm.doc.bank_receiving_account, undefined);
  });
}

test("switching documents during asynchronous field events stops application", async () => {
  const ui = desk(); await ui.refresh();
  const next = newDoc("next");
  ui.frm.afterSet = () => { ui.frm.doc = next; ui.events.refresh(ui.frm); };
  await ui.respond(0);
  assert.equal(next.bank_receiving_account, undefined);
  assert.equal(next.governing_law, undefined);
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
  assert.equal(ui.frm.doc.selling_price_list, profile.selling_price_list);
});

test("native unchanged Link triggers do not turn defaults into explicit overrides", async () => {
  const ui = desk(newDoc("new-1", { selling_price_list: "Generic Prices" }));
  ui.frm.fields_dict.selling_price_list = { df: { __default_value: "Generic Prices" } };
  await ui.refresh();
  ui.events.selling_price_list(ui.frm); // Native trigger_link_fields replays unchanged links.
  await ui.respond();
  assert.equal(ui.frm.doc.selling_price_list, profile.selling_price_list);
  ui.events.bank_receiving_account(ui.frm);
  await ui.frm.set_value("currency", "EUR"); await flush();
  assert.equal(ui.frm.doc.bank_receiving_account, null);
  assert.equal(ui.frm.doc.account_iban, null);
});

test("a currency mismatch preserves deliberate values and can reload matching defaults", async () => {
  const ui = desk(newDoc("new-1", { currency: "EUR", selling_price_list: "EUR Prices" }));
  await ui.refresh(); await ui.respond();
  assert.equal(ui.frm.doc.currency, "EUR");
  assert.equal(ui.frm.doc.selling_price_list, "EUR Prices");
  assert.equal(ui.frm.doc.bank_receiving_account, undefined);
  await ui.frm.set_value("currency", "USD");
  assert.equal(ui.requests.length, 2);
  await ui.respond();
  assert.equal(ui.frm.doc.selling_price_list, "EUR Prices");
  assert.equal(ui.frm.doc.bank_receiving_account, profile.bank_receiving_account);
});

test("changing Company clears seller defaults and keeps customer and deal values", async () => {
  const ui = desk(newDoc("new-1", { customer: "Buyer", named_place: "Deal Place" }));
  await ui.refresh(); await ui.respond();
  await ui.frm.set_value("company", "Another Seller"); await flush();
  assert.equal(ui.frm.doc.customer, "Buyer");
  assert.equal(ui.frm.doc.named_place, "Deal Place");
  assert.equal(ui.frm.doc.bank_receiving_account, null);
  assert.equal(ui.frm.doc.governing_law, null);
  await ui.respond(0);
  assert.equal(ui.frm.doc.governing_law, null);
  await ui.respond(1, { ...profile, seller_signatory: "Another Signer" });
  assert.equal(ui.frm.doc.seller_signatory, "Another Signer");
});

test("an amendment never requests current company defaults", async () => {
  const ui = desk(newDoc("amendment", { amended_from: "Cancelled Original", governing_law: "Original Terms" }));
  await ui.refresh(); await ui.frm.set_value("currency", "EUR");
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.frm.doc.governing_law, "Original Terms");
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
