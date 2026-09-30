# Petrol Zone Sales Contracts

A dedicated Frappe app for ERPNext v16. Sales users choose ERP Customers, Addresses, Contacts, Items, UOMs and Incoterms; managers submit contracts and their linked native Sales Orders. The supplied branded master’s complete 15 clauses, product specifications, Commercial Schedule, payment instructions and signature areas appear in the print/PDF.

## Payment DRAFT policy

The **first contract family saved using this app per Customer, across companies** has a conspicuous payment DRAFT header until the full **30% advance** is evidenced. ERP `docstatus` is separate. Later contracts have no payment DRAFT header, even if the first remains unpaid. Consequently a second-contract-before-first-payment bypass is possible under the user’s first-contract-only policy; this app does not silently add a credit/release restriction.

The first family is reserved transactionally using a Customer row lock, a locking current registry read and a unique Customer index. A simultaneous save may require a retry under MariaDB snapshot isolation; the losing transaction rolls back rather than creating a second first family. Its customer/company cannot change; deletion is blocked. Native Customer rename preserves the unique Customer link reservation. Cancelled contracts retain the reservation and print CANCELLED. Cancellation also cancels the generated Sales Order transactionally; native permissions and active downstream payment/invoice/delivery links can block cancellation until finance unwinds them. Amendments inherit the first family but generate a new Sales Order and require allocations to that new order. An accidental first draft therefore remains in the audit trail: cancel/amend for the same customer, or create a later contract. This deliberate tradeoff prevents deletion/cancellation from resetting customer identity.

**Historical scope:** an existing Customer master alone does not make a customer returning. This version does not infer pre-install contract history from invoices, receipts or old external PDFs, and offers no history override checkbox. A proven first contract outside this app will therefore require an administrator/finance rollout review; its historical receipt cannot clear the new app contract's marker without a valid allocation to this app's submitted order. No automatic migration or live history scan is performed. Treat this as a first-contract-in-this-app policy until an explicitly reviewed historical migration is implemented.

Payment evidence is computed live on the server and at print time. Receipts must be submitted, uncancelled native Payment Entries, positive Receive/Customer entries, correct company and party, received into the nominated Bank account or optional agreed Cash account on the contract, allocated to the submitted contract Sales Order or a submitted non-return invoice whose every line belongs to that order. Native advance reconciliation into such an invoice remains eligible. Each payment is counted once and capped by its receipt. Mixed-order invoices fail closed. Bank receipts require matching submitted deposit Bank Transactions, correct company/account/currency, full receipt reconciliation, live bank GL and clearance date. Manual clearance dates alone do not qualify. Cash receipts to genuine ERP Cash accounts use submitted finance accounting and live Cash GL as evidence of receipt. This is bookkeeping evidence, not independent physical verification.

**Foreign exchange limitation:** only receipts whose party and receiving accounts both use the contract currency and whose paid/received amounts match are eligible. Cross-currency receipts fail closed; there is no conversion based on a guessed exchange rate. Contracts themselves can use native ERP exchange rates. Journal Entries, payment requests, cancelled/return invoices, wallet credits, historical pre-app customer transactions and generic unallocated balances do not clear this marker.

The marker is an anti-abuse cue, not a cryptographic signature or a guarantee that a downloaded PDF cannot be altered. Administrators and database operators remain trusted. Keep native payment and bank-reconciliation permissions restricted to finance. Managers must independently verify the printed bank instructions against the nominated receiving account before submission; ERP receipt evidence does not authenticate those instructions.

## Commercial inputs

No holiday calendar, legal jurisdiction, fee or deadline is invented. The contract requires an explicit IANA time zone, weekday schedule, opening/closing times, Holiday List, collection grace amount/unit, charge bases/caps (or expressly none), cure/claim/force-majeure periods, measurement/tolerance, delivery/transport/insurance and law/courts. Overnight business hours are unsupported in this version. DST ambiguous boundaries use the first occurrence; nonexistent opening/closing times are rejected. `24 business hours` means accumulated actual open hours, not a clock day. Notice timestamps require ISO 8601 offsets and reliable written delivery evidence. Deadlines are resolved within the supplied Holiday List’s valid range. Submission freezes its agreed dates and validity range on the contract; later calendar-master edits do not change its deadlines or printed agreement. Approval timestamps record supplied written approvals; saving/submitting does not sign or send a contract.

The supplied 30%/70% percentages are fixed because both the master’s legal clause and signature acknowledgement state them. Additional exclusive Actual or On Net Total taxes/charges and net-total discounts use native Sales Order calculations. Inclusive taxes and compound tax rows are rejected explicitly. Grade, packaging and agreed specification reference are completed per selected ERP Item. No mixed-UOM quantity total is shown.

## Installation (administrator action)

Production installation was not performed. On a separately approved v16 bench:

```sh
bench get-app https://github.com/Botanium/pz_sales_contract --branch feature/bitumen-sales-contract
bench --site YOUR_SITE install-app pz_sales_contract
bench --site YOUR_SITE migrate
bench build --app pz_sales_contract
```

Requires Frappe/ERPNext `>=16,<17`, Python 3.14 and the bench wkhtmltopdf PDF engine. Use Sales User for create/read/print; Sales Manager **plus Sales User** for submission/cancellation/amendment and native master access; Accounts Manager for read/print. Submission also requires native Sales Order create/submit permission. The app grants no finance permissions. Configure Company selling defaults, accounts, price lists, master links, Incoterms and the agreed Holiday List in ERPNext. Enable draft print in native Print Settings if preliminary contracts must be printed.

All supported native contract print formats are routed through the mandatory app template with a freshly loaded persisted document. Native beta print builders, direct WeasyPrint downloads and the optional Chrome PDF renderer are explicitly rejected at configuration/request boundaries; scalar and dictionary batch requests are covered. Unsaved print payloads, client-supplied paid flags and alternate Standard formats cannot remove the marker from app-generated output. Other DocTypes retain Frappe’s ordinary print behavior.

## Validation

See [validation.md](docs/validation.md) for exact tested versions, outcomes, evidence and limitations. Synthetic integration tests live beside the DocType, and pure business-hour tests are in `tests/`. No production records, customer contracts, signatures or payment details are included in this repository.
