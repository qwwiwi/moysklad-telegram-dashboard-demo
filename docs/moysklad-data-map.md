# MoySklad data map

Research baseline: 2026-11-11. Official documentation was read in the browser. No authenticated MoySklad API call has been made for this project.

Base URL: `https://api.moysklad.ru/api/remap/1.2`.

| Resource | Read endpoint | Intended use |
| --- | --- | --- |
| Products | `GET /entity/product` | Stable IDs, names, articles, groups and configured prices |
| Warehouses | `GET /entity/store` | Warehouse directory |
| Customer orders | `GET /entity/customerorder` | Ordered items, statuses and reserves |
| Receipts | `GET /entity/supply` | Supplier receipts and acquisition documents |
| Shipments | `GET /entity/demand` | Sales shipment documents |
| Stock report | `GET /report/stock/all` | Stock, reserve, expectation, unit cost and stock days |
| Turnover report | `GET /report/turnover/all` | Opening/closing quantity and cost, incoming/outgoing movements |
| Profit by product | `GET /report/profit/byproduct` | Sales quantity, sales amount, sales cost and returns |
| Money movements | `GET /report/money/plotseries` | Receipts/payments over a period |
| Money balances | `GET /report/money/byaccount` | Current account and cash balances |

## Fields and interpretation

- Stock: `stock`, `reserve`, `inTransit`, `quantity`, `price`, `stockDays`. Preserve source definitions: available quantity is not automatically the same as physical stock minus reserve.
- Turnover: `onPeriodStart`, `onPeriodEnd`, `income`, `outcome`, each with `quantity` and `sum`.
- Profit: `sellQuantity`, `sellSum`, `sellCostSum`, `returnQuantity`, `returnSum`, `returnCostSum`, `profit`.
- Cash movements: `credit`, `debit`, `series`; balances: `balance`, organization and account.
- Convert units per endpoint contract. Stock cost and turnover cost sums are documented in kopecks; do not assume one universal unit for every monetary field.

## Integration requirements

1. Use server-side Bearer authentication; never expose the credential in the Mini App.
2. Send `Accept-Encoding: gzip`, as required by the current API documentation.
3. Follow pagination; a single response page is not a full import.
4. Set explicit report periods and timezone handling.
5. Record sync time, report parameters and source IDs. Handle delayed stock recalculation.
6. Reconcile known documents and amounts against the training account UI.
7. Verify report permissions before treating missing fields as zeros.
8. Handle throttling and partial synchronization without overwriting good data with empty results.
9. Do not generate or rotate account tokens automatically: generating a new user token revokes previously issued tokens according to the documentation.

## Limits of the reports

All outgoing warehouse movements are not sales: transfers and write-offs must not inflate cost of goods sold. The profit report is a source for trading profit, not proof of complete net business profit. Current money balances are accounting records, not independently verified bank balances.

## Official references

- [General API documentation](https://dev.moysklad.ru/doc/api/remap/1.2/)
- [Stock](https://dev.moysklad.ru/doc/api/remap/1.2/#/reports/report-stock)
- [Turnover](https://dev.moysklad.ru/doc/api/remap/1.2/#/reports/report-turnover)
- [Profit](https://dev.moysklad.ru/doc/api/remap/1.2/#/reports/report-pnl)
- [Money](https://dev.moysklad.ru/doc/api/remap/1.2/#/reports/report-money)
