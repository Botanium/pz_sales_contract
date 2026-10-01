# Validation evidence

## Dedicated app permissions (2026-10-01)

- A native regression first failed with 20 generic-role access assertions against the previous permissions and passed after replacing them with dedicated `PZ Sales Contract User` and `PZ Sales Contract Manager` permissions. Generic Sales User, Sales Manager, Accounts Manager and System Manager users have no contract access; Administrator retains native full access.
- 23 native integration tests and 6 calendar tests passed in a new isolated Docker bench at Frappe `f3f0c0b13c77a419487150a198fed42964e1919e` (16.36.0), ERPNext `af63cde4941570ec7b9e12422c68302762cfcf91` (16.37.0), Python 3.14.7 and MariaDB 11.8. App manager permissions include create/read/write/submit/cancel/amend/print and add no finance-history, payment or registry permissions.
- On a second disposable ERPNext site, fresh app installation and two subsequent migrations created the dedicated roles, preserved all existing user role assignments, denied generic-role contract access, preserved Administrator access, and retained finance-history rights for the existing finance role.
- Four synthetic native Frappe HTML/PDF cases were rendered with both patched-Qt wkhtmltopdf 0.12.5 (official focal amd64 build in a network-isolated container) and 0.12.6.1. The native PDF options were preserved and built CSS inlined for offline rendering. First draft, paid and returning contracts have 6 pages each; a 30-item draft has 8. Extracted text lengths match per case, complete terms/schedules/signatures appear, unpaid DRAFT markers occur on every page, and paid/returning outputs have no DRAFT marker. All 26 pages from the 0.12.5 outputs were visually inspected; no clipping, overlap, broken tables or missing signature areas were found.
- This validates the isolated 0.12.5 renderer, not the actual production binary, installed Qt patch status, fonts or hook ordering. No production contracts, transactions, customer designations, user-role changes or app installation were performed during these checks.

The app was tested on the connected MacBook using **two disposable sites** in the existing v16 Docker development bench, including a fresh ERPNext site without setup-wizard data. The existing weighbridge pilot site, records and installed-app configuration were not changed. No production installation, customer delivery or signing took place.

## Tested versions

- ERPNext **16.37.0**, commit `af63cde4941570ec7b9e12422c68302762cfcf91`
- Frappe **16.36.0**, commit `f3f0c0b13c77a419487150a198fed42964e1919e`
- Python **3.14.7** in the bench; native wkhtmltopdf **0.12.6.1 with patched Qt**

## Executed checks

- **22 native integration tests passed** after final payment, calendar and print changes. They cover native Customer/Item links and arithmetic, two-/three-decimal monetary print and evidence display with exact partial-payment thresholds, role permissions, first/returning customers, immutable reservation, Customer rename, cancellation/amendment, submitted versus draft/cancelled payments, 299 + 1 cash threshold, manual clearance rejection, full bank reconciliation, native advance reconciliation into Sales Invoice, unrelated party/company/currency, nominated receiving accounts, unagreed cash, restricted finance migration, paid/unpaid/draft/partial/cancelled historical receipts, denied Sales-user history designation, current-order override rejection, active historical designation replacement/cancellation, historical customer/receipt scope, frozen submitted holiday calendars, complete HTML terms and alternate renderer/payload guards.
- **6 business-hour unit tests passed**, including holidays/weekends, outside-hour notices, exhausted calendar, missing offset, MariaDB time roundtrip and DST folds. A 24-business-hour deadline accumulates actual open hours.
- A **real two-process database test passed**: two simultaneous inserts produced one registry and one first family. One transaction retried after native MariaDB snapshot conflict; a failed attempt rolled back cleanly.
- Native PDF exports passed explicit content/state checks: unpaid first contract **6 pages**, advance-confirmed first contract **6 pages**, returning customer **6 pages**, and 30-line unpaid first contract **8 pages**. Every unpaid continuation page includes DRAFT. All 15 clauses, specifications, payment instructions and signature areas are present. All six ordinary contract pages were visually inspected; no customer data or real payment instructions were used.
- The same **22 native tests passed on the fresh site**. Synthetic fixtures supply the native setup prerequisites for Customer groups, Territory, Item groups, Customer/Receivable Party Type, Transit Warehouse Type and a default address template. Native invoice advance reconciliation remained part of the suite.
- Browser QA used an ephemeral synthetic Sales User session: linked contract form, server advance-evidence dialog, currency display and enforced Standard print preview were checked. Temporary browser credentials and UI services were removed afterward. The temporary UI proxy did not provide realtime sockets; console socket errors were unrelated to contract form/print checks.
- Two independent reviewers examined permissions, payment evidence and print enforcement. Material findings were fixed and affected native checks rerun.

Run native tests on a disposable v16 site with `allow_tests` enabled:

```sh
bench --site TEST_SITE run-tests --app pz_sales_contract
python -m unittest discover -s tests -v
```

`pz_sales_contract.demo.export` and `.concurrency` refuse sites outside the disposable `pz-contract-test.*` / `pz-contract-ci.*` naming scope. Export temporarily permits repeated item rows on that test site and restores its prior setting. It creates only synthetic records.

## Practical limits

Verified pre-install history can be registered through the restricted PZ Customer History finance workflow. It requires identified contract evidence, a submitted matching native Sales Order and a qualifying full30% historical advance. It is never guessed from Customer existence, an invoice balance or a sales checkbox; no production scan was performed. Without such a designation, the first app family is reserved. The migration's native receipt evidence is rechecked live, and cancellation restores that original family. Later contracts deliberately remain unmarked even if the first advance is pending. The reservation persists an accidental first draft, cancellation and amendment.

Bank receipts require full native reconciliation of the receipt before its contract allocation counts. Finance-submitted Cash receipts to the agreed genuine Cash account qualify. Bookkeeping evidence does not independently verify physical cash or authenticate bank instructions. Cross-currency receipts, mixed-order invoices and Journal Entries are unsupported and fail closed. Administrators remain trusted; downloaded PDFs can be altered outside the app.

No production records were changed to test. No live historical customer classification or migration was performed. The app supports additional exclusive Actual/On Net Total taxes, net-total discount, and same-day business schedules. Native beta/WeasyPrint/Chrome contract PDF paths are rejected because they bypass Frappe's enforced body hook. Existing custom integrations that use those renderers must use native wkhtmltopdf.

GitHub CI creates its own fresh v16 bench and synthetic site; its status is visible on the draft pull request. A local native pass does not imply a future CI run passed.
