# Quotation State Machine v2

> Decision date: 2026-06-16 (Phase 0 / D3).
> Status: implemented in `mobbit-backend-service` v0.2.0.

---

## Why

The original MVP (`infra-backend-b2c-tf/`) had a single `state` field on
`Quotation` that was being **abused as a wizard progress indicator**:

- The B2C public wizard had 10 React components (Step1 through Step10)
- Each step that needed persistence called `PUT /quotation/{id}` with
  `state: 'step_3' | 'step_4' | 'step_6' | 'FILLED'`
- The provider's `GET /quotation/{id}/auctions` only returned quotations
  where `state == "FILLED"`

This conflated two distinct concepts:
1. **Lifecycle of the quotation** (DRAFT → QUOTED → BIDDING → …)
2. **Progress of the B2C wizard** (step 1, 2, 3, …, 10)

The data migration from DDB to PG exposed the problem: 234 items
included values like `state="step_6"`, `state="quoted"`, `state="FILLED"`
all mixed together. There was no clear way to know which was a
"real" lifecycle state and which was a wizard step.

## The new design

Two separate concerns, two separate fields.

### Schema

```sql
-- Lifecycle of the quotation (the business concept).
state           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'

-- Progress of the B2C wizard (orthogonal to the lifecycle).
wizard_step     INT          NULL          -- 1..10 while in progress
wizard_complete BOOLEAN      NOT NULL DEFAULT FALSE
```

`wizard_step IS NULL` + `wizard_complete = false`  → admin-created,
not from the wizard
`wizard_step IS NULL` + `wizard_complete = true`   → wizard finished,
now waiting for admin to publish
`wizard_step IS NOT NULL` + `wizard_complete = false` → wizard in
progress at step N

### Lifecycle states (valid values)

```
DRAFT → QUOTED → BIDDING → AWARDED → IN_PROGRESS → COMPLETED
        ↘                ↘                ↘
         CANCELLED        REJECTED         FAILED
```

| State         | Visible to providers? | Set by                                              |
|---------------|----------------------|------------------------------------------------------|
| `DRAFT`       | No                   | `POST /quotation` (B2C) or `POST /quotation` (admin) |
| `QUOTED`      | **Yes**              | `POST /quotation/{id}/publish` (admin only)          |
| `BIDDING`     | Yes                  | First auction is created (provider side)            |
| `AWARDED`     | Yes                  | `PUT /quotation/{id}/auction` (B2C client selects)   |
| `IN_PROGRESS` | Yes                  | Provider accepts the award                           |
| `COMPLETED`   | Yes                  | Service delivered                                   |
| `CANCELLED`   | No                   | `POST /quotation/{id}/cancel` (admin) or client     |
| `REJECTED`    | No                   | All providers decline (future)                       |
| `FAILED`      | No                   | Generic failure (future)                             |

### Transitions

All transitions are explicit. The only automated transitions are:

1. **DRAFT → QUOTED** via `POST /quotation/{id}/publish` (admin only).
   - Idempotent (re-publishing returns 200 unchanged).
   - Validates minimum required fields: `client_name`, `client_phone`,
     `client_email`, `origin_postal_code`, `destination_postal_code`.
   - Returns 400 if a terminal state (CANCELLED, REJECTED, FAILED).

2. **QUOTED → BIDDING** triggered by the first auction being created
   (provider submits an offer for the quotation).

3. **DRAFT → CANCELLED** (or any non-terminal → CANCELLED) via
   `POST /quotation/{id}/cancel` (admin).

4. **BIDDING → AWARDED** when the B2C client selects an offer
   (`PUT /quotation/{id}/auction`).

5. **AWARDED → IN_PROGRESS** when the provider accepts (not implemented
   yet; will be a new endpoint in Phase 2).

6. **IN_PROGRESS → COMPLETED** when the service is delivered
   (not implemented yet).

### Migration 0002

The Alembic migration that landed this design:

- Adds `wizard_step` and `wizard_complete` columns + indexes on
  `wizard_step` and `state`.
- Data migration: maps legacy states to the new model.
  | Old `state`       | New `state` | New `wizard_step` | New `wizard_complete` |
  |-------------------|-------------|--------------------|------------------------|
  | `FILLED`         | `QUOTED`    | `NULL`             | `true`                 |
  | `quoted`         | `QUOTED`    | `NULL`             | `true`                 |
  | `step_3`         | `DRAFT`     | `3`                | `false`                |
  | `step_4`         | `DRAFT`     | `4`                | `false`                |
  | `step_6`         | `DRAFT`     | `6`                | `false`                |
  | `NULL` / other   | (as-is)     | `NULL`             | `false`                |

  14 synthetic records (created during the DDB→PG migration to repair
  FKs) are unaffected — they have `state=NULL` and `client_email='synthetic@orphan.local'`,
  and are filtered out at the service layer.

- Reversible: a `downgrade()` re-maps the values back, lossy on
  `wizard_step` (the destination state values are approximate).

## Code locations

| What | Where |
|---|---|
| State constants | `mobbit-backend-service/app/services/quotation.py` (`ST_DRAFT`, `ST_QUOTED`, etc.) |
| Service logic (publish, cancel) | `mobbit-backend-service/app/services/quotation.py` |
| API endpoints | `mobbit-backend-service/app/api/admin/quotations.py` (`POST .../publish`, `POST .../cancel`) |
| Model | `mobbit-backend-service/app/models/__init__.py` (`Quotation.wizard_step`, `Quotation.wizard_complete`) |
| Schemas | `mobbit-backend-service/app/schemas/__init__.py` (`QuotationRead.wizard_step`, `wizard_complete`) |
| Migration | `mobbit-backend-service/alembic/versions/0002_state_machine_v2.py` |

## Future: wizard rewrite

The current B2C wizard (`/home/victor/github/mobbit/mobbit`, React +
Vite + Redux) will be **rewritten** with newer tech. The schema
above is forward-compatible with any wizard design:

- The new wizard can ignore `wizard_step` and `wizard_complete` entirely
  (admin-created quotations don't set them).
- Or it can set them to whatever step values it wants.
- The publish endpoint doesn't care about wizard internals — it just
  transitions `state` from `DRAFT` to `QUOTED`.

## Open items

- **Provider "list available quotations" endpoint** — Phase 2. The
  current `GET /api/b2c/quotationauctions` returns auctions, not
  quotations. A new `GET /api/provider/quotations?state=QUOTED` would
  be the natural place. For now, providers see quotations only by ID
  (when the B2C wizard links them).
- **Email/push notification on publish** — Phase 5.
- **Audit log** (who published, when) — Phase 5.

## Decision log

| Date | What | Who |
|---|---|---|
| 2026-06-16 | Lifecycle states defined | architect + product |
| 2026-06-16 | `wizard_step` separated from `state` | architect |
| 2026-06-16 | Opción C: explicit `publish` endpoint (no auto-publish) | architect + product |
| 2026-06-16 | Admin uses a form (not a wizard) | product |
| 2026-06-16 | `wizard_data` (JSONB) deferred to future | architect |
