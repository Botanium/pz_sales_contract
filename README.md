# Petrol Zone Sales Contracts

A dedicated Frappe app for ERPNext v16. App users choose ERP Customers, Addresses, Contacts, Items, per-line Bitumen Grade masters, UOMs and Incoterms; app managers submit contracts and create a linked Draft Sales Order for users to complete and submit separately. New contracts use the discounted item amount only; delivery date and applicable taxes are entered on the Sales Order. Existing contracts retain their saved date/tax data and legacy print behavior.

## Manual print DRAFT marker

The contract form includes a **Print as Draft** checkbox. It defaults unchecked for new contracts and migrated records; only an operator's saved checkbox value controls the print mark. When checked, each contract page and PDF running header show exactly **DRAFT**. The mark is independent of Customer history, Payment Entries, Sales Order status, contract save or submission. No advance receipt is checked to decide whether a contract can be saved, submitted or printed. A cancelled contract keeps its CANCELLED marking.

The checkbox can be changed after contract submission. Amendments start unchecked and do not copy the source contract's print choice. The existing first-family registry and restricted PZ Customer History remain for their finance audit workflow, but neither changes the print marker. Payment evidence is retained for historical finance verification and is not evaluated during contract rendering.

## Restricted finance history

The app retains a unique first-family reservation per Customer as an audit record. Customer identity cannot change within a family and deletion is blocked. Native Customer rename preserves the registry. Cancellation keeps the registry. Cancellation continues to cancel a submitted Sales Order transactionally; a linked Draft Sales Order is deleted only with native Sales Order Delete permission and its identifier is retained as a hidden contract audit reference. Active downstream payment/invoice/delivery links can block cancellation until finance unwinds them. Amendments inherit their family and create a new Sales Order.

Finance can use **PZ Customer History** to register evidence for identified pre-app contracts. Accounts Manager (with native Sales Order/Account read access) or System Manager alone can submit/cancel those auditable designations; Sales User and Sales Manager have no designation permission. Submission checks a matching submitted historical Sales Order and qualifying native receipt evidence. Customer existence, an old invoice balance, or a manual paid checkbox is insufficient. The history workflow does not control current contract draft printing.

Historical receipt matching uses submitted native Payment Entries allocated to the identified order or a wholly attributable submitted invoice, nominated accounts, company and currency. Bank receipts require native reconciliation and live bank GL evidence; cash receipts require native Cash account and GL evidence. Refunds, cancellation, unsupported allocations and related Customer debits are handled by the restricted history evidence workflow. These finance checks remain separate from contract save, submit and print.

**Foreign exchange limitation:** historical receipt verification requires the party and receiving accounts to use the order currency and matching paid/received amounts. Cross-currency receipts fail closed. This does not restrict the contract's native ERP exchange-rate accounting.

## Commercial inputs

The new contract form omits delivery date, contract tax details and deal-specific legal schedule or approval-record inputs. A new contract total equals discounted goods only; 30% / 70% amounts remain as displayed totals. The linked Sales Order is saved Draft so a user can enter a delivery date and applicable taxes before manually submitting it. New v3 prints include the user-supplied 15-clause term set and omit the Commercial Schedule, specification appendix and approval record. Several v3 clauses refer to values that v3 does not capture; see [the print-copy review](docs/contract-print-copy-review.md). No delivery date, schedule value, tax amount, venue, charge or deadline is inferred. Saving/submitting does not sign or send a contract.

The optional child `specification_reference` value is retained in stored history but hidden from the contract form and omitted from printing. New v3 contracts hide the specifications table and reject new specification rows because their print omits that appendix. Contract clauses are pinned at creation in `terms_snapshot` with a hidden `terms_version`; amendments inherit the source clause snapshot and print layout. Pre-snapshot records print the immutable versioned baseline matching their terms version and legacy layout. The v1 and v2 snapshots are SHA-256 guarded; v1 preserves the original master, and v2 preserves the previous two-clause print copy. The current 15-clause v3 wording and form-input gaps are recorded in `docs/contract-print-copy-review.md`.

The 30%/70% amounts displayed by the form remain calculated on discounted goods only, with taxes entered later on the linked Sales Order. The supplied v3 terms also describe the final balance as the final invoice total less the advance; that input/calculation mismatch is recorded in the print-copy review rather than filled with a new default. Historical contracts retain their native tax rows. Each contract line selects an active Bitumen Grade master, independent of Item, and the link maps to Sales Order Item `custom_bitumen_grade`. The contract keeps a text snapshot for print/history: the master’s `grade_code` is used when that field exists, otherwise the canonical Link name is used. Previously saved free-text Grade values remain viewable and savable as history; an unchanged disabled Grade link remains available on a saved contract, while a new line cannot use disabled or missing masters. If a previously linked Grade master is missing, saving the unchanged contract clears that stale Link but retains its text snapshot. No mixed-UOM quantity total is shown.

