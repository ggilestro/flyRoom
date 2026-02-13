# Lessons Learned

## 2026-02-11: SQLite DateTime Comparison Gotcha

### SQLAlchemy + SQLite Datetime Serialization Mismatch
- **Issue**: SQLAlchemy sends datetime bound parameters with microseconds (`'2026-02-11 11:43:44.000000'`) but SQLite `CURRENT_TIMESTAMP` stores without them (`'2026-02-11 11:43:44'`). Since SQLite uses string comparison, `'2026-02-11 11:43:44' < '2026-02-11 11:43:44.000000'` evaluates to True (`.` > ` ` in ASCII).
- **Impact**: Queries like `Stock.modified_at < current_stock.modified_at` can match the same row, and `Stock.modified_at == current_stock.modified_at` can miss it.
- **Fix**: When querying for rows adjacent to a current row, always explicitly exclude the current row with `Stock.id != current_id`.
- **Note**: This is SQLite-specific; MariaDB/MySQL/PostgreSQL use actual datetime types, not string comparison.

### Service Method Refactoring for Reuse
- **Pattern**: Extract filter/sort logic from `list_stocks()` into `_build_filtered_query()` and `_get_sort_column()` helper methods
- **Benefit**: Enables consistent filter/sort behavior across `list_stocks()` and `get_adjacent_stocks()` without code duplication

## 2026-02-02: BDSC Plugin Implementation

### Circular Import Prevention
- **Issue**: Importing `app.dependencies` at module level caused circular imports due to the dependency chain: `router.py` -> `dependencies.py` -> `auth/utils.py` -> `auth/router.py` -> `dependencies.py`
- **Solution**: Use late imports inside functions (like `_get_db()` and `_get_current_user()`) instead of importing at module level
- **Pattern**: For routers that need database and auth dependencies, define local dependency functions with late imports

### FlyBase Data Integration
- **Finding**: BDSC doesn't have a public API, but FlyBase provides bulk TSV files containing all stock center data
- **Data source**: `https://s3ftp.flybase.org/releases/current/precomputed_files/stocks/stocks_FB*.tsv.gz`
- **Key fields**: `FBst` (FlyBase ID), `stock_number`, `collection_short_name` (to filter BDSC), `FB_genotype`, `description`
- **Approach**: Download once, cache locally, filter to BDSC stocks, build in-memory index for fast search

### Testing Plugin Code
- **Pattern**: For async plugin code, pre-populate the data index in fixtures to avoid network calls
- **Pattern**: Use `MagicMock` and `AsyncMock` for testing router endpoints that depend on plugins
- **Pattern**: Test endpoint validation separately from business logic

## 2026-02-04: FlyBase Multi-Repository Support

### Plugin Refactoring Strategy
- **Approach**: When expanding a single-source plugin to multi-source, keep backward compatibility aliases
- **Pattern**: `BDSCPlugin = FlyBasePlugin` and `get_bdsc_plugin = get_flybase_plugin` allow existing code to work unchanged
- **Pattern**: Use source aliases in router (e.g., 'bdsc' -> 'flybase' with repository='bdsc') for backward compat

### Multi-Repository Index Structure
- **Design**: Two-level index structure: `{repository: {stock_number: data}}`
- **Benefit**: Allows both repository-specific and cross-repository searches efficiently
- **Pattern**: Transform records to include repository info during parsing, not at query time

### FlyBase Collection Mapping
- **Finding**: FlyBase `collection_short_name` maps to repository IDs:
  - `Bloomington` → `bdsc`
  - `Vienna` → `vdrc`
  - `Kyoto` → `kyoto`
  - `NIG-Fly` → `nig`
  - `KDRC` → `kdrc`
  - `FlyORF` → `flyorf`
  - `NDSSC` → `ndssc`
- **Pattern**: Define mappings as module-level constants for reuse across modules

### API Design for Multi-Repository
- **Pattern**: Use optional `repository` query param rather than separate endpoints per repo
- **Pattern**: Return repository info in stats endpoint to populate UI filters
- **Pattern**: Add `/repositories` endpoint for explicit listing of available repositories

## 2026-02-07: Server-Managed Agent Config + Zero-Config Pairing

### In-Memory Session Store Pattern
- **Pattern**: For short-lived sessions (pairing, imports), use a module-level dict with TTL expiry
- **Implementation**: `_pairing_sessions: dict[str, dict] = {}` with `_cleanup_expired_sessions()` called on create/get
- **Benefit**: No external dependencies (no Redis needed), sufficient for single-instance deploys

### Config Version Sync Pattern
- **Pattern**: Use a `config_version` integer that increments on any config change
- **Flow**: Heartbeat response includes version → agent compares → fetches full config if different
- **Key detail**: Increment version on BOTH agent-level changes (printer_name, poll_interval) AND tenant-level changes (label_format, copies, orientation)
- **Gotcha**: Must increment version on all agents when tenant-level settings change (bulk update query)

