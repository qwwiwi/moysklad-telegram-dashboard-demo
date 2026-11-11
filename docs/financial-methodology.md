# Financial methodology

All example amounts are synthetic RUB. Inventory is valued at cost, not selling price. Every metric must show its period and data completeness.

## Metrics

- Net sales = sales amount minus sales returns.
- Net cost of goods sold (COGS) = sales cost minus returned goods cost, with a consistent period and accounting policy.
- Gross profit = net sales minus net COGS.
- Net management profit = gross profit minus all other relevant expenses and taxes, using a consistent recognition policy.
- Inventory turns = net COGS / average inventory at cost.
- Inventory days = average inventory at cost / net COGS * days in period.
- GMROI = gross profit / average inventory at cost. This is before operating expenses and is not return on the owner's entire capital.
- Return on original investment = net management profit / original investment. Label this explicitly; it is not automatically ROIC or ROE.

Use average daily inventory when the history is available. An opening/closing average is an approximation and must be labeled. Zero denominators and missing costs produce an unavailable metric, not zero or infinity. Do not annualize a short demonstration period silently.

## Reconciled 30-day example

Assume no debt, receivables, payables, additional owner contributions or withdrawals. All transactions are paid. Sales are net of returns; no returns occur in this worked example.

| Item | RUB |
| --- | ---: |
| Original investment | 10,000,000 |
| Opening inventory | 7,000,000 |
| Opening cash | 3,000,000 |
| Net sales | 4,000,000 |
| COGS | 2,800,000 |
| Gross profit | 1,200,000 |
| Other expenses including illustrative taxes | 900,000 |
| Net management profit | 300,000 |
| Inventory replenishment paid | 2,800,000 |
| Closing inventory | 7,000,000 |
| Closing cash | 3,300,000 |

Cash reconciliation: 3,000,000 + 4,000,000 - 2,800,000 - 900,000 = 3,300,000.

Assuming average inventory of 7,000,000: turns = 0.4 for 30 days; inventory days = 75; return on the original investment = 3% for 30 days. Equal opening and closing balances alone do not prove that the daily average was 7,000,000.

## Slow stock

Proposed alert: positive stock with no sale in the preceding 90 days. This is a configurable demonstration rule, not a universal business standard. Days since last sale and the age of the current stock are different metrics. Newly received stock requires separate treatment.

RUB 7 million of inventory plus RUB 3 million cash only equals owner equity under the simplified no-debt model. A real capital view also needs receivables, payables, loans, other assets and owner movements.

## References

- [OpenStax financial statement analysis](https://openstax.org/books/principles-financial-accounting/pages/a-financial-statement-analysis)
- [MoySklad profitability report](https://dev.moysklad.ru/doc/api/remap/1.2/#/reports/report-pnl)
