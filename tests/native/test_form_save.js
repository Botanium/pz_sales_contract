// Exercise Frappe's real model, ScriptManager, mandatory check and save pipeline.
// The DOM and network are intercepted; this is not a browser/visual test.
// CI points FRAPPE_APP_PATH at the v16 app in its disposable integration bench.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const repo = path.resolve(__dirname, "../..");
const frappeApp = process.env.FRAPPE_APP_PATH || path.resolve(repo, "../frappe");
const doctypeDir = path.join(repo, "pz_sales_contract/sales_contracts/doctype");
const schemas = Object.fromEntries([
  "pz_sales_contract", "pz_contract_item", "pz_contract_specification",
].map((name) => {
  const schema = JSON.parse(fs.readFileSync(path.join(doctypeDir, name, `${name}.json`)));
  return [schema.name, schema];
}));
const schema = schemas["PZ Sales Contract"];
const appScript = fs.readFileSync(path.join(doctypeDir, "pz_sales_contract/pz_sales_contract.js"), "utf8");
const nativeSources = ["model/model.js", "form/script_manager.js", "form/form.js", "form/save.js"]
  .map((name) => {
    const filename = path.join(frappeApp, "frappe/public/js/frappe", name);
    // Form imports install UI components that are not involved in this test.
    // Evaluate the original save/model/event functions, without rewriting them.
    return [filename, fs.readFileSync(filename, "utf8").replace(/^import .*;\n/gm, "")];
  });
const flush = () => new Promise((resolve) => setImmediate(resolve));

