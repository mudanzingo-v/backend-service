# mobbit-backend-service

FastAPI port of the Mobbit B2B/B2C marketplace **Rust Lambdas**
(`infra-backend-b2c-tf` + `infra-backend-rccm-tf` from
[`../infra/`](../infra/)).

| | |
|---|---|
| **Stack** | Python 3.12 + FastAPI + SQLAlchemy 2 (async) + asyncpg + Alembic |
| **Database** | PostgreSQL 16 |
| **Auth** | Cognito JWT (compatible with the existing user pools) |
| **Scope** | 1:1 port of the B2C and admin endpoints (~50 routes) |
| **Container** | Multi-stage Dockerfile + docker-compose |

> The original Terraform infrastructure is **frozen as MVP**. This
> service is the next-generation implementation that fixes several
> bugs identified in `../infra/docs/research/business-domain.md`
> (e.g. the §5.2 pricing bug) and re-implements the same business
> flow with a relational store and a typed HTTP layer.

---

## Quickstart

```bash
# 1. Copy env template and fill in (or use defaults for local dev)
cp .env.example .env

# 2. Build + run
docker compose up --build

# 3. Hit it
curl http://localhost:8000/health
# → {"status": "ok", "service": "mobbit-backend-service", "env": "local"}

# 4. Open Swagger UI
open http://localhost:8000/docs
```

To run **without** Docker:

```bash
# Needs Python 3.12+ and a running Postgres
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

---

## Project layout

```
mobbit-backend-service/
├── app/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Pydantic settings (env-driven)
│   ├── core/
│   │   ├── auth.py              # Cognito JWT validation
│   │   ├── database.py          # Async SQLAlchemy session
│   │   ├── exceptions.py        # Custom errors + handlers
│   │   └── logging.py           # JSON in prod, text in dev
│   ├── models/                  # SQLAlchemy ORM models
│   ├── schemas/                 # Pydantic request/response
│   ├── services/                # Business logic
│   │   ├── pricing.py           # mobbit_fee, iva, transaction_fee
│   │   ├── mercadopago.py       # MP API client
│   │   ├── copomex.py           # Postal code lookup
│   │   ├── quotation.py
│   │   └── auction.py
│   └── api/
│       ├── b2c/                 # /api/b2c/...
│       │   ├── quotations.py
│       │   ├── auctions.py
│       │   ├── catalog.py
│       │   └── router.py
│       ├── admin/               # /api/admin/... (Cognito rccm required)
│       │   ├── quotations.py
│       │   ├── catalog.py
│       │   ├── providers.py
│       │   ├── salers.py
│       │   ├── auctions.py
│       │   ├── payments.py
│       │   └── router.py
│       └── webhooks/
│           └── mercadopago.py   # POST /webhooks/payments/mercadopago
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py      # All tables in one migration
├── tests/                       # (skeleton — see TODO below)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── .env.example
└── README.md (this file)
```

---

## Endpoints

### `/api/b2c/` (public; some require Cognito JWT)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/b2c/quotation` | B2C lead (only contact info) |
| `GET` | `/api/b2c/quotation/{id}` | Single quotation |
| `PUT` | `/api/b2c/quotation/{id}` | Update (B2C) |
| `GET` | `/api/b2c/quotation/{id}/auctions` | All auctions for a quotation |
| `PUT` | `/api/b2c/quotation/{id}/auction` | Select an auction → creates MP preference |
| `GET` | `/api/b2c/quotationauctions` | All auctions (top-level) |
| `GET` | `/api/b2c/quotation/{id}/auction/{aid}/preference` | MP preference for an auction |
| `GET` | `/api/b2c/location/{postal_code}` | Copomex proxy |
| `GET` | `/api/b2c/inventory/items` | All inventory items |
| `GET` | `/api/b2c/inventory/{category_id}/items` | Items in a category |
| `GET` | `/api/b2c/products` | All products |
| `GET` | `/api/b2c/services` | All services |

### `/api/admin/` (requires Cognito `rccm-users` JWT)

