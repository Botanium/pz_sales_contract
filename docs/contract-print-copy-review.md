# Contract print copy — review draft

**Status: draft for user and legal review. This copy is not active in the print template.** The current clause text in `pz_sales_contract/terms.json` remains unchanged while delivery and tax policy choices are pending.

## Proposed print structure

For new contracts, keep the party details, product/grade/quantity/UOM/rate table, agreed specification rows (only when supplied), payment instructions, the applicable versioned Contract Terms, and signature blocks. Remove the blank Commercial Schedule, the fixed “24 business hours” banner, the Approval / Collection Record, and signature wording that asserts uncompleted deadlines, charges, or force majeure settings. The existing child `specification_reference` field is hidden and retained for historical data; it is no longer shown in the form or print.

Do not activate that structure until the Contract Terms have been reconciled with it. Clauses that depend on delivery dates, business hours, collection grace, charges, legal venue, or other omitted schedule values cannot remain silently binding through the printout.

## Candidate replacement copy

**Opening paragraph — draft:**

> This document records the commercial details completed for this transaction, including the goods, grade, quantity and unit, unit price, currency, any discount, and the selected Incoterm and named place. The Contract Terms reproduced in this document form part of the parties’ agreement.

**Signature paragraph — draft:**

> Each signatory confirms that they are authorised to sign for the party named below and that the party accepts this document, including its completed commercial details and the Contract Terms reproduced here.

These paragraphs are candidates only. They do not settle the delivery-date or tax questions below and do not replace review of the full clauses or applicable law.

## Policy-dependent lines — leave unresolved

- **Delivery-date option under review:** If the user confirms a Draft Sales Order workflow, candidate line: “The delivery date is entered on the linked Sales Order before that order is submitted.” Do not print an empty delivery date or imply that one has been agreed in the contract.
- **Tax option under review:** If the user confirms item-amount-only 30% / 70% calculations with tax later on the Sales Order or invoice, candidate line: “The contract payment percentages are calculated on the discounted goods amount. Applicable taxes and charges are calculated and shown on the linked Sales Order or invoice.” Do not activate until the user confirms the basis and which charges, if any, are included.

## Historical clause handling

New contracts store the exact `terms.json` clause list in the hidden `terms_snapshot` field at creation. Amendments inherit the source contract’s snapshot. Contracts created before snapshots existed use the immutable `terms_versions/v1.json` copy when printed. A canonical SHA-256 check guards v1 at runtime and in the static test suite. That v1 copy freezes the clause list present at this change; it cannot prove which text an older contract rendered before this snapshot mechanism existed. Future approved copy changes should update the active `terms.json`; already-created contracts will continue to print their saved snapshot.

## Pending confirmations

1. Should the contract create a **Draft Sales Order**, with the delivery date entered or confirmed on that order before Sales Order submission?
2. Should the contract total and 30% / 70% amounts use **discounted item amounts only**, with taxes and charges calculated later on the Sales Order or invoice?

Until both answers and the copy review are recorded, this draft does not replace the current print template or active clauses.