function nativeDesk({ nativeRequests = false } = {}) {
  const locals = {}, requests = [], saves = [], messages = [], errors = [], transports = [];
  const ajaxSend = [], ajaxComplete = [];
  const ctx = {
    console: { log() {}, error(error) { errors.push(error); } },
    Promise, Set, WeakMap, Object, Array, JSON, locals,
    cur_frm: null, window: {}, document: {}, history: { replaceState() {} },
    __: (value) => value, toTitle: (value) => value,
    is_null: (value) => value === undefined || value === null || value === "",
  };
  const jq = () => ({
    prop() { return this; }, addClass() { return this; }, trigger() { return this; },
    attr() { return this; },
    ajaxSend(callback) { ajaxSend.push(callback); },
    ajaxComplete(callback) { ajaxComplete.push(callback); },
  });
  jq.extend = Object.assign;
  jq.each = (obj, fn) => {
    for (const [key, value] of Object.entries(obj)) if (fn(key, value) === false) break;
  };
  jq.isPlainObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  jq.isArray = Array.isArray;
  jq.ajax = (options) => {
    const callbacks = [];
    const transport = {
      options,
      done(callback) { callbacks.push(["done", callback]); return this; },
      always(callback) { callbacks.push(["always", callback]); return this; },
      fail(callback) { callbacks.push(["fail", callback]); return this; },
      async finish(data, failure = false) {
        const xhr = {
          responseJSON: data, responseText: JSON.stringify(data),
          statusCode: () => ({ status: failure ? 500 : 200 }),
          getResponseHeader: () => "application/json",
        };
        const args = failure ? [xhr, "error"] : [data, "success", xhr];
        // jQuery runs registered always and done/fail callbacks in order.
        for (const [kind, callback] of callbacks) {
          if (kind === "always" || kind === (failure ? "fail" : "done")) callback(...args);
        }
        for (const callback of ajaxComplete) callback();
        await flush();
      },
    };
    transports.push(transport);
    for (const callback of ajaxSend) callback();
    return transport;
  };
  ctx.$ = jq;

  const frappe = ctx.frappe = {
    provide(name) {
      let out = ctx;
      for (const part of name.split(".")) out = out[part] ||= {};
    },
    run_serially: (tasks) => tasks.reduce((promise, task) => promise.then(task), Promise.resolve()),
    after_server_call() {
      return frappe.request.ajax_count
        ? new Promise((resolve) => frappe.request.waiting_for_ajax.push(resolve)) : null;
    },
    request: { ajax_count: 0, waiting_for_ajax: [] },
    user: { has_role: () => false }, is_online: () => true,
    session: { user: "Synthetic User", logged_in_user: "Synthetic User" },
    show_alert(message) { messages.push(message); },
    msgprint(message) { messages.push(message); },
    throw(message) { messages.push(message); throw new Error(message); },
    meta: {
      docfield_list: Object.fromEntries(Object.entries(schemas).map(([dt, value]) => [dt, value.fields])),
      get_docfield_copy: (dt) => Object.fromEntries(schemas[dt].fields.map((field) => [field.fieldname, field])),
      get_docfield: (dt, name) => schemas[dt].fields.find((field) => field.fieldname === name),
    },
    get_meta: (dt) => schemas[dt], get_route: () => [], route_history: [], route_hooks: {},
    utils: { play_sound() {}, eval(expression, data) { return vm.runInNewContext(expression, data); } },
    call(options) {
      if (options.method === "frappe.desk.form.save.savedocs") {
        saves.push(JSON.parse(JSON.stringify(options.args.doc)));
        // Native model sync makes this a saved snapshot before after_save/refresh.
        options.args.doc.__islocal = 0;
        options.args.doc.__unsaved = 0;
        options.callback({});
        options.always({});
      } else requests.push(options);
    },
  };
  vm.createContext(ctx);
  for (const [filename, source] of nativeSources) vm.runInContext(source, ctx, { filename });
  if (nativeRequests) {
    const interceptedCall = frappe.call;
    const filename = path.join(frappeApp, "frappe/public/js/frappe/request.js");
    vm.runInContext(fs.readFileSync(filename, "utf8"), ctx, { filename });
    const requestCall = frappe.call;
    frappe.call = (options) => options.method === "frappe.desk.form.save.savedocs"
      ? interceptedCall(options) : requestCall(options);
  }
  vm.runInContext(appScript, ctx, { filename: "pz_sales_contract.js" });

  const doc = {
    doctype: schema.name, name: "new-contract", __islocal: 1,
    __unsaved: 1, docstatus: 0, company: "Company A",
  };
  for (const field of schema.fields) if ((field.reqd || field.mandatory_depends_on) && !doc[field.fieldname]) {
    doc[field.fieldname] = ["Float", "Currency"].includes(field.fieldtype) ? 1 : "Synthetic A";
  }
  Object.assign(doc, {
    seller_address: "Address A", seller_signatory: "Signer A", seller_position: "Position A",
    currency: "USD", conversion_rate: 1, bank_receiving_account: "Bank A", cash_receiving_account: null,
    incoterm: "FOB", contract_location: "Synthetic Location",
  });
  locals[doc.doctype] = { [doc.name]: doc };
  for (const [fieldname, dt] of [["items", "PZ Contract Item"], ["specifications", "PZ Contract Specification"]]) {
    const child = {
      doctype: dt, name: `new-${fieldname}`, parent: doc.name,
      parenttype: doc.doctype, parentfield: fieldname, idx: 1,
    };
    for (const field of schemas[dt].fields) if (field.reqd) {
      child[field.fieldname] = ["Float", "Currency"].includes(field.fieldtype) ? 1 : "Synthetic A";
    }
    doc[fieldname] = [child];
    locals[dt] = { [child.name]: child };
  }
  const frm = Object.create(frappe.ui.form.Form.prototype);
  Object.assign(frm, {
    doc, docname: doc.name, doctype: doc.doctype, meta: schema,
    cscript: {}, events: {}, wrapper: {}, fields_dict: {},
    set_query() {}, set_intro() {}, add_custom_button() {}, show_success_action() {},
    validate_form_action() {}, scroll_to_field() { return true; },
    refresh() { return this.script_manager.trigger("refresh"); },
  });
  for (const field of schema.fields) if (field.fieldtype !== "HTML") frm.fields_dict[field.fieldname] = { df: field };
  frappe.ui.form.close_grid_form = () => {};
  frm.script_manager = new frappe.ui.form.ScriptManager({ frm });
  ctx.cur_frm = frm;
  frappe.model.on(doc.doctype, "*", (fieldname, value, changed) => {
    if (changed.name === frm.docname) return frm.script_manager.trigger(fieldname, changed.doctype, changed.name);
  });
  return {
    frm, frappe, requests, saves, messages, errors, transports,
    async setup() { await frm.script_manager.trigger("setup"); },
    async respond(values, index = requests.length - 1) {
      requests[index].callback({ message: values }); await flush();
    },
    async releaseAjax() {
      frappe.request.ajax_count = 0;
      for (const resolve of frappe.request.waiting_for_ajax.splice(0)) resolve();
      await flush();
    },
    async save() {
      // Keep the native promise/error flow, but don't hang on native mandatory
      // failure (which intentionally leaves its outer save promise unresolved).
      frm.save("Save", null, null, () => {});
      await flush();
    },
  };
}

