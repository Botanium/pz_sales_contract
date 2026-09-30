# Validation evidence

The app was tested on the connected MacBook using a **new disposable site** in the existing v16 Docker development bench. The existing weighbridge pilot site, records and installed-app configuration were not changed. No production installation, customer delivery or signing took place.

## Tested versions

- ERPNext **16.37.0**, commit `af63cde4941570ec7b9e12422c68302762cfcf91`
- Frappe **16.36.0**, commit `f3f0c0b13c77a419487150a198fed42964e1919e`
- Python **3.14.7** in the bench; native wkhtmltopdf **0.12.6.1 with patched Qt**

## Executed checks

- **21 native integration tests passed** after final payment, calendar and print changes. They cover native Customer/Item links and arithmetic, role permissions, first/returning customers, immutable reservation, Customer rename, cancellation/amendment, submitted versus draft/cancelled payments, 299 + 1 cash threshold, manual clearance rejection, full bank reconciliation, native advance reconciliation into Sales Invoice, unrelated party/company/currency, nominated receiving accounts, unagreed cash, restricted finance migration, paid/unpaid/draft/partial/cancelled historical receipts, denied Sales-user history designation, current-order override rejection, active historical designation replacement/cancellation, historical customer/receipt scope, frozen submitted holiday calendars, complete HTML terms and alternate renderer/payload guards.
- **6 business-hour unit tests passed**, including holidays/weekends, outside-hour notices, exhausted calendar, missing offset, MariaDB time roundtrip and DST folds. A 24-business-hour deadline accumulates actual open hours.
- A **real two-process database test passed**: two simultaneous inserts produced one registry and one first family. One transaction retried after native MariaDB snapshot conflict; a failed attempt rolled back cleanly.
- Native PDF exports passed explicit content/state checks: unpaid first contract **6 pages**, advance-confirmed first contract **6 pages**, returning customer **6 pages**, and 30-line unpaid first contract **8 pages**. Every unpaid continuation page includes DRAFT. All 15 clauses, specifications, payment instructions and signature areas are present. All six ordinary contract pages were visually inspected; no customer data or real payment instructions were used.
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
