# USD, packaging and location entry

Applies to new contract families created after this change (`entry_policy_version = usd-location-v1`). Existing records and amendments retain their recorded policy, currency, exchange rate and named-place text.

## Packaging

Packaging is not an entry field. The saved snapshot and print use the exact verified Item ID mapping in `entry_policy.ITEM_PACKAGING`. The test-site Item form has no separate packaging field or configured variant packaging attribute. `Bitumen - Bulk` maps to `Bulk`, `Bitumen - Drum` to `Drum`, and `Bitumen - Jumbo` to `Jumbo`. Existing grade-specific Items with explicit Bulk, Drum or Jumbo Bag names are listed individually; there is no substring inference. No size, weight or bag specification is inferred.

Changing or clearing a product clears the prior packaging. The Item lookup may fill the hidden snapshot for immediate display, while server validation always derives it again for a new or changed Item. Late responses cannot overwrite another product or document. Unknown Items remain blank; their print shows the Item without a packaging claim. Unchanged saved packaging is retained as historical data.

## USD and accounting

- New contracts show read-only USD. Selling price list and exchange-rate inputs are hidden; manual contract item rates remain authoritative, with pricing rules disabled when building the native Sales Order.
- USD companies use a conversion rate of 1. The inspected test-site `Petrol Zone` Company uses USD.
- A non-USD Company requires a positive stored `Currency Exchange` from USD to the company currency, for selling, dated on/before the contract date and valid under native Accounts Settings staleness rules. Missing rates produce an explicit configuration error. No external rate is fetched and no fallback rate of 1 is invented.
- The internal price list comes from Company Contract Defaults, then a valid native Selling Settings default, then the sole enabled USD selling price list visible to the user. Missing/ambiguous choices or an incompatible explicit Company default fail with a configuration message. No Currency or Price List masters are changed or deleted.
- Saved accounting values remain snapshots. Changing the contract date resolves the date's conversion rate while preserving its selected internal price list. Existing foreign-currency contracts keep their prior behavior.

## Incoterm locations

New contracts select a searchable `PZ Contract Location` Link. Contract Users may read choices. Contract Managers may create/edit them through native Link Quick Entry or the master list; Administrator retains native access. No generic ERP roles receive new access.

Installation/migration adds the requested starter choices `Bandar Abbas` and `Mersin, Turkey` if absent. Existing master values are not overwritten. The selected label is copied to the contract's existing `named_place` field and passed to its Sales Order/print. Later label edits or disabling a location do not rewrite saved contract snapshots. Newly selected disabled locations are rejected.

## Verification and rollout

Local checks cover stored USD/IQD conversion, missing/invalid FX, missing/ambiguous price lists, currency snapshots, packaging races, location snapshots, and role metadata. Native ERPNext database integration cases are included but require the disposable Frappe bench in CI. Local native JavaScript save tests use Frappe v16 source with intercepted network/DOM; they are not a browser or PDF rendering test.

This branch has not been published or deployed. After review and permission to publish, run full CI, then deploy/migrate the approved test site and check new entry, location Quick Entry, Sales Order conversion/manual rates, and printing. No live master or transaction data was changed while preparing this branch.
