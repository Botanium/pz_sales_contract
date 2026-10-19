# Linked Sales Order description consistency

For item-only-scope contracts, the linked draft Sales Order may be completed with its delivery date and taxes. At submission, a nonblank description recorded on each submitted contract line must still match that Sales Order line, alongside the existing Item, Grade, quantity, UOM and rate checks. Replacement or removal of agreed wording blocks submission and identifies the row. Draft editing remains possible; restore the recorded contract wording before submitting.

Comparison uses the persisted descriptions copied by `build_order`, retaining native Frappe HTML sanitization and legacy snapshots without rewriting them. Unchanged plain text, line breaks, HTML and entity-containing text remain submittable. Non-item-only and unlinked orders retain their existing behavior.

Blank/null contract descriptions contain no agreed product wording. Those lines retain ERPNext’s existing blank/Item-description fallback rather than gaining a new description obligation. No stored contracts, linked orders or Item masters are migrated or updated by this change; no production data was inspected to infer whether any real order was affected.

The regression was reproduced on a disposable Frappe16.19.0/ERPNext16.20.1 site: an altered description submitted successfully before the fix. Native tests now reject replacement, empty and null removal, reject swapped descriptions on identical Item rows, and accept unchanged sanitized/historical wording and blank contracts.
