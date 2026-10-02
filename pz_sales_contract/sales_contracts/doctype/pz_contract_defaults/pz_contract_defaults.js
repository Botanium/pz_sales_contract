frappe.ui.form.on("PZ Contract Defaults", {
	setup(frm) {
		frm.set_query("seller_address", () => ({
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: { link_doctype: "Company", link_name: frm.doc.company },
		}));
		frm.set_query("bank_receiving_account", () => ({
			filters: { company: frm.doc.company, account_type: "Bank", is_group: 0, disabled: 0 },
		}));
		frm.set_query("cash_receiving_account", () => ({
			filters: { company: frm.doc.company, account_type: "Cash", is_group: 0, disabled: 0 },
		}));
		frm.set_query("selling_price_list", () => ({ filters: { enabled: 1, selling: 1 } }));
	},
	refresh(frm) {
		if (!frm.is_new()) frm.set_df_property("company", "read_only", 1);
	},
});
