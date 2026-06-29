"""Regression guard — no MercadoPago references in `app/`, `tests/`, OR `web-portal/`.

After PR4 of `stripe-payment-replacement`, the entire backend is Stripe-only.
After T6 of `nextjs-unified-portal-seo`, the unified Next.js frontend is also
Stripe-only. This test pins both invariants so any future change that
accidentally re-introduces MercadoPago references in either codebase fails CI
immediately.

Pinned keywords (case-insensitive):
- `mercadopago` — gateway / module / file references
- `init_point`, `sandbox_init_point` — MercadoPago Preference response fields
- `mp_payment_id`, `mp_preference_id`, `mp_status`, `mp_status_detail` — old column names
- `mercadopago_mock` — old config setting

Excluded paths (intentional, documented):
- `tests/snapshots/openapi.json` — regenerated from the live app; if MP code
  ever re-appears in the app, this file gets updated by the next PR.
- `__pycache__/` — Python bytecode; regenerated on import.
- `web-portal/scripts/no-mp-references.sh` — this guard's sibling script
  on the frontend side (it intentionally mentions the banned keywords to
  document the cutover and the allowlist).
- `web-portal/node_modules/`, `web-portal/.next/` — generated artifacts.
- `web-portal/tests/` — frontend test fixtures that document the cutover.
"""
from __future__ import annotations

import re
from pathlib import Path

# Repo root: tests/test_no_mp_references.py → ../.. → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that MUST NOT contain MercadoPago references.
# `web-portal/` is the Next.js 15 unified portal (T6 of
# nextjs-unified-portal-seo). It's a sibling of the backend submodule,
# located one level up from REPO_ROOT (the backend submodule root).
SCAN_DIRS = [
    REPO_ROOT / "app",
    REPO_ROOT / "tests",
    REPO_ROOT.parent / "web-portal",
]

# Keyword set (case-insensitive). Includes both the gateway name and the
# historical column / config names that PR2's alembic migration removed.
BANNED_KEYWORDS = (
    "mercadopago",
    "init_point",
    "sandbox_init_point",
    "mp_payment_id",
    "mp_preference_id",
    "mp_status",
    "mp_status_detail",
    "mercadopago_mock",
)

# Files that are excluded from the scan (regenerated artifacts).
EXCLUDED_FILES = {
    # Absolute path → skip
    REPO_ROOT / "tests" / "snapshots" / "openapi.json",
    # Migration-regression tests: these explicitly assert that MP fields /
    # endpoints are GONE, so they mention the names by intent.
    # The guard's job is to catch FUTURE production re-introductions, not to
    # fail on tests that document the historical cutover.
    REPO_ROOT / "tests" / "test_auction_service.py",
    REPO_ROOT / "tests" / "test_admin_payments.py",
    # Migration roundtrip tests assert the historical column was dropped.
    REPO_ROOT / "tests" / "test_stripe_migration.py",
    # THIS test file itself: the guard's job is to scan app code + other
    # tests, not to scan itself. Self-reference would create a tautological
    # failure.
    REPO_ROOT / "tests" / "test_no_mp_references.py",
    # The web-portal sibling guard: `web-portal/scripts/no-mp-references.sh`
    # intentionally mentions banned keywords in its docstring + pattern
    # constant to document the cutover and the allowlist. Skipping it
    # avoids a cross-module tautology.
    REPO_ROOT.parent / "web-portal" / "scripts" / "no-mp-references.sh",
}

# File extensions scanned in the web-portal side (Node/TypeScript ecosystem).
# The Python-side scan (app/, tests/) implicitly handles .py files; this
# explicit list keeps the frontend scan narrow to source-ish extensions
# (skip binary, skip generated `.next/`, skip `node_modules/`).
WEB_PORTAL_TEXT_SUFFIXES = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".mdx", ".md", ".json", ".css", ".html",
)

# Files at the web-portal root that are scanned as plain text by Python
# (the rglob below picks them up via the suffix allow-list).
WEB_PORTAL_EXCLUDED_RELATIVE_PATHS = {
    # The web-portal sibling guard itself (excluded as a file above; the
    # relative-path guard below is a defensive double-check for callers
    # that may iterate paths in different orders).
    "scripts/no-mp-references.sh",
    # The ES dictionary contains a docstring comment on line 210 that
    # references `MercadoPago` by name to document the cutover (it lives
    # in the wizard/admin/provider documentation block). The match is
    # documentation only — no active code references MercadoPago.
    "lib/i18n/dictionaries/es.ts",
    # Frontend test fixtures that document the cutover by mentioning the
    # banned keywords (analogous to the backend's migration tests).
    # Add specific paths here if/when the web-portal vitest suite ships.
}


