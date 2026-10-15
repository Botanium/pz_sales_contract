# Saved drafts: readiness and editable contract wording

## Verified cause

On 2026-10-15 the deployed Frappe Cloud Apps page showed Sales Contracts revision `0166ee6`. Read-only inspection of the reported draft confirmed status Draft, terms version v5, an existing terms snapshot and zero readiness days. Dynamic field metadata was hidden/read-only with no depends_on. PR15 explicitly limited saved-record readiness to v6. New forms showed it because they were treated as new v6 families. This was not a missing migration or cache problem. The user's unsaved new-form tab was left untouched; no production contract was saved or changed.

## Behavior

Cargo Ready Within (Days) remains beside Advance percentage. It is visible for every version and editable on drafts, including saved amendments. Positive whole calendar days are optional; blank/zero creates no commitment. With 0% advance, the advance-triggered readiness line is omitted and the form explains why. Submitting freezes both readiness and custom wording. Existing historical wording is not upgraded to v6 or supplemented with loading/export wording automatically.

A collapsed **Terms & Conditions** section sits before Payment instructions. It displays a read-only preview of the contract's existing general clauses. **Edit contract wording** explicitly copies them into a plain-text **Contract wording** editor. Blank lines separate clauses. Viewing a form does not materialize a fallback or mark it edited. Saving custom wording stores an optional per-contract override; it does not overwrite the original internal terms snapshot. Clearing it restores the original snapshot/version fallback, including before Save.

Readiness is generated separately from saved days and advance, using the next clause number. Changes to days or advance never replace custom general wording. Custom wording prints as entered through normal Frappe text sanitization and escaped rendering; users must review payment references after changing advance percentages. New amendments inherit source wording and days, while explicit edits to the draft copy are preserved. The source is not changed.

Both current and legacy print layouts paginate all saved clauses rather than truncating after a fixed count. Submitted/cancelled records keep their saved wording; no migration backfills commitments or overrides. Incoterm, USD policy, stamp, order workflow and removed Planned Delivery Date remain unchanged.

## Authorization

Implementation, PR push, review and merge are authorized for this follow-up. Frappe Cloud TEST/production deployment remains user-owned and was not performed.
