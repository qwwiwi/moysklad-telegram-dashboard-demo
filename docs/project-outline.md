# Delivery outline

Public README is the Russian teaching walkthrough; internal planning notes remain in English. This outline describes intended work, not a completed application.

## Confirmed context

- Telegram bot and Mini App for inventory turnover and financial visibility.
- Fictional home-goods retailer; 30 products, two warehouses and 180 days of synthetic history are the proposed demo scope.
- Original capital example: RUB 10 million, split into inventory at cost (7 million) and cash (3 million).
- Start with reproducible, reconciled local synthetic data; connect MoySklad afterward.
- A training server has already been rented: 4 GB RAM, 2 CPU cores, 80 GB storage. Do not publish its address. Read-only SSH access as root was verified. Approximately 1.5 GB RAM and 66 GB disk were available at the check; Python and Docker are installed. Ports 80 and 443 are already occupied, so inspect the existing web service before any deployment.
- Domain is not selected. Consider an existing subdomain or an approved purchase.

## Stages

1. Confirm users, bot, reporting periods and source of operating expenses; inspect the server read-only.
2. Agree a design and mobile screens using Hallmark and the dashboard starter.
3. Generate deterministic, internally consistent synthetic products and document history.
4. Implement the bot, authenticated backend, database and Mini App against the demo source.
5. Validate turnover, slow-stock indicators, profit and return on original capital.
6. Verify MoySklad permissions and implement server-side read-only synchronization, pagination and deduplication.
7. Reconcile data against the account UI; populate only an explicitly selected training account if that step is authorized.
8. Review local functionality, access tests and mobile screenshots.
9. Choose a domain and deployment layout; deploy after owner approval, then verify HTTPS, private endpoints and backups.
10. Publish demo screenshots, reproducible instructions and evidence through pull requests.

## Acceptance evidence

- Opening inventory + incoming movements - outgoing movements = closing inventory.
- Cash and profit follow distinct, documented reconciliation rules.
- Transfers do not count as sales; returns and write-offs follow explicit rules.
- Repeated synchronization does not duplicate rows.
- Missing permissions or unavailable data do not turn into false zero values.
- Unauthorized Telegram users cannot read the dashboard.
- UI labels demo mode, period, data source and last update.
- Credentials and private infrastructure information are absent from public commits.

## Open inputs

Existing web-service routing and deployment layout; bot username and token file; domain choice; authorized Telegram IDs; expense recognition policy and training account API credential file.

## Optional later work

Daily Telegram digest, configurable alerts, ABC analysis, replenishment estimates and cash planning. These are proposals outside the first-version baseline.