def _scan_for_keywords() -> list[tuple[Path, int, str, str]]:
    """Walk SCAN_DIRS, return list of (path, line_no, keyword, line_text) tuples
    for every banned-keyword match. Skips binary files, excluded files, and
    __pycache__ directories.

    For the web-portal side (the Next.js 15 unified portal), the scan is
    narrowed to source-ish extensions via WEB_PORTAL_TEXT_SUFFIXES so we
    don't accidentally traverse `node_modules/` or `.next/` (which are
    large generated trees). The web-portal's own sibling guard
(`scripts/no-mp-references.sh`) provides a complementary bash-only
    check that's CI-friendly on the frontend side.
    """
    matches: list[tuple[Path, int, str, str]] = []
    pattern = re.compile("|".join(re.escape(kw) for kw in BANNED_KEYWORDS), re.IGNORECASE)

    for root in SCAN_DIRS:
        # Detect whether we're scanning the Python backend (app/, tests/)
        # or the web-portal Node/TS surface.
        is_web_portal = root.name == "web-portal"

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # Skip __pycache__ (Python bytecode; regenerated on import).
            if "__pycache__" in path.parts:
                continue
            # Skip excluded files (absolute path match).
            if path in EXCLUDED_FILES:
                continue
            # Skip generated / vendored trees on the web-portal side.
            if is_web_portal:
                rel_parts = path.relative_to(root).parts
                if rel_parts and rel_parts[0] in {
                    "node_modules",
                    ".next",
                    "public",
                    "tests",
                    ".git",
                    "scripts",
                }:
                    continue
                # Only scan source-ish extensions on the frontend side.
                if path.suffix not in WEB_PORTAL_TEXT_SUFFIXES:
                    continue
                # Defensive double-check for relative-path excludes.
                rel_str = "/".join(rel_parts)
                if rel_str in WEB_PORTAL_EXCLUDED_RELATIVE_PATHS:
                    continue
            else:
                # Skip binary / non-text files by extension on the Python side.
                if path.suffix in {".pyc", ".png", ".jpg", ".gif", ".pdf"}:
                    continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # Binary file we couldn't decode — skip silently.
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                m = pattern.search(line)
                if m is not None:
                    matches.append((path, line_no, m.group(0), line.strip()))
    return matches


def test_no_mercadopago_file_exists() -> None:
    """The `app/services/mercadopago.py` module was deleted in PR4 and MUST
    NOT re-appear in any future change."""
    assert not (REPO_ROOT / "app" / "services" / "mercadopago.py").exists(), (
        "MercadoPago service module re-appeared at app/services/mercadopago.py; "
        "the backend is Stripe-only."
    )


def test_no_mp_webhook_file_exists() -> None:
    """The `app/api/webhooks/mercadopago.py` stub was deleted in PR4 and MUST
    NOT re-appear in any future change."""
    assert not (REPO_ROOT / "app" / "api" / "webhooks" / "mercadopago.py").exists(), (
        "MercadoPago webhook handler re-appeared at app/api/webhooks/mercadopago.py; "
        "the backend is Stripe-only."
    )


def test_no_mercadopago_references_in_app_or_tests() -> None:
        """Grep-scan of `app/`, `tests/`, AND `web-portal/` for any MercadoPago
        keyword. The scan excludes regenerated artifacts (openapi.json),
        __pycache__, and the documented allowlist (the web-portal sibling
        guard + the cutover docstring in `lib/i18n/dictionaries/es.ts`)."""
        matches = _scan_for_keywords()
        if matches:
            # Build a human-readable diff-style report. The web-portal matches
            # live OUTSIDE the backend's REPO_ROOT, so relative_to would raise
            # for those. Walk up to the first common ancestor (the super-repo
            # root) so all matches are reported in a consistent format.
            super_root = REPO_ROOT.parent
            lines = ["Banned MercadoPago keywords found:"]
            for path, line_no, kw, text in matches:
                try:
                    rel = path.relative_to(super_root)
                except ValueError:
                    rel = path
                lines.append(f"  {rel}:{line_no}  [{kw}]  {text}")
            raise AssertionError("\n".join(lines))


def test_env_example_has_stripe_settings() -> None:
    """`.env.example` must list the 4 Stripe settings and MUST NOT contain
    any MERCADOPAGO_* variable."""
    env_path = REPO_ROOT / ".env.example"
    assert env_path.exists(), f".env.example not found at {env_path}"
    text = env_path.read_text(encoding="utf-8")

    required = [
        "STRIPE_SECRET_KEY=",
        "STRIPE_PUBLISHABLE_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "STRIPE_API_VERSION=",
    ]
    for needle in required:
        assert needle in text, f".env.example missing required Stripe setting: {needle}"

    banned = ["MERCADOPAGO_ACCESS_TOKEN", "MERCADOPAGO_API_URL", "MERCADOPAGO_MOCK"]
    for needle in banned:
        assert needle not in text, (
            f".env.example still contains MercadoPago setting: {needle}"
        )


def test_handbook_and_status_documents_stripe() -> None:
    """Workspace docs (`HANDOFF.md`, `STATUS.md`) must mention Stripe in the
    payment context. `STATUS.md` must not still say "webhook MP stub"."""
    # The workspace docs live in the super-repo (one directory up from the
    # submodule). Skip silently if the super-repo isn't present (e.g. when
    # running tests from inside the submodule alone).
    super_root = REPO_ROOT.parent
    handoff = super_root / "HANDOFF.md"
    status = super_root / "STATUS.md"

    if not handoff.exists() or not status.exists():
        # Workspace docs aren't accessible (e.g. CI sandbox only has the
        # submodule mounted). Skip rather than fail.
        import pytest
        pytest.skip("Workspace docs (HANDOFF.md / STATUS.md) not accessible from here")

    handoff_text = handoff.read_text(encoding="utf-8")
    status_text = status.read_text(encoding="utf-8")

    # HANDOFF must mention Stripe somewhere (case-insensitive).
    assert re.search(r"\bstripe\b", handoff_text, re.IGNORECASE), (
        "HANDOFF.md does not mention Stripe; the payment gateway change should "
        "be reflected in the workspace handoff document."
    )

    # STATUS.md must NOT have the line "webhook MP stub" (the obsolete
    # description of Phase 1.1).
    banned_phrase = "webhook MP stub"
    assert banned_phrase not in status_text, (
        f"STATUS.md still contains the obsolete phrase '{banned_phrase}'; "
        f"Phase 1.1 is now Stripe webhook integration."
    )