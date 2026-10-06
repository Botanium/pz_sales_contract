# Validation evidence

## Manual print draft policy (2026-10-06)

New and historical contracts use the saved `Print as Draft` checkbox, default unchecked, to control the printed DRAFT marker. Customer history and receipt state do not set the marker or block contract save, submit or print. Cancellation takes precedence in the print. The v2 30% / 70% terms remain unchanged; this removes payment-status warnings and automatic display decisions, not contract payment terms. Earlier sections below record checks under the policy active at the time and are historical evidence, not the current behavior.

- Local checks pass: **45 Python unit tests**, **39 Desk behavior tests**, and **15 native Frappe JavaScript save tests**, plus Python compilation, JavaScript syntax checks and `git diff --check`.
- This Mini has no local Frappe bench/database for the native server integration suite. The pushed commit's disposable v16 GitHub CI result is required before merge. PDF route tests verify native HTML rendering while mocking only the final wkhtmltopdf binary conversion boundary; no local PDF binary run is claimed.
- No production install, contract/payment record, receipt, ledger or permission change was made.

## Daily-entry form follow-up (2026-10-02)

- A further source-backed regression on `b7a57502948faa705ae722fe023b27b8f61ccba0` reproduced Save overtaking a paused Company change: mandatory checks passed with Company B's address/account but Company A's signer/legal text. The regression executes Frappe's actual model, ScriptManager, mandatory-check and save functions, intercepting every network write.
- Save now rejects while any document-scoped defaults fetch, application, clear or dependent reconciliation is unfinished. It never silently resumes a rejected save. Token cleanup handles superseded operations and empty/failed lookups, including Frappe's internally handled query timeouts/deadlocks; failed Company clears can be retried at Save. Currency changes during bank-instruction clearing are reconciled before the barrier is released.
- Cloud checks pass **28 JavaScript behavior tests**, **7 native-source request/save-pipeline tests**, and **15 Python calendar/form-definition tests**, plus JavaScript syntax, Python compilation and whitespace checks. The native-source tests used Frappe `f3f0c0b13c77a419487150a198fed42964e1919e` (16.36.0) locally. CI runs them against its actual installed v16 sources. This is a source-backed harness, not a completed native Desk visual walkthrough or a new local ERPNext/database integration run; pushed-commit CI still needs verification.
- Starting from PR #3 revision `c07fd6b0c05829318919e8166d839e55b49c935a`, two added Desk behavior regressions reproduced interrupted Company clearing retaining the old seller's fields and an explicit price-list edit being lost on a later currency round trip.
- Each unsaved document now retains its original pending Company-clear snapshot across navigation. Clearing resumes before requesting the new Company's profile. Field-specific write tracking distinguishes automatic changes from edits made while an asynchronous event is pending, including edits back to a previous value.
- The local JavaScript behavior suite passes **22 tests**, including both reproductions, fresh edits before and during resumed clearing, explicit zero grace, repeated refreshes, document isolation, amendments, copied bank instructions and native prefilled values. The calendar/form-definition suite passes **15 tests**. Python compilation, JavaScript syntax and whitespace checks also pass.
- This Mini has no Bench/Frappe or local MariaDB/Redis installation. Native ERPNext validation uses GitHub's disposable v16 bench for the pushed commit; its 41-test result must be checked before merge. These JavaScript harness results do not claim a completed native Desk visual walkthrough. Earlier MacBook native results are recorded in the PR, with its unfinished Desk walkthrough explicitly disclosed.
- This follow-up changes only client default-state handling and its regressions. Required fields, server validation, optional defaults, explicit entry, amendment snapshots, first-family DRAFT/payment/refund/history rules, permissions and complete printed terms remain covered by the existing suites.

## Refund and review fixes — version 0.1.1 (2026-10-01)

