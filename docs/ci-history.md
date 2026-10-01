# CI notification history

The ten original failure alerts came from the push and pull-request runs for five earlier commits. Workflow history is retained. These are superseded runs, not failures of the final original release commit `6dfd3377bf21aaf7ff99d35d91d7924bf7f00f76`, whose [PR](https://github.com/Botanium/pz_sales_contract/actions/runs/36793603676) and [push](https://github.com/Botanium/pz_sales_contract/actions/runs/36793599601) checks both passed calendar and native v16 integration.

| Earlier commit / PR run | Root cause | Existing correction |
| --- | --- | --- |
| [`953e8d0`](https://github.com/Botanium/pz_sales_contract/actions/runs/36789519734) | Bench initialization used the obsolete `--skip-redis-config` option. | `b4901e7` uses `--skip-redis-config-generation` and current Bench dependency commands. |
| [`b4901e7`](https://github.com/Botanium/pz_sales_contract/actions/runs/36789695355) | A fresh ERPNext site had no setup-wizard Customer Group root. | `96461ce` seeds the required synthetic tree roots. |
| [`96461ce`](https://github.com/Botanium/pz_sales_contract/actions/runs/36791184820) | The fresh site's Company setup required the absent Transit Warehouse Type. | `b3f68a1` supplies Transit plus the native Address Template and Customer/Receivable Party Type prerequisites. |
| [`b3f68a1`](https://github.com/Botanium/pz_sales_contract/actions/runs/36792980059) | Skipping asset generation left Frappe's bundled asset manifest absent; native printview failed when including `print.bundle.css`. | `6dfd337` builds the actual Frappe assets. |
| [`488d339`](https://github.com/Botanium/pz_sales_contract/actions/runs/36793148293) | The README-only follow-up had the same missing native print assets. | The same `6dfd337` correction. |

A subsequent fresh code review found a separate display defect: monetary print values and the evidence dialog used two decimal places even when native ERP precision was three. The fix uses native field precision and the server-provided advance precision. A new regression covers normal two-decimal and three-decimal rates, line/contract totals, required advances and receipts, including insufficient advances. Native arithmetic and the server threshold were not relaxed. Both disposable native sites passed 22 tests, with six additional business-hour unit tests; native PDF exports and the real concurrency check also passed.

For the current branch, use the commit-specific checks on [draft PR #1](https://github.com/Botanium/pz_sales_contract/pull/1). A passing earlier commit does not imply that a later commit has passed.