### Split Config for Local Agent
- **Pattern**: Core credentials (server_url + api_key) in `config.json`, operational settings cached in `cached_config.json`
- **Benefit**: Server-pushed config changes don't overwrite auth credentials
- **Backward compat**: `load()` handles old all-in-one format by checking if fields exist in main config before overlaying cache

### Pairing Code Generation
- **Pattern**: Exclude visually confusing characters (O/I/L/0/1) from random codes
- **Character set**: `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (26 chars)
- **Length**: 6 chars gives ~300M combinations, more than sufficient for 5-min TTL sessions

### Testing Without DB Connection
- **Issue**: Cannot run `alembic upgrade head` locally when DB is in Docker (host 'db' not resolvable from host machine)
- **Workaround**: Verify migration file loads via `importlib.util.spec_from_file_location()`, run actual migration on deploy
- **Pattern**: Test flyprint agent modules separately since they don't depend on the app's DB

## 2026-02-05: Pre-commit and CI version mismatch

**Problem**: Pre-commit hooks passed locally but CI failed with ruff linting errors.

**Root cause**: Pre-commit used ruff `v0.1.15` while CI installed the latest ruff (which was `0.15.0`). The newer version had additional rules enabled by default.

**Solution**:
1. Keep tool versions synchronized across all config files:
   - `.pre-commit-config.yaml` - defines the pre-commit hook version
   - `.github/workflows/ci.yml` - pins the CI version
   - `pyproject.toml` - defines the dev dependency version
2. Use `pre-commit autoupdate` periodically to keep hooks current
3. When adding ignore rules, add them to `pyproject.toml` so they apply everywhere

**Prevention**: Before pushing, run `pre-commit run --all-files` to catch issues the same way CI does.

## 2026-02-05: Dymo LabelWriter 400 CUPS Integration

**Problem**: Labels printed at wrong size (2x or 4x expected), wrong orientation, or wrong position.

**Root cause**: CUPS PDF filters apply unpredictable scaling. The `-o ppi=300` option is not reliably respected.

**Solution**:
1. **Use PNG images instead of PDF** - goes directly to raster driver, avoids scaling issues
2. **Use 72 DPI** (not 300 DPI) - CUPS interprets images at 72 DPI by default
3. **Match pixel dimensions to CUPS page size** - for `w72h154`, use 72×154 pixels
4. **Account for printer margins** - PPD `ImageableArea` shows non-printable area; add `left_margin_px` offset
5. **Use lpr with `scaling=100` and `fit-to-page=false`**

**Key formula**: For any CUPS page size `wXXhYY`, create a PNG that is XX×YY pixels at 72 DPI.

**What didn't work**:
- PDF output (always scaled incorrectly)
- `-o ppi=300` option (ignored by CUPS)
- High-resolution images (interpreted at 72 DPI, appeared 4x larger)
- ReportLab canvas rotation (coordinate transforms moved content off-page)

**Documentation**: See `/docs/label-printer-integration.md` for full details and reference when adding new printer models.

## 2026-02-08: CUPS Supersampling for Print Quality

**Problem**: 72 DPI images have correct size for CUPS but blurry text. 300 DPI images have sharp text but print over multiple labels (4x too large).

**Root cause**: CUPS image filter treats 1 pixel = 1 point (1/72 inch) with `scaling=100`. No CUPS option reliably scales by DPI metadata.

**What does NOT work** (exhaustively tested):
- `ppi=300` — ignored by CUPS image filter
- `natural-scaling=100` with 300 DPI — still prints over multiple labels
- `fit-to-page` — doesn't respect PageSize on Dymo
- `scaling=24` (72/300*100) — prints minuscule output

**Solution**: Supersample — render at 300 DPI, LANCZOS downsample to 72 DPI before sending to CUPS:
```python
# In create_label_png():
render_dpi = 300  # Always render at 300 DPI for sharp text
output_dpi = 72 if for_print else 300
# ... render everything at render_dpi ...
# Before saving:
if output_dpi < render_dpi:
    out_w = int(img.width * output_dpi / render_dpi)
    out_h = int(img.height * output_dpi / render_dpi)
    img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
img.save(buffer, format="PNG", dpi=(output_dpi, output_dpi))
```

**UPDATE**: Supersampling still produced unreadable barcodes — LANCZOS introduces gray
pixels that confuse barcode readers, and 72 DPI is fundamentally too low resolution.

**Final solution**: Use PDF instead of PNG for CUPS printing:
1. Server generates a portrait PDF (72pt x 153pt) embedding the 300 DPI PNG
2. Agent downloads PDF and prints via `lp` (not `lpr`)
3. CUPS rasterizes the PDF at the printer's native 300 DPI → full quality

**Key**: `create_batch_label_pdf(for_print=True)` generates portrait PDF for print.
`for_print=False` generates landscape PDF for web preview.

**See also**: `PRINTING_NOTES.md` in the flyprint repo for the complete reference.
