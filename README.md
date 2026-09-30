# Petrol Zone Sales Contracts

A dedicated Frappe app for ERPNext v16. Sales users choose ERP Customers, Addresses, Contacts, Items, UOMs and Incoterms; managers submit contracts and their linked native Sales Orders. The supplied branded master’s complete 15 clauses, product specifications, Commercial Schedule, payment instructions and signature areas appear in the print/PDF.

## Payment DRAFT policy

The **first saved contract family per Customer, across companies** has a conspicuous payment DRAFT header until the full **30% advance** is evidenced. ERP `docstatus` is separate. Later contracts have no payment DRAFT header, even if the first remains unpaid. Consequently a second-contract-before-first-payment bypass is possible under the user’s first-contract-only policy; this app does not silently add a credit/release restriction.

The first family is reserved transactionally using a Customer row lock. Its customer/company cannot change; deletion is blocked. Cancelled contracts retain the reservation and print CANCELLED. Amendments inherit the first family but generate a new Sales Order and require allocations to that new order. An accidental first draft therefore remains in the audit trail: cancel/amend for the same customer, or create a later contract. This deliberate tradeoff prevents deletion/cancellation from resetting customer identity.

Payment evidence is computed live on the server and at print time. Receipts must be submitted, uncancelled native Payment Entries, positive Receive/Customer entries, correct company and party, allocated to the submitted contract Sales Order or a submitted non-return invoice whose every line belongs to that order. Native advance reconciliation into such an invoice remains eligible. Each payment is counted once and capped by its receipt. Mixed-order invoices fail closed. Bank receipts require matching submitted deposit Bank Transactions, correct company/account/currency, full receipt reconciliation, live bank GL and clearance date. Manual clearance dates alone do not qualify. Cash receipts to genuine ERP Cash accounts use submitted finance accounting and live Cash GL as evidence of receipt. This is bookkeeping evidence, not independent physical verification.

**Foreign exchange limitation:** only receipts whose party and receiving accounts both use the contract currency and whose paid/received amounts match are eligible. Cross-currency receipts fail closed; there is no conversion based on a guessed exchange rate. Contracts themselves can use native ERP exchange rates. Journal Entries, payment requests, cancelled/return invoices, wallet credits, historical pre-app customer transactions and generic unallocated balances do not clear this marker.

The marker is an anti-abuse cue, not a cryptographic signature or a guarantee that a downloaded PDF cannot be altered. Administrators and database operators remain trusted. Keep native payment and bank-reconciliation permissions restricted to finance.

## Commercial inputs

No holiday calendar, legal jurisdiction, fee or deadline is invented. The contract requires an explicit IANA time zone, weekday schedule, opening/closing times, Holiday List, collection grace amount/unit, charge bases/caps (or expressly none), cure/claim/force-majeure periods, measurement/tolerance, delivery/transport/insurance and law/courts. Overnight business hours are unsupported in this version. `24 business hours` means accumulated actual open hours, not a clock day. Notice timestamps require ISO 8601 offsets and reliable written delivery evidence. Deadlines are resolved within the supplied Holiday List’s valid range. Approval timestamps record supplied written approvals; saving/submitting does not sign or send a contract.

The supplied 30%/70% percentages are fixed because both the master’s legal clause and signature acknowledgement state them. Additional exclusive Actual or On Net Total taxes/charges and net-total discounts use native Sales Order calculations. Inclusive taxes and compound tax rows are rejected explicitly. Grade, packaging and agreed specification reference are completed per selected ERP Item. No mixed-UOM quantity total is shown.

## Installation (administrator action)

Production installation was not performed. On a separately approved v16 bench:

```sh
bench get-app https://github.com/Botanium/pz_sales_contract --branch feature/bitumen-sales-contract
bench --site YOUR_SITE install-app pz_sales_contract
bench --site YOUR_SITE migrate
bench build --app pz_sales_contract
```

Requires Frappe/ERPNext `>=16,<17`, Python 3.14 and the bench PDF engine. Use Sales User for create/read/print; Sales Manager for submission/cancellation/amendment; Accounts Manager for read/print. Submission also requires native Sales Order create/submit permission. The app grants no finance permissions. Configure Company selling defaults, accounts, price lists, master links, Incoterms and the agreed Holiday List in ERPNext. Enable draft print in native Print Settings if preliminary contracts must be printed.

All native contract print formats are routed through the mandatory app template with a freshly loaded persisted document. Unsaved print payloads, client-supplied paid flags and alternate Standard formats cannot remove the marker from app-generated output. Other DocTypes retain Frappe’s ordinary print behavior.

## Validation

See [validation.md](docs/validation.md) for exact tested versions, outcomes, evidence and limitations. Synthetic integration tests live beside the DocType, and pure business-hour tests are in `tests/`. No production records, customer contracts, signatures or payment details are included in this repository.
