# MacBook test handoff — contract scope WIP

This handoff is for a disposable v16 test site on the MacBook. Do not run these steps against production, migrate production, assign live permissions, create real contracts or receipts, or send/sign contracts. The Mini worktree did not run app tests or native printing.

## Automated synthetic suite

Use a disposable site named with the `pz-contract-test.` prefix and enable `allow_tests`; fixture helpers refuse to run outside a matching test site. For example:

```sh
bench new-site pz-contract-test.localhost
bench --site pz-contract-test.localhost set-config allow_tests true
```

`setup_fixtures()` creates a minimal synthetic `Bitumen Grade` DocType and the `Sales Order Item.custom_bitumen_grade` Link field only when absent, on this disposable test site. These test prerequisites are not installed by the app and must not be created on production. Run the command already used by CI:

```sh
bench --site TEST_SITE run-tests --app pz_sales_contract
```

Use an empty/disposable site with the app's synthetic fixture setup. Capture the exact commit SHA and complete test result. Do not merge if the suite is red.

## New contract and Sales Order lifecycle

1. Create a synthetic contract with a discounted line. Confirm contract delivery date, taxes and tax total are hidden/blank; contract total is subtotal less discount; advance and balance remain 30% / 70% of that item-only amount.
2. Submit the contract. Confirm its linked Sales Order is Draft, has no delivery date, has no contract taxes, and has `skip_delivery_note` turned off after creation. Confirm receipt status remains zero while the order is Draft.
3. Attempt to submit the order without a delivery date; it should be blocked. Add a synthetic delivery date and test tax row on the Sales Order, save, then submit manually. Confirm its net item total still equals the contract amount, its grand total includes the Sales Order tax, and the contract payment basis is unchanged.
4. Change an item, Grade, quantity, UOM, rate or discount on the linked order and confirm submission is blocked. Cancel a contract with a linked Draft order and confirm native Sales Order delete permission is required and the removed order reference stays in the contract audit field.
5. Print the new contract using the native enforced print format. Confirm the item-only Contract Amount and 30% / 70% basis, no delivery date or contract tax detail, no Commercial Schedule/specification appendix/Approval and Collection Record/24-business-hour banner, and the linked Draft Sales Order status. Confirm the new terms state that applicable taxes are recorded separately on the linked Sales Order or invoice and are outside the 30% / 70% basis. Print a historical contract and confirm its v1 clauses, saved schedule/specification/approval data and legacy layout remain intact.

## Desk defaults, print and access checks

- Switch Company on an unsaved contract; confirm prior seller/account defaults clear, the new Company's approved defaults load, and no legal schedule or Incoterm choice is silently selected.
- Verify customer, company, date, price list, signer, position and account fields save and reload. Confirm hidden legal defaults stay blank for new contracts.
- Generate native PDF with the bench wkhtmltopdf route and inspect pagination, signatures, the active v3 terms snapshot and the absence of removed schedule/specification/approval sections. Generate an archived v2 snapshot and a legacy v1 print; confirm each retains its saved wording and layout.
- Check role access on a disposable site: `PZ Sales Contract User` can create/read/write/print but cannot submit/cancel; `PZ Sales Contract Manager` has those contract actions; generic `Sales User`, `Sales Manager`, `Accounts Manager` and `System Manager` do not gain incidental contract access. Administrator retains native full access. Verify native Sales Order create/submit/cancel permissions separately for each intended user; users who cancel a contract while its linked order is Draft also need native Sales Order Delete permission. Verify those prerequisites before deployment.

## Release gate

Record test-site URL/name, app commit SHA, Frappe/ERPNext versions, test summary, PDF screenshot or artifact, permission results and independent reviewer sign-off. Merge only after automated checks and independent review pass on the exact pushed SHA. Production installation and user-role assignment require a separate explicit deployment step.