test("new contract boot metadata hides FX and price-list inputs before form refresh", async () => {
  const ui = nativeDesk();
  assert.equal(ui.frm.fields_dict.conversion_rate.df.hidden, 1);
  assert.equal(ui.frm.fields_dict.selling_price_list.df.hidden, 1);
  await ui.frm.refresh(); await flush();
  assert.equal(ui.frm.fields_dict.conversion_rate.df.hidden, 1);
  assert.equal(ui.frm.fields_dict.selling_price_list.df.hidden, 1);
});

test("native Save requires a replacement after a disallowed Incoterm is cleared", async () => {
  const ui = nativeDesk(); await ui.setup();
  ui.frm.doc.incoterm = "FCA";
  await ui.frm.refresh(); await flush(); await ui.respond({});
  assert.equal(ui.frm.doc.incoterm, null);
  assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), false);
  await ui.save();
  assert.equal(ui.saves.length, 0);
  await ui.frm.set_value("incoterm", "EXW");
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].incoterm, "EXW");
});

test("native Save cannot overtake a paused Company clear", async () => {
  const ui = nativeDesk(); await ui.setup();
  const { frm, frappe } = ui;
  frappe.request.ajax_count = 1;
  frm.set_value("company", "Company B"); await flush();
  assert.equal(frm.doc.seller_address, null);
  assert.equal(frm.doc.seller_signatory, "Signer A");
  assert.ok(frm._pzCompanyDefaultsPendingClear);
  frm.set_value("seller_address", "Address B");
  frm.set_value("bank_receiving_account", "Bank B"); await flush();
  assert.equal(frappe.ui.form.check_mandatory(frm), true);
  await ui.save();
  assert.equal(ui.saves.length, 0, "never serialize stale seller values with Company B");
  assert.ok(frm.is_new());
  assert.match(String(ui.messages.at(-1)), /Company details.*updating/i);

  await ui.releaseAjax();
  assert.equal(frm.doc.seller_position, null);
  const profileB = Object.fromEntries(schema.fields.filter((field) => field.reqd)
    .map((field) => [field.fieldname, ["Float", "Currency"].includes(field.fieldtype) ? 1 : "Synthetic B"]));
  Object.assign(profileB, {
    seller_address: "Address B", seller_signatory: "Signer B", seller_position: "Position B",
    currency: "USD", conversion_rate: 1, bank_receiving_account: "Bank B",
  });
  await ui.respond(profileB);
  assert.equal(ui.saves.length, 0, "finishing defaults must not silently resume the rejected Save");
  await ui.save();
  assert.equal(ui.saves.length, 1, "an explicit retry succeeds after clearing/defaults finish");
  assert.equal(ui.saves[0].company, "Company B");
  assert.equal(ui.saves[0].seller_signatory, "Signer B");
  assert.equal(ui.saves[0].seller_position, "Position B");
  assert.equal(ui.saves[0].seller_address, "Address B");
  assert.equal(ui.saves[0].bank_receiving_account, "Bank B");
});

for (const result of ["empty", "failed"]) {
  test(`native Save blocks pending optional defaults, then permits manual entry after ${result} results`, async () => {
    const ui = nativeDesk(); await ui.setup();
    await ui.frm.refresh(); await flush();
    assert.equal(ui.requests.length, 1);
    assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), true);
    await ui.save();
    assert.equal(ui.saves.length, 0);
    if (result === "empty") await ui.respond({});
    else { ui.requests[0].error(); await flush(); }
    // The clean before_save path must not wait on unrelated AJAX after its
    // guard. Real ScriptManager treats an explicitly returned promise specially.
    ui.frappe.request.ajax_count = 1;
    await ui.save();
    assert.equal(ui.saves.length, 1);
    assert.equal(ui.saves[0].seller_signatory, "Signer A");
    await ui.releaseAjax();
  });
}

test("native Save is blocked until a profile's asynchronous field application finishes", async () => {
  const ui = nativeDesk();
  ui.frm.doc.seller_signatory = null;
  await ui.setup(); await ui.frm.refresh(); await flush();
  ui.frappe.request.ajax_count = 1;
  await ui.respond({ seller_signatory: "Profile Signer A" });
  assert.equal(ui.frm.doc.seller_signatory, "Profile Signer A");
  assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), true);
  await ui.save();
  assert.equal(ui.saves.length, 0);
  await ui.releaseAjax();
  assert.equal(ui.saves.length, 0);
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].seller_signatory, "Profile Signer A");
});

for (const exception of ["QueryTimeoutError", "QueryDeadlockError"]) {
  test(`native ${exception} handling releases completed optional-default work`, async () => {
    const ui = nativeDesk({ nativeRequests: true }); await ui.setup();
    ui.frm.refresh(); await flush();
    assert.equal(ui.transports.length, 1);
    await ui.transports[0].finish({ exception: `frappe.exceptions.${exception}: Synthetic failure` }, true);
    assert.equal(ui.frappe.request.ajax_count, 0);
    assert.equal(ui.frm._pzCompanyDefaultsWork.size, 0);
    await ui.save();
    assert.equal(ui.saves.length, 1, "failed optional defaults must not block manual saving forever");
  });
}

