# Training-account seed design

The owner explicitly requested populating the connected MoySklad training account before starting the app. Existing account documents are not modified or deleted. This bounded slice builds a reusable seed tool and executes it against that designated account.

Use the existing organization and primary warehouse, add a marked secondary warehouse and 30 fictional home-goods products. Synthetic opening inventory is RUB 7,000,000 at cost; opening cash is RUB 3,000,000, represented as a separately labeled owner contribution. Generate 180 completed days ending 2026-11-10 with deterministic weekly fast sellers, fortnightly normal sellers and ten products without sales. Replenish sold quantities after sales; record matched customer/vendor cash documents and monthly operating expenses. A warehouse transfer demonstrates non-sales movement. No debt or VAT in this simplified demo; synthetic amounts are not tax advice or a complete accounting model.

Every new entity has a stable externalCode under a2s-demo-v1 and a visible A2S-DEMO marker. Build the same payloads deterministically. Read before write; reuse matching demo records and reject drift rather than overwrite. Document syncId values, when supported, are UUID5 identifiers. Dry-run is the default, explicit --apply enables creation. Persist only a private mapping/receipt outside the repository. Token values and raw account records never appear in output or public commits. Avoid automatic write retries; a failed or ambiguous request stops the run and is reconciled by externalCode on the next run.

The public repository contains only synthetic scenario data, code, tests and Russian teaching docs. Baseline account snapshot and credential path stay private. Verify physical stock by item and warehouse, profit-report sales/cost and aggregate cash against the generated ledger, accounting for asynchronous stock recalculation. Do not claim verification while reports are stale.

Application UI, deployment and DNS changes are outside this slice.
