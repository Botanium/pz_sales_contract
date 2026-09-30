frappe.ui.form.on("PZ Sales Contract", {
  setup(frm) {
    frm.set_query("customer_address", () => ({query: "frappe.contacts.doctype.address.address.address_query", filters: {link_doctype: "Customer", link_name: frm.doc.customer}}));
    frm.set_query("seller_address", () => ({query: "frappe.contacts.doctype.address.address.address_query", filters: {link_doctype: "Company", link_name: frm.doc.company}}));
    frm.set_query("contact_person", () => ({query: "frappe.contacts.doctype.contact.contact.contact_query", filters: {link_doctype: "Customer", link_name: frm.doc.customer}}));
    frm.set_query("item_code", "items", () => ({filters: {disabled: 0, is_sales_item: 1}}));
    frm.set_query("selling_price_list", () => ({filters: {enabled: 1, selling: 1}}));
  },
  refresh(frm) {
    frm.set_intro("Only the first contract family carries the payment DRAFT marker until 30% is allocated and bank reconciled. ERP submission is separate. Save before printing.");
    if (!frm.is_new()) frm.add_custom_button("Advance evidence", () => {
      frappe.call({method: "pz_sales_contract.payments.get_status", args: {name: frm.doc.name}, callback(r) {
        const s = r.message;
        frappe.msgprint({title: "Server payment evidence", message: `${s.payment_draft ? "DRAFT — advance pending" : "Payment marker clear / later contract"}<br>Reconciled: ${frappe.format(s.confirmed, {fieldtype: "Currency", options: frm.doc.currency})}<br>Required advance: ${frappe.format(s.required, {fieldtype: "Currency", options: frm.doc.currency})}<br>ERP status: ${["Unsubmitted", "Submitted", "Cancelled"][frm.doc.docstatus]}`});
      }});
    });
  },
  customer(frm) { frm.set_value({customer_address: null, contact_person: null}); },
  company(frm) { frm.set_value({seller_address: null}); }
});
frappe.ui.form.on("PZ Contract Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.item_code) frappe.db.get_value("Item", row.item_code, ["item_name", "description", "stock_uom"], r => {
      frappe.model.set_value(cdt, cdn, {item_name: r.item_name, description: r.description, uom: r.stock_uom});
    });
  }
});
