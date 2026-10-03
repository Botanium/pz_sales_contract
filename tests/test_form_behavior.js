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
  const handlers = {}, requests = [], lookups = [], alerts = [], queries = {};
  const locals = { "PZ Contract Item": {} };
  const frappe = {
    ui: { form: { on: (doctype, events) => { handlers[doctype] = events; } } },
    call: (request) => requests.push(request),
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
  vm.runInNewContext(script, { frappe, __: (value) => value, Promise, Set, WeakMap, locals });
  const frm = {
    doc, fields_dict: {}, is_new() { return Boolean(this.doc.__islocal); },
    set_query(fieldname, ...args) { queries[fieldname] = args.at(-1); }, set_intro() {}, add_custom_button() {},
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
  return { frm, events, childEvents: handlers["PZ Contract Item"], requests, lookups, locals, alerts, queries,
    async refresh() { events.refresh(frm); await flush(); },
    async respond(index = requests.length - 1, values = profile) {
      requests[index].callback({ message: values }); await flush();
    },
  };
}

test("Item and Grade lookups ignore stale, cleared, and deleted child rows", () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "line-1", item_code: "Item A" };
  ui.frm.doc.items = [row]; ui.locals["PZ Contract Item"][row.name] = row;
  ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  row.item_code = "Item B"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  ui.lookups[1].callback({ item_name: "Item B", description: "B", stock_uom: "Nos" });
  ui.lookups[0].callback({ item_name: "Item A", description: "A", stock_uom: "Kg" });
  assert.equal(row.item_name, "Item B");
  assert.equal(row.uom, "Nos");

  row.item_code = "Item C"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  row.item_code = ""; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  ui.lookups[2].callback({ item_name: "Stale C", description: "stale", stock_uom: "Kg" });
  assert.equal(row.item_name, "Item B");

  row.item_code = "Item D"; ui.childEvents.item_code(ui.frm, row.doctype, row.name);
  ui.frm.doc.items = [];
  delete ui.locals["PZ Contract Item"][row.name];
  ui.lookups[3].callback({ item_name: "Deleted D", description: "stale", stock_uom: "Kg" });
  assert.equal(row.item_name, "Item B");
});

test("Grade Link snapshots follow the latest active selection and clearing", () => {
  const ui = desk();
  const row = { doctype: "PZ Contract Item", name: "grade-line", item_code: "Item A" };
  ui.frm.doc.items = [row]; ui.locals["PZ Contract Item"][row.name] = row;
  row.grade_master = "Grade A"; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  row.grade_master = "Grade B"; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  assert.deepEqual(ui.lookups[0].fields, ["disabled"]);
  ui.lookups[1].callback({ disabled: 0 });
  ui.lookups[0].callback({ disabled: 0 });
  assert.equal(row.grade, "Grade B");

  row.grade_master = null; ui.childEvents.grade_master(ui.frm, row.doctype, row.name);
  ui.lookups[1].callback({ disabled: 0 });
  assert.equal(row.grade, null);
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

test("new contracts offer the base and configured Incoterms without silently selecting one", async () => {
  const ui = desk();
  const options = () => ui.queries.incoterm().filters.name[1];
  assert.deepEqual(options(), ["EXW", "FOB", "CIF"]);
  assert.equal(ui.frm.doc.incoterm, undefined);
  await ui.refresh(); await ui.respond();
  assert.deepEqual(options(), ["EXW", "FOB", "CIF", "FCA"]);
  assert.equal(ui.frm.doc.incoterm, undefined);
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
  assert.equal(ui.frm.doc.seller_position, null);
  await ui.respond(0);
  assert.equal(ui.frm.doc.seller_position, null);
  await ui.respond(1, { ...profile, seller_signatory: "Another Signer" });
  assert.equal(ui.frm.doc.seller_signatory, "Another Signer");
});

test("an amendment requests allowed Incoterms without applying current company defaults", async () => {
  const ui = desk(newDoc("amendment", { amended_from: "Cancelled Original", seller_position: "Original Terms" }));
  await ui.refresh(); await ui.frm.set_value("currency", "EUR");
  assert.equal(ui.requests.length, 1);
  assert.match(ui.requests[0].method, /get_allowed_incoterms$/);
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
  for (const field of ["seller_address", "seller_signatory", "seller_position", "bank_receiving_account"])
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
    assert.equal(first.seller_address, "Address B");
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
  assert.equal(ui.frm.doc.conversion_rate, null);
  assert.equal(ui.frm.doc.selling_price_list, null);
  assert.equal(ui.frm.doc.account_iban, null);
  assert.equal(ui.frm.doc.bank_receiving_account, "Bank B");
  assert.equal(ui.frm.doc.currency, "EUR");
  assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
  await ui.events.before_save(ui.frm);
  await ui.frm.set_value("currency", "USD"); await flush();
  assert.equal(ui.requests.length, 2);
  await ui.respond(1);
  assert.equal(ui.frm.doc.selling_price_list, profile.selling_price_list);
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
