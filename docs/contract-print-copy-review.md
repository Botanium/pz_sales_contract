# New-contract print wording and layout

**Status:** Version 2 is active for new contract families. The wording below was approved by the user for this implementation. Its scope is to preserve the stated 30% / 70% split, identify the goods-only calculation and place any applicable taxes on the linked Sales Order or invoice. It adds no payment deadline, penalty, charge, delivery default or legal venue.

## Exact new-contract wording

**Opening paragraph**

> This document records the commercial details completed for this transaction, including the goods, grade, quantity and unit, unit price, currency, any discount, and the selected Incoterm and named place. The Contract Terms reproduced in this document form part of the parties’ agreement.

**Clause 1 — Contract Documents**

> 1. Contract Documents. This Contract consists of the Seller and Buyer details, the completed Products and Price section (including the listed goods, grade, quantity, unit, rate, currency, any discount, and selected Incoterm and named place), and these Contract Terms. Changes require written agreement by authorised representatives.

**Clause 2 — Contract Amount and Payment Split**

> 2. Contract Amount and Payment Split. The Contract Amount is the discounted goods amount only (subtotal less discount). The Buyer’s payment split is a 30% advance and a 70% balance, each calculated on the Contract Amount. Applicable taxes, if any, are recorded and calculated separately on the linked Sales Order or invoice; they are not included in the Contract Amount or the 30% / 70% calculation.

**Signature paragraph**

> Each signatory confirms that they are authorised to sign for the party named below and that the party accepts this document, including its completed commercial details and the Contract Terms reproduced here.

## Versioned print behavior

New contract families snapshot the active `terms.json` clauses and receive hidden `terms_version = v2`. Their print omits the Commercial Schedule, product-specification appendix, Approval / Collection Record, fixed 24-business-hour banner, and signature assertions about deadlines, charges and force majeure. The new form hides the specification table and server validation rejects specification rows for v2 so entered terms cannot silently disappear from the printed contract. New prints show the Contract Amount, 30% advance and 70% balance using discounted goods only; the two clauses above state that applicable taxes are handled separately on the linked Sales Order or invoice.

Amendments copy their source contract's clause snapshot and print version. Records without a `terms_version` keep the legacy layout. Records without a terms snapshot use `terms_versions/v1.json`; its canonical SHA-256 remains pinned in code and the static test suite. The v1 file is not changed. This preserves pre-cutover wording and layout, including specifications and any stored schedule/approval history.

The v1 snapshot freezes the clause text present at the original snapshot cutover; it cannot establish which wording an older PDF used before snapshots existed.
