# Proposed delivery outline

This is an initial research outline, not an approved implementation design.

## Stages

1. Confirm the demo business, reporting periods, users, currency and timezone.
2. Inspect the designated server read-only and verify available MoySklad API access.
3. Agree the screens, metric definitions, data model and source of operating expenses.
4. Prepare reproducible synthetic products and documents for the explicitly selected training account.
5. Implement the read-only synchronization path, preserving source IDs and reconciliation evidence.
6. Adapt the Telegram dashboard starter: authenticated backend, bot, Mini App and inventory-specific tables.
7. Verify financial arithmetic, duplicate imports, stale/missing data, returns and access rejection.
8. Review locally with mobile screenshots and documented evidence.
9. Deploy only after owner approval; verify HTTPS, private ingestion endpoints and backups.

## Evidence required

- Source documents reconcile with stock, sales cost and money reports.
- Repeating synchronization does not duplicate rows.
- Missing permissions or unavailable reports do not turn into false zero values.
- Transfers do not count as sales; returns and write-offs follow explicit rules.
- An unauthorized Telegram user cannot read the dashboard.
- Demo data and real-account data cannot be confused.

## Open inputs

- Training account API credential file location and verified report permissions.
- Server SSH alias/address and what already runs there.
- Bot username and credential file location.
- Dashboard domain and the list of authorized users.
- Expense categories, recognition policy and the demo reporting period.

## Session log

- Downloaded upstream course skill repositories and reviewed the published second-week materials.
- Read the official MoySklad documentation through the browser and inspected the signed-in account homepage without changes.
- Defined an initial inventory and finance scenario with synthetic figures.
- Created the public teaching repository. Application implementation and account seeding remain pending.
