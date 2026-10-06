# Contract terms and print layout

**Current print version:** v4. New contract families snapshot the exact 15 clauses in `pz_sales_contract/terms.json`; the same clause list is archived as `terms_versions/v4.json` and pinned by SHA-256. Clause 4 restores the source wording “outside those hours.” The prior v3 text remains pinned in `terms_versions/v3.json` with its wording “outside business hours.” Each clause prints as its own paragraph with widow/orphan-safe page flow. Clauses are grouped in sets of five with repeated Contract Terms headings. The exact supplied wording is preserved, including the repaired boundary between clauses 8 and 9.

## Terms-to-form input gaps

The new print keeps the supplied wording as written. The v4 contract form intentionally omits the Commercial Schedule and specification editor, and no new defaults, fields or values were added to resolve the references below.

| Clauses | Term references | Current v4 contract input |
| --- | --- | --- |
| 1 | Commercial Schedule and agreed specifications | No schedule is printed or captured; new specification rows are rejected. |
| 2 | Measurement basis, quantity tolerances, price adjustments, additional charges and taxes in commercial terms | The contract captures quantity, unit and rate but no measurement/tolerance/adjustment/charge schedule. Contract taxes are empty; applicable taxes are entered on the linked Sales Order. The clause's final invoice balance also differs from the printed 70% balance basis. |
| 3 | Order Approval, 24 business-hour advance and balance deadlines, Ready Notice | No approval or Ready Notice timestamps/deadlines are captured for v4. The separate manual Print as Draft checkbox remains independent of receipts. |
| 4 | Business days, opening/closing hours, time zone, holiday calendar and notice channel | These values are not entered or printed in v4; hidden historical schedule fields are cleared. |
| 5 | Completed collection grace, agreed storage/handling/reheating/reloading/demurrage charges, penalty basis and cap | No grace period, charge schedule or penalty basis is captured for v4. |
| 6 | Completed cure period | No cure period is captured for v4. |
| 7 | Signed delivery/risk arrangement, transport and insurance responsibility | v4 captures Incoterm and named place only; it has no separate delivery/risk/transport/insurance fields. |
| 9 | Completed latent-claim period and agreed specifications | No latent-claim period or v4 specification table is captured. |
| 13 | Completed force-majeure threshold | No termination threshold is captured for v4. |
| 14 | Taxes and charges determined by commercial terms | Applicable taxes are entered on the linked Sales Order; no contract-level charge lines are captured for v4. |
| 15 | Completed governing-law and court fields | These fields are hidden, cleared for new v4 contracts, and not captured elsewhere in the contract form. |

Clauses 10–12 and 14 also supply legal remedies, liability limits, cancellation treatment, force-majeure scope/procedure, safety and compliance terms. Those are printed exactly as supplied; this change does not populate per-order values for them. No schedule value, tax, penalty, venue, deadline or charge has been inferred. The above is a product/input mismatch report for legal and business review, not a legal interpretation.

## Print-only stamp

The user-provided Petrol Zone stamp is cropped to its blue-seal boundary with a 12-pixel white margin. A pixel comparison verified the crop matches the corresponding source pixels exactly; no text, shape, ink or color was redrawn. The crop is kept outside the public app source and must be staged by an authorized site operator at `sites/<site>/private/files/petrol_zone_stamp.png`. The print context reads that site-private file only after contract read/print permission checks and embeds it only in the seller signature area. No DocType field or public asset route is added. If the file is missing, printing continues without it. It is a company stamp graphic, not a signature. This change does not stage the image on any installed site.

## Exact v4 contract terms

The active and archived v4 clause lists are `pz_sales_contract/terms.json` and `pz_sales_contract/terms_versions/v4.json`. Their canonical clause-list digest is pinned in `contract_terms.py`. The archived v3 list and its digest are unchanged; its clause 4 retains “outside business hours.”

## Version behavior

New contract families use `terms_version = v4` and snapshot the active clauses. Existing v3 contract snapshots are not changed; records with no saved v3 snapshot continue to use the unchanged v3 archive, and amendments retain their source snapshot and print version. V2 contracts retain their saved two-clause snapshots and simplified print layout. The v2 and v3 wording files remain pinned, and pre-v2 records retain the immutable v1 baseline and legacy layout. Updating the active terms file does not rewrite saved snapshots.

The native HTML print and PDF route share the same template and print context. CI tests verify the rendered HTML passed to native PDF generation, page grouping, headers/footers, stamp placement, and draft/cancel markers. The CI PDF route mocks the final wkhtmltopdf binary boundary, so a real PDF engine visual pass remains separate.
