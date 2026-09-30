# Implementation specification

User-authorized scope: implement, test and publish this dedicated app in public Botanium/pz_sales_contract. Production installation/deployment, sending contracts and signing contracts remain excluded.

- Sales team selects ERPNext Customer, Item and linked details; quantity/UOM/grade/packaging/rate/currency/tax/discount/totals and Incoterm plus named place are captured.
- All 15 full clauses and supplied signature/specification/payment sections preserve the supplied branded five-page master’s commercial meaning. Capture referenced missing Commercial Schedule inputs; invent no legal terms, fees, calendars, jurisdiction or deadlines.
- Attractive branded print/PDF with supplied logo, clean pagination, full terms/specifications and signatures.
- First contract ONLY per customer bears conspicuous DRAFT until the full required 30% advance, not a token partial payment. Separate this business marker from ERP docstatus.
- Enforce on server and all native app prints using submitted/noncancelled appropriately allocated receipt and clearance/reconciliation evidence. Cash uses native restricted-finance submitted receipt and GL evidence; FX must follow native semantics or explicitly fail closed.
- Handle cancellations, amendments, concurrency, duplicate allocations and company/currency isolation. Describe second-contract-before-first-advance bypass without adding an unauthorized later-contract restriction.
- Feature branch and draft PR; preserve unrelated repos/work; public staged diff has no credentials, real customer/payment records, dumps or Library metadata.
- Native v16 integration in a disposable site with synthetic fixtures; permission, first/returning, draft/cancelled/submitted receipts, insufficient advances, cancellation, arithmetic and print/PDF tests. Verify exact remote commit and CI.

The readable master SHA and transcription provenance are in master-provenance.md. README records implementation decisions and explicit limitations.
