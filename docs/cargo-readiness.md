# Cargo readiness and seller responsibilities

Requested scope: seller arranges and pays factory cargo loading; seller handles and pays Iraqi export customs formalities, documentation and applicable manifest/customs charges. New v6 terms append clause 16 to the approved v5 clauses. The optional clause 17 states cargo ready for loading within the entered calendar days after receipt of the agreed advance payment. This is cargo readiness, not FOB delivery. Incoterm choices, risk terms, USD entry policy, stamp and payment percentage options remain unchanged. Planned Delivery Date remains removed.

Cargo Ready Within (Days) has no default and is optional. Native Int zero means cleared/omitted; positive whole calendar days are freely entered within native database integer capacity. Blank/zero omits clause 17. With 0% advance, clause 17 is omitted even if days are stored; the form explicitly explains this. No replacement trigger or deadline is inferred. Restoring a positive advance on an editable v6 draft regenerates the clause from its saved days.

New families use v6. Existing v1-v5 records and amendments retain their saved wording; fallback rendering uses their immutable version archive. Existing v5 drafts can still adjust advance percentages using v5 wording. v6 draft families can edit readiness; submitted records and amendments freeze it. No migration backfills days or rewrites terms. Print uses the persisted snapshot and the existing private stamp path.

Review consideration: supplementing an EXW contract with seller-paid loading and export clearance may conflict with the ordinary EXW allocation. The app retains the operator's Incoterm and the approved delivery/risk clauses; no automatic replacement is made. The parties should review that combination before signing.

Deployment to Frappe Cloud TEST and production is owned by Botan and excluded from this implementation.