| Domain | Routes |
|---|---|
| **Quotations** | `POST/GET/PUT/DELETE /api/admin/quotation[/{id}]`, `GET /api/admin/quotation` |
| **Auctions** | `POST /api/admin/quotation/{qid}/provider/{pid}/auction`, `GET/PUT/DELETE /api/admin/auction/{id}` |
| **Payments** | `POST /api/admin/quotation/{qid}/payment/mercadopago`, `POST .../deposito`, `GET .../payment/s`, `GET /api/admin/payment/{id}` |
| **Products** | `POST/GET/PUT/DELETE /api/admin/product[/{id}]` |
| **Services** | `POST/GET/PUT/DELETE /api/admin/service[/{id}]` |
| **Inventory categories** | `POST/GET /api/admin/inventory/category[/{id}]` |
| **Inventory items** | `POST/GET/PUT /api/admin/inventory/category/{cid}/item[/{id}]`, `GET /api/admin/inventory/items` |
| **Providers** | `POST/GET/PUT /api/admin/provider[/{id}]` |
| **Trucks** | `POST/GET/PUT /api/admin/provider/{pid}/truck[/{id}]` |
| **Salers** | `POST/GET/PUT/DELETE /api/admin/saler[/{id}]` |

### `/webhooks/`

| Method | Path | Status |
|---|---|---|
| `POST` | `/webhooks/payments/mercadopago` | **STUB** (matches original Lambda) |

---

## Auth

The original Lambdas used API Gateway's Cognito authorizer. This service
validates the JWT in-process with `python-jose` against the Cognito JWKS
endpoint (cached in-memory for 10 minutes).

| Dependency | Pool | When |
|---|---|---|
| `current_user` | any | Future use |
| `current_provider` | `providers` | Future B2B endpoints |
| `current_admin` | `rccm-users` | All `/api/admin/...` endpoints |

For local dev, set `AUTH_SKIP_VERIFICATION=true` to skip signature
checking (the JWT is still decoded). **Never** in prod.

---

## Environment

See [`.env.example`](.env.example). The most important knobs:

| Var | Default | Effect |
|---|---|---|
| `APP_ENV` | `local` | `local` \| `dev` \| `staging` \| `prod` |
| `DATABASE_URL` | `postgresql+asyncpg://mobbit:mobbit@db:5432/mobbit` | asyncpg URL |
| `COGNITO_USER_POOL_*` | real values from `infra-base-t/cognito.tf` | JWT validation |
| `MERCADOPAGO_ACCESS_TOKEN` | empty | **Required** for any MP endpoint to work |
| `COPOMEX_API_TOKEN` | empty | **Required** for `/api/b2c/location/...` |
| `PRICING_MOBBIT_FEE` | `0.05` | Override the hardcoded constant |
| `PRICING_IVA` | `0.16` | Same |
| `PRICING_TRANSACTION_FEE` | `0.05` | Same |
| `AUTH_SKIP_VERIFICATION` | `false` | Dev only |

---

## Differences from the original Lambdas

The new service **is not a byte-for-byte port** — it cleans up several
known issues. Material changes:

1. **Database**: DynamoDB single-table → Postgres relational. The
   `pk/sk` partition scheme is replaced by FK relationships. The
   `auctions` table still has a `UNIQUE(quotation_id, provider_id)`
   constraint to match the original `pk=QUOTATION#<q>, sk=AUCTION#<p>`
   identity.
2. **Pricing bug fix**: `services/pricing.py` uses the *calculated*
   `mobbit_fee_value` in `transaction_fee` and `total`, not the
   raw constant. See `docs/research/business-domain.md` §5.2.
3. **No hardcoded secrets**: MP and Copomex tokens are read from env.
4. **No `scan()`**: All queries use indexes and `select()`.
5. **Pydantic validation on every body**: email format, non-empty
   strings, decimal parsing, etc.
6. **Money as `Numeric(12, 2)`**, not stringified float. `as i32`
   truncation is gone.
7. **Field name fixes**: `lenght` → `length`, `weigh` → `weight`
   in the inventory item schema.
8. **State machine hint** in `auctions.state` (PENDING/SELECTED/
   REJECTED/ACCEPTED/PAID) but the field is still free-form (matches
   the original behaviour).
9. **Webhook** is still a stub (matches the original). The route
   exists; the business logic is documented in
   `app/api/webhooks/mercadopago.py` for the next person to implement.

---

## Tests

The `tests/` directory is a skeleton. Suggested next steps:

```bash
pip install -e ".[dev]"
pytest
```

Recommended test setup (not in this MVP):
- `pytest-asyncio` for the async endpoints
- `httpx.AsyncClient` with `ASGITransport` for in-process testing
- `testcontainers` for ephemeral Postgres in CI

