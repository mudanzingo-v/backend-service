"""
Migrate DynamoDB → PostgreSQL for Mobbit Backend Service.

Source: AWS DynamoDB table `mobbit` (single-table design) in the
account configured by AWS_PROFILE.

Target: PostgreSQL via `DATABASE_URL` env var (asyncpg).

Run from the project root:
    python -m scripts.migrate_ddb_to_pg

Behaviour:
- Scans the entire DDB table (paginated, 234 items expected).
- Truncates the target Postgres tables (in dependency order).
- Inserts rows in dependency order: providers → salers → services
  → products → inventory_categories → inventory_items → trucks →
  quotations → auctions → preferences.

Notes on the DDB schema (see also docs/research/business-domain.md):
- Money fields are stored as **strings** in DDB (e.g. `"6132"`).
  We parse them to `Decimal` for Postgres.
- Some fields use DDB String Sets (`SS`) or Lists of Maps (`L`/`M`).
  We map them to JSONB in Postgres.
- Field renames:
  * InventoryItem: `lenght` → `length`, `weigh` → `weight`
  * Product: `precio` → `price` (extra field `cantidad` preserved as JSONB)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg
import boto3
from botocore.config import Config

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate")


# =============================================================================
# Helpers: parse DDB AttributeValue shapes
# =============================================================================
def _s(item: dict, key: str) -> str | None:
    """Get a string attribute or None."""
    val = item.get(key)
    if not val:
        return None
    if "S" in val:
        return val["S"]
    return None


def _n(item: dict, key: str) -> Decimal | None:
    """Get a numeric attribute as Decimal or None."""
    val = item.get(key)
    if not val:
        return None
    if "N" in val:
        try:
            return Decimal(val["N"])
        except InvalidOperation:
            return None
    if "S" in val:
        try:
            return Decimal(val["S"])
        except InvalidOperation:
            return None
    return None


def _ss_to_list(item: dict, key: str) -> list[str] | None:
    """Get a StringSet as a list, or None."""
    val = item.get(key)
    if not val:
        return None
    if "SS" in val:
        return list(val["SS"])
    if "S" in val:
        return [val["S"]]
    if "L" in val:
        return [v.get("S", "") for v in val["L"] if "S" in v]
    return None


def _l_to_jsonb(item: dict, key: str) -> str | None:
    """Get a List/Map attribute and serialize to JSON for JSONB."""
    val = item.get(key)
    if not val:
        return None
    if "L" in val or "M" in val or "SS" in val:
        return json.dumps(val.get("L") or val.get("M") or list(val.get("SS", [])),
                         default=str, ensure_ascii=False)
    if "S" in val:
        return json.dumps([val["S"]], ensure_ascii=False)
    return None


def _split_pk(pk: str) -> tuple[str, str]:
    """`QUOTATION#<uuid>` → ('QUOTATION', '<uuid>')"""
    if "#" not in pk:
        return (pk, "")
    parts = pk.split("#", 1)
    return (parts[0], parts[1])


def _split_sk(sk: str) -> tuple[str, str]:
    """`AUCTION#<id>` → ('AUCTION', '<id>') ; `METADATA` → ('METADATA', '')"""
    if "#" not in sk:
        return (sk, "")
    parts = sk.split("#", 1)
    return (parts[0], parts[1])


# ---- Timestamp parsing ----
def _parse_ts(s: str | None) -> datetime | None:
    """
    Parse a DDB-style timestamp string and return a NAIVE datetime in UTC.
    Examples seen in the data:
      - "2026-06-13 18:02:19.022180878 -06:00"
      - "2023-11-27T18:40:30.798-04:00"
    Returns None on failure (so the SQL uses NOW()).
    """
    if not s:
        return None
    s = s.strip()
    parsed: datetime | None = None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f %z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            parsed = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(s)
        except ValueError:
            return None
    # Normalise to naive UTC for Postgres TIMESTAMP
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


# =============================================================================
# Mappers: DDB item → Postgres row
# =============================================================================
def map_inventory_category(item: dict) -> dict:
    # pk = "INVENTORY#CATEGORY#<id>" — extract the last segment
    pk = _s(item, "pk") or ""
    parts = pk.split("#")
    cat_id = parts[-1] if len(parts) >= 3 else ""
    return {
        "id": cat_id,
        "name": _s(item, "name") or "",
        "description": _s(item, "description"),
        "active": True,
    }


def map_inventory_item(item: dict) -> dict:
    # pk = "INVENTORY#CATEGORY#<cat_id>", sk = "ITEM#<item_id>"
    pk = _s(item, "pk") or ""
    sk = _s(item, "sk") or ""
    cat_id = pk.split("#")[-1]
    item_id = sk.split("#", 1)[1] if "#" in sk else sk
    return {
        "id": item_id,
        "name": _s(item, "name") or "",
        "url_image": _s(item, "url_image"),
        "length": _n(item, "lenght"),  # typo in DDB
        "width": _n(item, "width"),
        "height": _n(item, "height"),
        "weight": _n(item, "weigh"),  # typo in DDB
        "category_id": cat_id,
        "active": True,
    }


def map_provider(item: dict) -> dict:
    _, prov_id = _split_pk(_s(item, "pk") or "")
    first = _s(item, "first_name") or ""
    last = _s(item, "last_name") or ""
    name = _s(item, "name") or _s(item, "company_name") or f"{first} {last}".strip()
    return {
        "id": prov_id,
        "email": _s(item, "email"),
        "name": name or None,
        "phone": _s(item, "phone"),
        "rfc": _s(item, "rfc"),
        "address": _s(item, "address"),
        "active": True,
    }


def map_truck(item: dict) -> dict:
    _, prov_id = _split_pk(_s(item, "pk") or "")
    _, truck_id = _split_sk(_s(item, "sk") or "")
    return {
        "id": truck_id,
        "provider_id": prov_id,
        "brand": _s(item, "brand"),
        "model": _s(item, "model"),
        "year": int(_n(item, "year") or 0) or None,
        "plates": _s(item, "car_id") or _s(item, "plates"),
        "capacity_kg": _n(item, "capacity"),
        "capacity_m3": _n(item, "capacity_m3"),
        "active": True,
    }


def map_saler(item: dict) -> dict:
    _, saler_id = _split_pk(_s(item, "pk") or "")
    return {
        "id": saler_id,
        "name": _s(item, "name") or "",
        "email": _s(item, "email"),
        "phone": _s(item, "phone"),
        "commission_pct": _n(item, "commission_pct"),
        "active": True,
    }


def map_service(item: dict) -> dict:
    _, svc_id = _split_pk(_s(item, "pk") or "")
    return {
        "id": svc_id,
        "name": _s(item, "name") or "",
        "description": _s(item, "code"),  # original used `code` as a kind of slug
        "price": _n(item, "base_price") or _n(item, "price"),
        "active": True,
    }


def map_product(item: dict) -> dict:
    _, prod_id = _split_pk(_s(item, "pk") or "")
    return {
        "id": prod_id,
        "name": _s(item, "name") or "",
        "description": _s(item, "description"),
        "sku": _s(item, "sku"),
        "price": _n(item, "precio") or _n(item, "price"),
        "url_image": _s(item, "url_image"),
        "category_id": _s(item, "category_id"),
        "active": True,
    }


def map_quotation(item: dict) -> dict:
    _, q_id = _split_pk(_s(item, "pk") or "")
    services_list = _ss_to_list(item, "services")
    services_json = json.dumps(services_list, ensure_ascii=False) if services_list else None
    products_l = _l_to_jsonb(item, "products")
    items_l = _l_to_jsonb(item, "items")
    return {
        "id": q_id,
        "client_name": _s(item, "client_name") or "",
        "client_phone": _s(item, "client_phone") or "",
        "client_email": _s(item, "client_email") or "",
        "channel_sales": _s(item, "channel_sales"),
        "state": _s(item, "state"),
        "service_name": _s(item, "service_name"),
        "service_type": _s(item, "service_type"),
        "service_zone": _s(item, "service_zone"),
        "service_hour": _s(item, "service_hour"),
        "service_date": _s(item, "service_date"),
        "service_internal": _s(item, "service_internal"),
        "id_saler": _s(item, "id_saler"),
        "saler": _l_to_jsonb(item, "saler"),
        "origin_postal_code": _s(item, "origin_postal_code"),
        "origin_adress": _s(item, "origin_adress"),
        "origin_type": _s(item, "origin_type"),
        "origin_transport_type": _s(item, "origin_transport_type"),
        "origin_pulley": _s(item, "origin_pulley"),
        "origin_restrictions": _s(item, "origin_restrictions"),
        "origin_floor": _s(item, "origin_floor"),
        "destination_postal_code": _s(item, "destination_postal_code"),
        "destination_adress": _s(item, "destination_adress"),
        "destination_type": _s(item, "destination_type"),
        "destination_transport_type": _s(item, "destination_transport_type"),
        "destination_pulley": _s(item, "destination_pulley"),
        "destination_restrictions": _s(item, "destination_restrictions"),
        "destination_floor": _s(item, "destination_floor"),
        "services": services_json,
        "products": products_l,
        "items": items_l,
        "created_at": _parse_ts(_s(item, "created_at")),
        "updated_at": _parse_ts(_s(item, "created_at")),
    }


def map_auction(item: dict) -> dict:
    """
    DDB: pk=QUOTATION#<q>, sk=AUCTION#<uuid>.
    The original Rust design used sk=AUCTION#<provider_id>; in practice the
    data has UUIDs there. We honour the data: sk suffix is the auction's own
    id, and we also store it as provider_id (since the docs say so).
    """
    _, q_id = _split_pk(_s(item, "pk") or "")
    _, a_id = _split_sk(_s(item, "sk") or "")
    return {
        "id": a_id,
        "quotation_id": q_id,
        "provider_id": a_id,  # see docstring — original design
        "price_load": _n(item, "price_load") or Decimal("0"),
        "subtotal": _n(item, "subtotal") or Decimal("0"),
        "mobbit_fee": _n(item, "mobbit_fee") or Decimal("0"),
        "iva": _n(item, "iva") or Decimal("0"),
        "transaction_fee": _n(item, "transaction_fee") or Decimal("0"),
        "total": _n(item, "total") or Decimal("0"),
        "cash_on_delivery_provider": _n(item, "cash_on_delivery_provider"),
        "cash_on_delivery_mobbit": _n(item, "cash_on_delivery_mobbit"),
        "people": _s(item, "people"),
        "id_truck": _s(item, "id_truck"),
        "state": _s(item, "state") or "PENDING",
        "services": _l_to_jsonb(item, "services"),
        "products": _l_to_jsonb(item, "products"),
        "created_at": _parse_ts(_s(item, "created_at")),
        "updated_at": _parse_ts(_s(item, "created_at")),
    }


def map_preference(item: dict) -> dict:
    import uuid as _uuid
    _, a_id = _split_pk(_s(item, "pk") or "")
    # We need to find the auction_id for this AUCTION#<a_id>.
    # In our relational model, Auction.id = the a_id (see map_auction).
    return {
        "id": str(_uuid.uuid4()),
        "auction_id_external": a_id,
        "mp_id": _s(item, "id"),
        "init_point": _s(item, "init_point"),
        "sandbox_init_point": _s(item, "sandbox_init_point"),
        "date_created": _s(item, "date_created"),
        "client_id": _s(item, "client_id"),
        "collector_id": _s(item, "collector_id"),
        "operation_type": _s(item, "operation_type"),
        "items": _s(item, "items"),
        "payer": _s(item, "payer"),
        "shipment": _s(item, "shipment"),
        "created_at": _parse_ts(_s(item, "date_created")),
    }


# =============================================================================
# Migration
# =============================================================================
async def migrate() -> None:
    ddb_table = os.environ.get("DDB_TABLE", "mobbit")
    aws_region = os.environ.get("AWS_REGION", "us-west-2")
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL is not set")
        sys.exit(1)

    log.info("Connecting to DynamoDB %s in %s", ddb_table, aws_region)
    ddb = boto3.client(
        "dynamodb",
        region_name=aws_region,
        config=Config(retries={"max_attempts": 5}),
    )

    log.info("Scanning DynamoDB table %s ...", ddb_table)
    items: list[dict] = []
    scan_kwargs: dict[str, Any] = {"TableName": ddb_table}
    while True:
        resp = ddb.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    log.info("Scanned %d items from DynamoDB", len(items))

    # Bucket by entity
    buckets: dict[str, list[dict]] = {
        "providers": [],
        "salers": [],
        "services": [],
        "products": [],
        "inv_categories": [],
        "inv_items": [],
        "trucks": [],
        "quotations": [],
        "auctions": [],
        "preferences": [],
        "unknown": [],
    }
    for item in items:
        pk = _s(item, "pk") or ""
        sk = _s(item, "sk") or ""
        pk_pref, _ = _split_pk(pk)
        sk_pref, _ = _split_sk(sk)
        if pk_pref == "INVENTORY" and sk == "METADATA":
            buckets["inv_categories"].append(item)
        elif pk_pref == "INVENTORY" and sk_pref == "ITEM":
            buckets["inv_items"].append(item)
        elif pk_pref == "PROVIDER" and sk == "METADATA":
            buckets["providers"].append(item)
        elif pk_pref == "PROVIDER" and sk_pref == "TRUCK":
            buckets["trucks"].append(item)
        elif pk_pref == "SALER":
            buckets["salers"].append(item)
        elif pk_pref == "SERVICE":
            buckets["services"].append(item)
        elif pk_pref == "PRODUCT":
            buckets["products"].append(item)
        elif pk_pref == "QUOTATION" and sk == "METADATA":
            buckets["quotations"].append(item)
        elif pk_pref == "QUOTATION" and sk_pref == "AUCTION":
            buckets["auctions"].append(item)
        elif pk_pref == "AUCTION" and sk == "PREFERENCE":
            buckets["preferences"].append(item)
        else:
            buckets["unknown"].append(item)
            log.warning("Unknown item: pk=%s sk=%s", pk, sk)

    for k, v in buckets.items():
        log.info("Bucketed: %s = %d", k, len(v))

    log.info("Connecting to PostgreSQL ...")
    conn = await asyncpg.connect(db_url)

    try:
        # ---- Truncate in reverse-dependency order ----
        log.info("Truncating tables ...")
        await conn.execute("""
            TRUNCATE TABLE
                payments, preferences, auctions, quotations,
                trucks, providers, salers, products, services,
                inventory_items, inventory_categories
            RESTART IDENTITY CASCADE
        """)

        # ---- Insert in dependency order ----
        async def bulk(
            table: str,
            cols: list[str],
            rows: list[dict],
            transform=None,
            timestamps: bool = True,
        ) -> None:
            """
            Bulk insert helper.

            - `cols`: column names to insert (in order).
            - `transform`: function from raw DDB item to dict.
            - `timestamps`: if True, automatically append `created_at` and
              `updated_at` columns, using the DDB value if present, else NOW().
            """
            if not rows:
                return
            t = transform or (lambda r: r)
            extra_cols: list[str] = []
            extra_sql: list[str] = []
            if timestamps:
                extra_cols = ["created_at", "updated_at"]
                extra_sql = [
                    f"COALESCE(${len(cols)+1}::timestamp, NOW())",
                    f"COALESCE(${len(cols)+2}::timestamp, NOW())",
                ]
            all_sql = ",".join(cols) + ("," + ",".join(extra_cols) if extra_cols else "")
            placeholders_inner = (
                ",".join(f"${i+1}" for i in range(len(cols)))
                + ("," + ",".join(extra_sql) if extra_sql else "")
            )
            sql = f"INSERT INTO {table} ({all_sql}) VALUES ({placeholders_inner})"
            # Build values
            values = []
            for r in rows:
                mapped = t(r)
                row_values = [mapped.get(c) for c in cols]
                if timestamps:
                    row_values.append(mapped.get("created_at"))
                    row_values.append(mapped.get("updated_at"))
                values.append(tuple(row_values))
            log.info("Inserting %d rows into %s ...", len(rows), table)
            await conn.executemany(sql, values)

        # Providers (no FK deps)
        await bulk("providers",
                   ["id", "email", "name", "phone", "rfc", "address", "active"],
                   buckets["providers"], map_provider)

        # Salers (no FK deps)
        await bulk("salers",
                   ["id", "name", "email", "phone", "commission_pct", "active"],
                   buckets["salers"], map_saler)

        # Services (no FK deps)
        await bulk("services",
                   ["id", "name", "description", "price", "active"],
                   buckets["services"], map_service)

        # Products (no FK deps; category_id is string, may or may not match an InvCategory)
        await bulk("products",
                   ["id", "name", "description", "sku", "price", "url_image", "category_id", "active"],
                   buckets["products"], map_product)

        # Inventory Categories (no FK deps)
        await bulk("inventory_categories",
                   ["id", "name", "description", "active"],
                   buckets["inv_categories"], map_inventory_category)

        # Inventory Items (FK → inventory_categories)
        # First, make sure every category referenced by an item exists.
        # If not, create a synthetic one (data inconsistency in DDB).
        existing_cat_ids = {
            r["id"]
            for r in await conn.fetch("SELECT id FROM inventory_categories")
        }
        referenced_cat_ids = set()
        for it in buckets["inv_items"]:
            cat_id = it["pk"]["S"].split("#")[-1]
            referenced_cat_ids.add(cat_id)
        missing = referenced_cat_ids - existing_cat_ids
        if missing:
            log.warning(
                "Creating %d synthetic categories for orphan items: %s",
                len(missing),
                sorted(missing)[:5],
            )
            for cat_id in missing:
                await conn.execute("""
                    INSERT INTO inventory_categories
                        (id, name, description, active, created_at, updated_at)
                    VALUES ($1, $2, NULL, FALSE, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """, cat_id, "(synthetic — referenced by items but missing in DDB)")

        await bulk("inventory_items",
                   ["id", "name", "url_image", "length", "width", "height", "weight",
                    "category_id", "active"],
                   buckets["inv_items"], map_inventory_item)

        # Trucks (FK → providers)
        # Same fallback as inventory: synthetic providers if missing.
        existing_prov_ids = {r["id"] for r in await conn.fetch("SELECT id FROM providers")}
        referenced_prov_ids = set()
        for t in buckets["trucks"]:
            prov_id = t["pk"]["S"].split("#", 1)[1]
            referenced_prov_ids.add(prov_id)
        missing_prov = referenced_prov_ids - existing_prov_ids
        if missing_prov:
            log.warning(
                "Creating %d synthetic providers for orphan trucks: %s",
                len(missing_prov),
                sorted(missing_prov)[:5],
            )
            for pid in missing_prov:
                await conn.execute("""
                    INSERT INTO providers (id, active, created_at, updated_at)
                    VALUES ($1, FALSE, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """, pid)

        await bulk("trucks",
                   ["id", "provider_id", "brand", "model", "year", "plates",
                    "capacity_kg", "capacity_m3", "active"],
                   buckets["trucks"], map_truck)

        # Quotations (no FK deps; some columns are JSONB → we cast in SQL)
        log.info("Inserting %d quotations ...", len(buckets["quotations"]))
        q_rows = buckets["quotations"]
        for q in q_rows:
            m = map_quotation(q)
            await conn.execute("""
                INSERT INTO quotations (
                    id, client_name, client_phone, client_email,
                    channel_sales, state, service_name, service_type, service_zone,
                    service_hour, service_date, service_internal, id_saler, saler,
                    origin_postal_code, origin_adress, origin_type,
                    origin_transport_type, origin_pulley, origin_restrictions, origin_floor,
                    destination_postal_code, destination_adress, destination_type,
                    destination_transport_type, destination_pulley, destination_restrictions,
                    destination_floor,
                    services, products, items, created_at, updated_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,
                    $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,
                    $29::jsonb,$30::jsonb,$31::jsonb,$32::timestamp,$33::timestamp
                )
                ON CONFLICT (id) DO NOTHING
            """,
                m["id"], m["client_name"], m["client_phone"], m["client_email"],
                m["channel_sales"], m["state"], m["service_name"], m["service_type"],
                m["service_zone"], m["service_hour"], m["service_date"], m["service_internal"],
                m["id_saler"], m["saler"],
                m["origin_postal_code"], m["origin_adress"], m["origin_type"],
                m["origin_transport_type"], m["origin_pulley"], m["origin_restrictions"],
                m["origin_floor"],
                m["destination_postal_code"], m["destination_adress"], m["destination_type"],
                m["destination_transport_type"], m["destination_pulley"],
                m["destination_restrictions"], m["destination_floor"],
                m["services"], m["products"], m["items"],
                m["created_at"], m["updated_at"],
            )

        # Auctions (FK → quotations)
        # Same fallback: create synthetic quotations if any auction references
        # one that doesn't exist.
        existing_q_ids = {r["id"] for r in await conn.fetch("SELECT id FROM quotations")}
        referenced_q_ids = set()
        for a in buckets["auctions"]:
            q_id = a["pk"]["S"].split("#", 1)[1]
            referenced_q_ids.add(q_id)
        missing_q = referenced_q_ids - existing_q_ids
        if missing_q:
            log.warning(
                "Creating %d synthetic quotations for orphan auctions: %s",
                len(missing_q),
                sorted(missing_q)[:5],
            )
            for qid in missing_q:
                await conn.execute("""
                    INSERT INTO quotations
                        (id, client_name, client_phone, client_email,
                         state, created_at, updated_at)
                    VALUES ($1, '(synthetic)', '0000000000', 'synthetic@orphan.local',
                            NULL, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """, qid)

        log.info("Upserting %d auctions ...", len(buckets["auctions"]))
        for a in buckets["auctions"]:
            m = map_auction(a)
            await conn.execute("""
                INSERT INTO auctions (
                    id, quotation_id, provider_id,
                    price_load, subtotal, mobbit_fee, iva, transaction_fee, total,
                    cash_on_delivery_provider, cash_on_delivery_mobbit,
                    people, id_truck, state, services, products,
                    created_at, updated_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                    $15::jsonb,$16::jsonb,
                    COALESCE($17::timestamp, NOW()),
                    COALESCE($18::timestamp, NOW())
                )
                ON CONFLICT (id) DO UPDATE SET
                    quotation_id = EXCLUDED.quotation_id,
                    provider_id = EXCLUDED.provider_id,
                    price_load = EXCLUDED.price_load,
                    subtotal = EXCLUDED.subtotal,
                    mobbit_fee = EXCLUDED.mobbit_fee,
                    iva = EXCLUDED.iva,
                    transaction_fee = EXCLUDED.transaction_fee,
                    total = EXCLUDED.total,
                    cash_on_delivery_provider = EXCLUDED.cash_on_delivery_provider,
                    cash_on_delivery_mobbit = EXCLUDED.cash_on_delivery_mobbit,
                    people = EXCLUDED.people,
                    id_truck = EXCLUDED.id_truck,
                    state = EXCLUDED.state,
                    services = EXCLUDED.services,
                    products = EXCLUDED.products,
                    updated_at = EXCLUDED.updated_at
            """,
                m["id"], m["quotation_id"], m["provider_id"],
                m["price_load"], m["subtotal"], m["mobbit_fee"], m["iva"],
                m["transaction_fee"], m["total"],
                m["cash_on_delivery_provider"], m["cash_on_delivery_mobbit"],
                m["people"], m["id_truck"], m["state"],
                m["services"], m["products"],
                m["created_at"], m["updated_at"],
            )

        # Preferences (FK → auctions)
        log.info("Inserting %d preferences ...", len(buckets["preferences"]))
        for p in buckets["preferences"]:
            m = map_preference(p)
            # Look up the auction's internal id by external provider_id (=auction id)
            row = await conn.fetchrow(
                "SELECT id FROM auctions WHERE id = $1", m["auction_id_external"]
            )
            if row is None:
                log.warning(
                    "Skipping preference for unknown auction %s", m["auction_id_external"]
                )
                continue
            await conn.execute("""
                INSERT INTO preferences (
                    id, auction_id, mp_id, init_point, sandbox_init_point, date_created,
                    client_id, collector_id, operation_type, items, payer, shipment,
                    created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    COALESCE($13::timestamp, NOW())
                )
            """,
                m["id"], row["id"], m["mp_id"], m["init_point"], m["sandbox_init_point"],
                m["date_created"], m["client_id"], m["collector_id"], m["operation_type"],
                m["items"], m["payer"], m["shipment"], m["created_at"],
            )

        log.info("Migration complete.")
        log.info("Unknown items (skipped): %d", len(buckets["unknown"]))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