The supplied company stamp is embedded in the seller signature area by the print context only. It is not a contract-form field or part of the public app package. An authorized site operator must place the cropped image at `sites/<site>/private/files/petrol_zone_stamp.png`; if absent, the print omits the image without failing.

## Optional company defaults

New contract families use fixed USD. Their exchange rate and internal USD selling price list are resolved on the server; those inputs are hidden on the form from initial load. Packaging is hidden and read-only for all contract families, derived server-side from exact verified Item IDs when a line is added or changed, and included in the print when known. An unchanged saved line retains its historical packaging snapshot, including on amendments. A searchable **PZ Contract Location** supplies the named-place snapshot. Contract Users can read locations; Contract Managers can add and edit them. See [USD, packaging and location entry](docs/usd-packaging-location-entry.md) for resolution rules and historical compatibility.

A System Manager may maintain one **PZ Contract Defaults** record per seller Company. Supported blank seller fields and compatible USD receiving-account instructions are copied on creation only. New contracts resolve accounting conversion from the Company currency and stored Currency Exchange records, independently of any profile rate. Historical delivery/legal schedule settings remain stored but are not copied into new contracts. Customer, quantity, item rate, Incoterm, location, discount and taxes require explicit entry. The Incoterm chooser offers EXW, FOB and CIF plus other existing ERP Incoterm records configured per Company; no term or location is auto-selected.

If no defaults record exists, seller and payment fields remain available for explicit entry. Changing Company on a new form clears the prior seller address, signatory and accounts while retaining USD. Each saved contract is self-contained: later master/default edits do not rewrite its accounting or named-place snapshots. Pre-cutover records and amendments retain their existing currency and entry policy. Defaults do not set or change the operator-controlled Print as Draft checkbox.

Save is blocked while Company defaults are loading, applying or clearing. Wait for the update to finish, review the resulting values and save again. A blocked attempt never automatically saves later. Empty or failed optional-default lookups still permit manual entry once pending updates have finished.

## Installation (administrator action)

On a separately approved v16 bench, install the reviewed revision from `main` and verify its actual Git commit:

```sh
bench get-app https://github.com/Botanium/pz_sales_contract --branch main
bench --site YOUR_SITE install-app pz_sales_contract
bench --site YOUR_SITE migrate
bench build --app pz_sales_contract
```

Requires Frappe/ERPNext `>=16,<17`, Python 3.14 and the bench wkhtmltopdf PDF engine. Installation creates **PZ Sales Contract User** (create/read/write/print) and **PZ Sales Contract Manager** (those operations plus submit/cancel/amend). Assign the appropriate app role explicitly to approved users; installation and migration do not assign roles to any user. Administrator retains native full access. Generic Sales User, Sales Manager, Accounts Manager and System Manager roles do not grant access to PZ Sales Contract.

App roles grant no native Sales Order, master-data, payment, bank-reconciliation, finance-history or registry permissions. Reuse each approved user's existing native Sales Order create/submit/cancel and Customer/Company/Address/Contact/Item/Bitumen Grade/Account read access; users who cancel a contract while its linked Sales Order is Draft also need native Sales Order Delete permission. The Sales Order Item `custom_bitumen_grade` field must already exist. Review any missing prerequisite separately. Finance history remains restricted to Accounts Manager/System Manager. Configure Company selling defaults, accounts, price lists, Grade and Incoterm masters in ERPNext. Enable draft print in native Print Settings if preliminary contracts must be printed.

All supported native contract print formats are routed through the mandatory app template with a freshly loaded persisted document. Native beta print builders, direct WeasyPrint downloads and the optional Chrome PDF renderer are explicitly rejected at configuration/request boundaries; scalar and dictionary batch requests are covered. Unsaved print payloads, client-supplied paid flags and alternate Standard formats cannot remove the marker from app-generated output. Other DocTypes retain Frappe’s ordinary print behavior.

## Validation

See [validation.md](docs/validation.md) for exact tested versions, outcomes, evidence and limitations. Synthetic integration tests live beside the DocType, and pure business-hour tests are in `tests/`. No production records, customer contracts, signatures or payment details are included in this repository. See [CI history](docs/ci-history.md) for the superseded build/setup failures that generated earlier notifications.