---

## Deployment

The `Dockerfile` is multi-stage (builder + slim runtime, non-root user).
The `docker-compose.yml` adds a Postgres for local dev.

For a real deployment:
- Build: `docker build -t mobbit-backend-service:0.1.0 .`
- Push to your registry
- Run with `DATABASE_URL` pointing at a managed Postgres (RDS, Aurora,
  Cloud SQL, etc.)
- Set `APP_ENV=prod` and `AUTH_SKIP_VERIFICATION=false`
- Mount secrets via your platform (SSM, Vault, K8s secrets)

---

## Reference docs

- `../infra/docs/research/business-domain.md` — business flow, entity
  model, pricing, gaps from the original Lambdas.
- `../infra/docs/research/deployment-drift.md` — what's actually
  deployed in AWS (helpful when debugging JWT claims etc.).
- `../infra/docs/BLUEPRINT.md` — the architecture decisions this port
  inherits.

---

## Documentación adicional

| Doc | Tema |
|---|---|
| [`docs/research/state-machine-design.md`](docs/research/state-machine-design.md) | Diseño del state machine de Quotation (D3) |
| [`../../docs/research/auction-flow-design.md`](../../docs/research/auction-flow-design.md) | Diseño del flow de auctions (admin assign + provider) |
| [`../../docs/operations/testing-guide.md`](../../docs/operations/testing-guide.md) | Cómo probar los endpoints |
| [`../../docs/operations/troubleshooting.md`](../../docs/operations/troubleshooting.md) | Problemas comunes |

## Endpoints

### Admin (auth: rccm pool)
- `GET/POST /api/admin/quotation` — listar/crear cotizaciones
- `GET/PUT/DELETE /api/admin/quotation/{id}` — detail/update/delete
- `POST /api/admin/quotation/{id}/publish` — DRAFT → QUOTED
- `POST /api/admin/quotation/{id}/cancel` — cancel
- **`POST /api/admin/quotation/{id}/assign-provider?provider_id=...`** — asignar provider con budget
- `GET /api/admin/auction?quotation_id=...&limit=100` — listar auctions
- `GET/PUT/DELETE /api/admin/auction/{id}` — detail/update/delete
- `GET/POST /api/admin/product[/{id}]` — CRUD products
- `GET/POST /api/admin/service[/{id}]` — CRUD services
- `GET/POST /api/admin/inventory/category[/{id}]` — CRUD categories
- `GET/POST /api/admin/inventory/category/{id}/item[/{item_id}]` — CRUD items
- `GET/POST /api/admin/provider[/{id}]` — CRUD providers
- `GET/POST /api/admin/provider/{id}/truck[/{truck_id}]` — CRUD trucks
- `GET/POST /api/admin/saler[/{id}]` — CRUD salers
- `GET /api/admin/quotation/{id}/payment/s` — listar payments de una quotation
- `GET /api/admin/payment/{id}` — detail de un payment
- `GET /api/admin/stats` — conteos en vivo

### B2C (sin auth, público)
- `POST /api/b2c/quotation` — crear quotation
- `GET/PUT /api/b2c/quotation/{id}` — detail/update
- `GET /api/b2c/quotation/{id}/auctions` — listar auctions (filtrado a PENDING en la selección)
- `PUT /api/b2c/quotation/{id}/auction` — seleccionar auction (crea preference + payment)
- `GET /api/b2c/products` — listar productos
- `GET /api/b2c/services` — listar servicios
- `GET /api/b2c/inventory/items` — listar items
- `GET /api/b2c/inventory/{category_id}/items` — items por categoría
- `GET /api/b2c/location/{postal_code}` — lookup de ubicación

### Provider (auth: providers pool)
- `GET /api/provider/profile` — mi perfil
- `GET /api/provider/auction?state=PENDING&limit=100` — mis auctions
- `GET /api/provider/auction/{id}` — detail de mi auction
- `PUT /api/provider/auction/{id}` — aceptar / counter-offer
- `POST /api/provider/auction/{id}/decline` — rechazar

### Webhooks
- `POST /webhooks/payments/mercadopago` — webhook de MP (stub — Phase 1.1)

### Health
- `GET /health` — health check
- `GET /` — info del servicio
- `GET /docs` — Swagger UI
- `GET /openapi.json` — OpenAPI schema