- Follow-up is based on merged main `44527abe71ed2e68556fc04b9e3a9abf9f585625`. Independent standards and requirements reviews identified one P1 refunded-advance defect and five P2 controller/print-permission issues.
- Native regressions first reproduced the incorrect current-order, invoice-reconciled and finance-history refund thresholds. A further native invoice-linked Customer debit/Cash credit Journal Entry submitted successfully while the app incorrectly retained confirmed 300; the regression now passes with evidence invalidated. Mixed-order invoice/credit-note payouts and credit-note header ancestry are also covered.
- 34 native integration tests and 6 calendar tests pass against the exact Frappe 16.36.0/ERPNext 16.37.0 revisions below. Coverage includes net Pay refunds, negative credit-note allocation signs, refund cancellation, additional receipts after partial refunds, ambiguous unallocated payouts, unrelated/mixed payouts, refunded historical designation revalidation, unsupported persisted payout references, native zero-decimal precision, Sales Order named place, denied user amendment and all reviewed native renderer aliases/paths/stored Chrome selection.
- Current native v16 rejects the attempted synthetic Pay allocation to the unmatched credit Journal Entry before submission. Unsupported-reference handling is therefore tested with an explicitly adversarial persisted reference on an otherwise valid native payout; it is a defensive fail-closed check, not a claim that this exact allocation is accepted by native v16.
- Two further migrations on the separate install-check site preserve every existing user role assignment and Administrator/finance permissions. No migration assigns an app role to a user.
- Five synthetic PDF cases pass on patched-Qt wkhtmltopdf 0.12.5 and 0.12.6.1: draft, paid, fully refunded first contract and returning contract have 6 pages each; the 30-item draft has 8. Text lengths/page counts match between engines. Refunded first-contract DRAFT appears on every page, and paid/returning outputs remain unmarked. All 32 pages of the 0.12.5 outputs were visually inspected with no clipping, overlap, broken tables or missing signatures. Actual production binary/fonts/hook ordering still require read-only acceptance.
- Qualifying incoming receipt criteria and the authorized first-family-only policy are unchanged. Fully allocated unrelated order/invoice payouts remain excluded. Ambiguous or unsupported same-customer/company refunds keep the first family in DRAFT until finance resolves them; they never establish finance history.

## Dedicated app permissions (earlier 0.1.0 validation, 2026-10-01)

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
node --test tests/test_form_behavior.js
FRAPPE_APP_PATH=/path/to/bench/apps/frappe node --test tests/native/test_form_save.js
```

`pz_sales_contract.demo.export` and `.concurrency` refuse sites outside the disposable `pz-contract-test.*` / `pz-contract-ci.*` naming scope. Export temporarily permits repeated item rows on that test site and restores its prior setting. It creates only synthetic records.

## Practical limits

Verified pre-install history can be registered through the restricted PZ Customer History finance workflow. It requires identified contract evidence, a submitted matching native Sales Order and a qualifying full30% historical advance. It is never guessed from Customer existence, an invoice balance or a sales checkbox; no production scan was performed. Without such a designation, the first app family is reserved. The migration's native receipt evidence is rechecked live, and cancellation restores that original family. Later contracts deliberately remain unmarked even if the first advance is pending. The reservation persists an accidental first draft, cancellation and amendment.

Bank receipts require full native reconciliation of the receipt before its contract allocation counts. Finance-submitted Cash receipts to the agreed genuine Cash account qualify. Bookkeeping evidence does not independently verify physical cash or authenticate bank instructions. Cross-currency receipts, mixed-order invoices and Journal Entries are unsupported and fail closed. Administrators remain trusted; downloaded PDFs can be altered outside the app.

No production records were changed to test. No live historical customer classification or migration was performed. The app supports additional exclusive Actual/On Net Total taxes, net-total discount, and same-day business schedules. Native beta/WeasyPrint/Chrome contract PDF paths are rejected because they bypass Frappe's enforced body hook. Existing custom integrations that use those renderers must use native wkhtmltopdf.

GitHub CI creates its own fresh v16 bench and synthetic site; its status is visible on the follow-up pull request. A local native pass does not imply a future CI run passed.
