# One-off migration scripts

These scripts were written to perform **one-time** code transformations during
development (schema renames, lint cleanups, test-shape fixes). They are kept
here for historical reference only — they are **not** part of the runtime and
should not be needed for normal use.

| Script | What it did |
|---|---|
| `cleanup_hsn.py` | Removed `hsn_code` references after the v0.3 product schema change (HSN replaced by SKU). |
| `cleanup_ruff.py` | Surgical fixes for remaining ruff findings. |
| `fix_test_filter.py` | Repaired a SQLAlchemy filter-expression typo in a test. |
| `patch_tests_fulfillment.py` | Added `fulfillment_date` to `create_order()` test calls. |
| `patch_tests_fulfillment_2.py` | Second pass of the same test-shape fix. |

## Running them

If you ever need one, run it **from the repository root** so relative paths
(`tests/`, `app/`) resolve correctly:

