
# Architecture Decision Records

This directory contains the Architecture Decision Records (ADRs) for
House of Desserts. Each ADR captures a single significant decision,
the context behind it, and the consequences.

## Format

We use the **Nygard template**: Status → Context → Decision → Consequences.

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-record-architecture-decisions.md) | Record Architecture Decisions | Accepted | 2026-09-21 |
| [0002](0002-python-fastapi-backend.md) | Python + FastAPI as Backend | Accepted | 2026-09-21 |
| [0003](0003-sqlite-sqlalchemy-database.md) | SQLite + SQLAlchemy for Data Layer | Accepted | 2026-09-21 |
| [0004](0004-htmx-daisyui-frontend.md) | HTMX + daisyUI for Frontend | Accepted | 2026-09-21 |
| [0006](0006-escpos-thermal-printing.md) | ESC/POS for Thermal Printing | Accepted | 2026-09-21 |
| [0007](0007-environment-configuration.md) | Environment-Based Configuration | Accepted | 2026-09-21 |
| [0008](0008-alembic-migrations.md) | Alembic for Schema Migrations | Accepted | 2026-09-21 |
| [0009](0009-fpdf2-over-weasyprint.md) | fpdf2 for PDF Generation | Accepted | 2026-09-22 |
| [0010](0010-precompiled-css.md) | Pre-compiled CSS (Tailwind Standalone CLI) | Accepted | 2026-09-22 |
| [0011](0011-soft-delete-strategy.md) | Soft Delete for All Entities | Accepted | 2026-09-22 |
| [0012](0012-multi-address-model.md) | Multi-Address per Customer | Accepted | 2026-09-22 |
| [0013](0013-navbar-only-navigation.md) | Navbar-Only Navigation (No Drawer) | Accepted | 2026-09-22 |
| [0014](0014-local-time-over-utc.md) | Local Time (IST) Over UTC | Superseded by 0015 | 2026-09-22 |
| [0015](0015-store-utc-display-ist.md) | Store UTC, Display in the Business Timezone | Accepted | 2026-11-21 |
| [0016](0016-b2b-channel-additive-layer.md) | B2B Channel as an Additive Layer Over Retail Orders | Accepted | 2026-11-21 |
| [0017](0017-order-date-is-a-local-date.md) | `order_date` Is a Local Calendar Date | Accepted | 2026-11-21 |
| [0018](0018-recipes-keyed-to-family.md) | Recipes Keyed to a Product Family, Not a Product | Proposed | 2026-11-26 |
