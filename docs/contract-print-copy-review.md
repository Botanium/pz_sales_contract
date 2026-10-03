# Contract print copy — review draft

**Status: draft for legal and print review. The user's delivery-date and tax choices are recorded below; this copy is not active as a replacement print layout.** New contracts now snapshot the active terms in `pz_sales_contract/terms.json`; existing snapshots and the frozen v1 fallback remain unchanged.

## Proposed print structure

For new contracts, keep the party details, product/grade/quantity/UOM/rate table, agreed specification rows (only when supplied), payment instructions, the applicable versioned Contract Terms, and signature blocks. Remove the blank Commercial Schedule, the fixed “24 business hours” banner, the Approval / Collection Record, and signature wording that asserts uncompleted deadlines, charges, or force majeure settings. The existing child `specification_reference` field is hidden and retained for historical data; it is no longer shown in the form or print.

Do not activate that structure until the Contract Terms have been reconciled with it. Clauses that depend on delivery dates, business hours, collection grace, charges, legal venue, or other omitted schedule values cannot remain silently binding through the printout.

## Candidate replacement copy

**Opening paragraph — draft:**

> This document records the commercial details completed for this transaction, including the goods, grade, quantity and unit, unit price, currency, any discount, and the selected Incoterm and named place. The Contract Terms reproduced in this document form part of the parties’ agreement.

**Signature paragraph — draft:**

> Each signatory confirms that they are authorised to sign for the party named below and that the party accepts this document, including its completed commercial details and the Contract Terms reproduced here.

These paragraphs are candidates only. They do not replace review of the full clauses or applicable law.

## Confirmed workflow lines — legal review remains open

- **Delivery date:** Omit it from new contract entry and print. The linked Sales Order remains Draft until a user enters the delivery date and manually submits it.
- **Tax basis:** New contract total and 30% / 70% amounts use discounted goods only. Applicable taxes and charges are entered on the linked Sales Order or invoice and are not included in the contract amount.
- The active print still contains the Commercial Schedule, fixed 24-business-hour banner, Approval / Collection Record and associated signature assertions. Their legal treatment is unresolved; this WIP keeps them visible and blocks release pending copy/legal review.

## Historical clause handling

New contracts store the exact `terms.json` clause list in the hidden `terms_snapshot` field at creation. Amendments inherit the source contract’s snapshot. Contracts created before snapshots existed use the immutable `terms_versions/v1.json` copy when printed. A canonical SHA-256 check guards v1 at runtime and in the static test suite. That v1 copy freezes the clause list present at this change; it cannot prove which text an older contract rendered before this snapshot mechanism existed. Future approved copy changes should update the active `terms.json`; already-created contracts will continue to print their saved snapshot.

## Remaining release review

The user has selected the Draft Sales Order flow and item-only contract amount. The changed active clauses state that basis for new contracts. This draft still does not replace the existing print layout; legal review and a consistent treatment of the schedule and approval assertions remain release gates.
