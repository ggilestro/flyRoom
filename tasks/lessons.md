# Lessons Learned

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