test("native request completion cannot release an ongoing successful defaults application", async () => {
  const ui = nativeDesk({ nativeRequests: true });
  ui.frm.doc.seller_signatory = null;
  await ui.setup(); ui.frm.refresh(); await flush();
  // Keep another native AJAX event outstanding after the defaults response.
  ui.frappe.request.ajax_count++;
  await ui.transports[0].finish({ message: { seller_signatory: "Profile Signer A" } });
  assert.equal(ui.frappe.request.ajax_count, 1);
  assert.equal(ui.frm.doc.seller_signatory, "Profile Signer A");
  await ui.save();
  assert.equal(ui.saves.length, 0);
  await ui.releaseAjax();
  await ui.save();
  assert.equal(ui.saves.length, 1);
});


test("native party mandatory checks accept phone-only contact and block missing buyer details", async () => {
  const ui = nativeDesk(); await ui.setup(); await ui.frm.refresh(); await flush(); await ui.respond({});
  ui.frm.doc.buyer_email_phone = "00971 505 65 1305";
  ui.frm.doc.customer_address = null;
  ui.frm.doc.contact_person = null;
  ui.frm.doc.seller_address = null;
  assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), true);
  ui.frm.doc.customer_name = "";
  await ui.save();
  assert.equal(ui.saves.length, 0);
  ui.frm.doc.customer_name = "Entered Buyer";
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].buyer_email_phone, "00971 505 65 1305");
});


test("native Save permits optional buyer details blank but still requires primary phone", async () => {
  const ui = nativeDesk(); await ui.setup(); await ui.frm.refresh(); await flush(); await ui.respond({});
  ui.frm.doc.customer_tax_id = null;
  ui.frm.doc.buyer_email_phone = "";
  assert.equal(ui.frm.fields_dict.customer_tax_id.df.reqd, false);
  assert.equal(ui.frm.fields_dict.buyer_email_phone.df.reqd, false);
  assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), true);
  ui.frm.doc.buyer_phone = "";
  await ui.save();
  assert.equal(ui.saves.length, 0);
  ui.frm.doc.buyer_phone = "0012345678";
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].customer_tax_id, null);
  assert.equal(ui.saves[0].buyer_email_phone, "");
});


test("native Save permits empty optional payment instructions and free-text bank", async () => {
  const ui = nativeDesk(); await ui.setup(); await ui.frm.refresh(); await flush(); await ui.respond({});
  for (const field of ["bank_receiving_account", "cash_receiving_account", "beneficiary", "bank_branch", "account_iban", "swift_reference"]) {
    ui.frm.doc[field] = "";
    assert.equal(ui.frm.fields_dict[field].df.reqd, false);
  }
  assert.equal(ui.frappe.ui.form.check_mandatory(ui.frm), true);
  ui.frm.doc.bank_receiving_account = "Synthetic unlinked bank text";
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].bank_receiving_account, "Synthetic unlinked bank text");
});


test("native Save preserves all optional payment fields cleared before defaults arrive", async () => {
  const ui = nativeDesk();
  const fields = ["bank_receiving_account", "cash_receiving_account", "beneficiary", "bank_branch", "account_iban", "swift_reference"];
  for (const field of fields) ui.frm.doc[field] = `Initial ${field}`;
  await ui.setup();
  await ui.frm.refresh(); await flush();
  for (const field of fields) await ui.frm.set_value(field, "");
  await ui.respond({ currency: "USD", ...Object.fromEntries(fields.map(field => [field, `Configured ${field}`])) });
  await ui.save();
  assert.equal(ui.saves.length, 1);
  for (const field of fields) assert.equal(ui.saves[0][field], "", field);
});

test("native Save persists the manually selected Print as Draft checkbox without payment state", async () => {
  const ui = nativeDesk(); await ui.setup(); await ui.frm.refresh(); await flush(); await ui.respond({});
  assert.equal(ui.frm.fields_dict.print_as_draft.df.fieldtype, "Check");
  assert.equal(String(ui.frm.fields_dict.print_as_draft.df.default || "0"), "0");
  ui.frm.doc.print_as_draft = 1;
  await ui.save();
  assert.equal(ui.saves.length, 1);
  assert.equal(ui.saves[0].print_as_draft, 1);
});
