# Improve Tray Handling in CSV Import

## Current Task
The `location` column was mistakenly mapped to `tray_name`, causing unwanted tray auto-creation. Implemented clearer tray handling with explicit user confirmation.

**Date Started:** 2026-02-05
**Date Completed:** 2026-02-05
**Status:** Complete

## Problem Statement
1. Location column auto-detection was causing unwanted tray creation
2. Import workflow needed clearer tray handling with explicit user confirmation
3. Tray auto-creation should be conditional on explicit tray column mapping

## Implementation Summary

### Schema Changes (`app/imports/schemas.py`)
- Added `tray_column_mapped: bool` to `ImportPreviewV2`
- Added `stats: Optional[ImportStats]` to `ImportPreviewV2`
- Added `TrayResolution` schema for user's resolution of tray name conflicts
- Added `tray_resolutions: list[TrayResolution]` to `ImportExecuteV2Request`

### Backend Changes (`app/imports/router.py`)
- Added `/validate-mappings` endpoint to validate user mappings and return tray statistics
- Updated `_get_or_create_tray()` to accept `tray_resolutions` and `tray_column_mapped` params
- Added `_create_new_tray()` helper function
- Updated `execute_v2_phase1` and `execute_v2_phase2` to:
  - Only process trays when tray_name column is explicitly mapped
  - Apply tray resolutions (use_existing, create_new, skip)

### Frontend Changes (`app/templates/stocks/import.html`)
- Added conditional Step 3: Tray Configuration between Map and Preview
- Dynamic step numbering (Upload → Map → [Trays] → Preview → [Resolve])
- Tray Configuration step shows:
  - Existing tray conflicts with resolution options (use existing, create new, skip)
  - New trays to create with auto-create toggle
  - Default tray type and max positions configuration
- New state variables: `showTrayStep`, `mappingStats`, `trayResolutions`, `trayNewNames`
- New functions: `validateAndContinue()`, `handleTrayResolutionChange()`, step helpers

## Test Results
- All 84 import tests pass
- Verified schema changes compile correctly

---

# Two-Phase Import with Conflict Resolution

## Current Task
Implementing coalesce column mapping and two-phase import with conflict resolution UI.

**Date Started:** 2026-02-03
**Date Completed:** 2026-02-03
**Status:** Complete

## Problem Statement
1. **Multiple source columns for same field**: User has BDSC and VDRC columns - each row has a value in one OR the other, but both should map to `repository_stock_id`
2. **Current limitation**: The "already used" restriction prevents mapping multiple columns to the same target field
3. **Need for conflict resolution**: When both columns have values, or when genotype mismatches occur with remote data, user intervention is required

## Solution Overview

### Two-Phase Import Architecture
```
Phase 1: Clean Import
├── Process all rows
├── Detect conflicts in each row
├── Import rows with NO conflicts immediately
└── Return list of conflicting rows with details

Phase 2: Conflict Resolution
├── Display conflicting rows in review UI
├── User resolves each conflict (choose value, skip, edit)
├── Submit resolved rows for import
└── Return final import results
```

## Implementation Checklist

### Phase 1: Coalesce Mapping Support ✅
- [x] Remove "already used" restriction from UI dropdown (allow same field multiple times)
- [x] Update `isFieldUsed()` function to allow duplicate mappings
- [x] Add visual indicator when multiple columns map to same field (amber background)
- [x] Update `apply_user_mappings()` in `parsers.py` to handle coalesce logic
- [x] Coalesce rule: Use first non-empty value when multiple columns map to same field
- [x] Add unit tests for coalesce mapping behavior

### Phase 2: Conflict Detection System ✅
- [x] Create `ConflictType` enum in `schemas.py`:
  - `COALESCE_CONFLICT` - Multiple columns have values for same target field
  - `GENOTYPE_MISMATCH` - Local genotype differs from repository genotype
  - `DUPLICATE_STOCK` - Stock ID already exists in database
  - `MISSING_REQUIRED` - Required field empty even after coalesce
  - `VALIDATION_ERROR` - Data format/validation issues
  - `LLM_FLAGGED` - (Future) LLM detected potential issue
- [ ] Create `RowConflict` schema with:
  - `row_index: int`
  - `conflict_type: ConflictType`
  - `field: str` (which field has the conflict)
  - `values: dict[str, str]` (column_name → value for conflicting values)
  - `message: str` (human-readable description)
  - `original_row: dict` (full row data for context)
  - `confidence: Optional[float]` - (Future) For LLM-based detection confidence score
  - `suggestion: Optional[str]` - (Future) LLM-suggested resolution
  - `detector: str` - Which detector found this ("rule", "llm", etc.)
- [ ] Create `ConflictingRow` schema grouping all conflicts for a single row
- [ ] **Design extensible conflict detection architecture** (see below)
- [ ] Implement `detect_conflicts()` function in `parsers.py`
- [ ] Add conflict detection for coalesce scenarios
- [ ] Add conflict detection for genotype mismatch (when fetching BDSC/VDRC data)
- [ ] Add unit tests for conflict detection

#### Extensible Conflict Detection Architecture
Design the conflict detection system to allow future LLM integration:

```python
# app/imports/conflict_detectors.py

from abc import ABC, abstractmethod
from typing import Protocol

class ConflictDetector(Protocol):
    """Protocol for conflict detection strategies."""

    async def detect(
        self,
        row: dict,
        row_index: int,
        context: "DetectionContext"
    ) -> list[RowConflict]:
        """Detect conflicts in a single row."""
        ...

class DetectionContext:
    """Context passed to all detectors."""
    existing_stock_ids: set[str]
    column_mappings: list[UserColumnMapping]
    remote_metadata: dict[str, dict]  # repo_stock_id → metadata
    all_rows: list[dict]  # For cross-row analysis

class RuleBasedDetector:
    """Current rule-based conflict detection."""
    async def detect(self, row, row_index, context) -> list[RowConflict]:
        conflicts = []
        conflicts.extend(self._check_coalesce_conflicts(row, context))
        conflicts.extend(self._check_genotype_mismatch(row, context))
        conflicts.extend(self._check_duplicates(row, context))
        return conflicts

class LLMDetector:
    """Future: LLM-powered conflict detection."""
    async def detect(self, row, row_index, context) -> list[RowConflict]:
        # Future implementation:
        # - Fuzzy genotype matching
        # - Semantic duplicate detection
        # - Data quality assessment
        # - Suggested resolutions with confidence scores
        return []  # Placeholder

class CompositeDetector:
    """Combines multiple detectors."""
    def __init__(self, detectors: list[ConflictDetector]):
        self.detectors = detectors

    async def detect(self, row, row_index, context) -> list[RowConflict]:
        all_conflicts = []
        for detector in self.detectors:
            conflicts = await detector.detect(row, row_index, context)
            all_conflicts.extend(conflicts)
        return all_conflicts

# Usage in router.py:
def get_conflict_detector() -> ConflictDetector:
    """Factory function - easy to extend later."""
    detectors = [RuleBasedDetector()]

    # Future: Add LLM detector if enabled
    # if settings.enable_llm_detection:
    #     detectors.append(LLMDetector(client=get_llm_client()))

    return CompositeDetector(detectors)
```

**Future LLM Use Cases:**
1. **Fuzzy genotype matching** - Understand that minor notation differences may be the same stock
2. **Semantic duplicate detection** - Find stocks that are functionally identical
3. **Smart resolution suggestions** - Recommend which value to use with reasoning
4. **Data quality flags** - Identify suspicious or potentially incorrect data
5. **Cross-row analysis** - Detect patterns across the entire import batch

### Phase 3: Two-Phase Import Backend ✅
- [ ] Create `ImportPhase1Result` schema:
  - `imported_count: int`
  - `imported_stock_ids: list[str]`
  - `conflicting_rows: list[ConflictingRow]`
  - `conflict_summary: dict[ConflictType, int]` (count by type)
- [ ] Create `ConflictResolution` schema:
  - `row_index: int`
  - `resolution_type: str` ("use_value", "skip", "manual")
  - `resolved_values: dict[str, str]` (field → chosen value)
- [ ] Create `ImportPhase2Request` schema:
  - `resolutions: list[ConflictResolution]`
  - `session_id: str` (to link with phase 1 data)
- [ ] Add `/api/imports/execute-v2-phase1` endpoint:
  - Process file with user mappings
  - Detect conflicts in each row
  - Import clean rows immediately
  - Store conflicting rows in session/cache for phase 2
  - Return `ImportPhase1Result`
- [ ] Add `/api/imports/execute-v2-phase2` endpoint:
  - Accept user resolutions
  - Apply resolutions to conflicting rows
  - Import resolved rows
  - Return final `ImportExecuteResult`
- [ ] Implement session storage for conflicting rows (Redis or in-memory with TTL)

### Phase 4: Genotype Mismatch Detection ✅
- [ ] During phase 1, when `repository_stock_id` is mapped:
  - Fetch metadata from BDSC/VDRC plugin
  - Compare local `genotype` with remote `genotype`
  - If mismatch, create `GENOTYPE_MISMATCH` conflict
- [ ] Include both local and remote genotype in conflict details
- [ ] Allow user to choose: use local, use remote, or skip

### Phase 5: Conflict Resolution UI ✅
- [ ] Add Step 4: "Resolve Conflicts" after Step 3 in import wizard
- [ ] Only show Step 4 if phase 1 returns conflicting rows
- [ ] Create conflict summary card showing counts by type
- [ ] Create conflict table with:
  - Row number
  - Conflict type badge
  - Conflicting values side-by-side
  - Resolution buttons/dropdown
- [ ] For `COALESCE_CONFLICT`:
  ```
  ┌─────────────────────────────────────────────────────────────┐
  │ Row 15: Multiple values for Repository Stock ID             │
  │                                                             │
  │   BDSC column: 12345                                        │
  │   VDRC column: v98765                                       │
  │                                                             │
  │   [Use "12345"] [Use "v98765"] [Skip Row] [Enter: ____]     │
  └─────────────────────────────────────────────────────────────┘
  ```
- [ ] For `GENOTYPE_MISMATCH`:
  ```
  ┌─────────────────────────────────────────────────────────────┐
  │ Row 23: Genotype mismatch with BDSC #3605                   │
  │                                                             │
  │   Your file:  w[1118]; P{GAL4-da.G32}UH1                    │
  │   BDSC says:  w[1118]; P{da-GAL4.w[-]}3                     │
  │                                                             │
  │   [Use mine] [Use BDSC] [Skip Row]                          │
  └─────────────────────────────────────────────────────────────┘
  ```
- [ ] Add "Resolve All" batch actions:
  - "Skip all conflicts of this type"
  - "Use first value for all coalesce conflicts"
  - "Use remote genotype for all mismatches"
- [ ] Track resolution state in Alpine.js
- [ ] Submit resolutions to phase 2 endpoint
- [ ] Show final results after phase 2 completes

### Phase 6: Testing ✅
- [ ] Test coalesce mapping with single non-empty value
- [ ] Test coalesce conflict detection (both values present)
- [ ] Test genotype mismatch detection
- [ ] Test phase 1 import (clean rows imported, conflicts returned)
- [ ] Test phase 2 import (resolutions applied correctly)
- [ ] Test UI flow end-to-end
- [ ] Test edge cases:
  - All rows clean (no phase 2 needed)
  - All rows conflicting (nothing imported in phase 1)
  - Mixed scenarios

## API Endpoints

### New Endpoints
- `POST /api/imports/execute-v2-phase1` - Import clean rows, return conflicts
- `POST /api/imports/execute-v2-phase2` - Import resolved conflicts

### Modified Endpoints
- `POST /api/imports/preview-v2` - No changes needed
- `POST /api/imports/execute-v2` - Keep for backwards compatibility (single-phase)

## Data Flow

```
1. User uploads file
   ↓
2. preview-v2 → column info + sample data
   ↓
3. User maps columns (including multiple → same field)
   ↓
4. execute-v2-phase1 →
   ├── Clean rows: Import immediately
   └── Conflicting rows: Return for review
   ↓
5. [If conflicts exist] User resolves in UI
   ↓
6. execute-v2-phase2 → Import resolved rows
   ↓
7. Final results displayed
```

## Schema Definitions

```python
class ConflictType(str, Enum):
    COALESCE_CONFLICT = "coalesce_conflict"
    GENOTYPE_MISMATCH = "genotype_mismatch"
    DUPLICATE_STOCK = "duplicate_stock"
    MISSING_REQUIRED = "missing_required"
    VALIDATION_ERROR = "validation_error"
    LLM_FLAGGED = "llm_flagged"  # Future: LLM-detected issues

class RowConflict(BaseModel):
    conflict_type: ConflictType
    field: str
    values: dict[str, str]  # source_column → value
    message: str
    remote_value: Optional[str] = None  # For genotype mismatch
    # Future LLM integration fields:
    detector: str = "rule"  # "rule" | "llm" - which system detected this
    confidence: Optional[float] = None  # LLM confidence score (0-1)
    suggestion: Optional[str] = None  # LLM suggested resolution
    reasoning: Optional[str] = None  # LLM explanation for the conflict

class ConflictingRow(BaseModel):
    row_index: int
    original_row: dict
    conflicts: list[RowConflict]

class ImportPhase1Result(BaseModel):
    imported_count: int
    imported_stock_ids: list[str]
    conflicting_rows: list[ConflictingRow]
    conflict_summary: dict[str, int]
    session_id: str  # For phase 2

class ConflictResolution(BaseModel):
    row_index: int
    action: str  # "use_value", "skip", "manual"
    field_values: dict[str, str]  # field → chosen value

class ImportPhase2Request(BaseModel):
    session_id: str
    resolutions: list[ConflictResolution]
```

## UI State Management

```javascript
// Alpine.js state for conflict resolution
{
    phase1Result: null,
    resolutions: {},  // row_index → { field → chosen_value }

    // Computed
    unresolvedCount() { ... },
    canSubmitPhase2() { return this.unresolvedCount() === 0; },

    // Actions
    resolveConflict(rowIndex, field, value) { ... },
    resolveAllOfType(conflictType, strategy) { ... },
    skipRow(rowIndex) { ... },
    submitPhase2() { ... }
}
```

## Files to Create/Modify

### New Files
- None (all changes in existing files)

### Modified Files
- `app/imports/schemas.py` - Add conflict-related schemas
- `app/imports/parsers.py` - Add `detect_conflicts()`, update `apply_user_mappings()`
- `app/imports/router.py` - Add phase1/phase2 endpoints
- `app/templates/stocks/import.html` - Add conflict resolution UI (Step 4)
- `tests/test_imports/test_imports.py` - Add conflict detection tests

## Session Storage Strategy

For storing conflicting rows between phase 1 and phase 2:

**Option A: In-memory dict with TTL** (Simple, single-instance)
```python
import_sessions: dict[str, dict] = {}  # session_id → {rows, expires_at}
```

**Option B: Redis** (Scalable, multi-instance)
```python
redis.setex(f"import:{session_id}", 3600, json.dumps(data))
```

**Recommendation**: Start with Option A for simplicity. The import session only needs to persist for the duration of the user's import workflow (minutes, not hours).

## Test Results
- TBD

---

---

# Stock Organization, Tagging, Trays, and Visibility System Implementation

## Current Task
Implementing comprehensive stock organization system with organizations, trays, visibility, and stock requests.

**Date Started:** 2026-02-02
**Date Completed:** 2026-02-02
**All Phases Complete:** Yes

## Implementation Checklist

### Phase 1: Organization Hierarchy + Geographic Data ✅
- [x] Create Organization model with name, slug, normalized_name, description, website
- [x] Create OrganizationJoinRequest model for join workflow
- [x] Update Tenant model with organization_id, is_org_admin, city, country, lat, long
- [x] Create migration 004
- [x] Create app/organizations/ module (schemas, service, router)
- [x] Add fuzzy search for duplicate prevention

### Phase 2: Tray System ✅
- [x] Create Tray model with types (numeric, grid, custom)
- [x] Rename Stock.location to Stock.legacy_location
- [x] Add Stock.tray_id, Stock.position, Stock.owner_id
- [x] Create app/trays/ module (schemas, service, router)
- [x] Add position validation for different tray types

### Phase 3: Visibility System ✅
- [x] Create StockVisibility enum (LAB_ONLY, ORGANIZATION, PUBLIC)
- [x] Add Stock.visibility and Stock.hide_from_org fields
- [x] Update StockService with visibility filtering by scope
- [x] Update stock schemas with new fields
- [x] Update stock router with scope parameter

### Phase 4: Stock Request System ✅
- [x] Create StockRequest model with status workflow
- [x] Create StockRequestStatus enum (pending, approved, rejected, fulfilled, cancelled)
- [x] Create app/requests/ module (schemas, service, router)
- [x] Implement request creation, approval, rejection, fulfillment, cancellation
- [x] Add request statistics

### Phase 5: UI and Enhanced Filtering ✅
- [x] Update stock forms with tray/position selector
- [x] Update stock forms with visibility dropdown
- [x] Update stock lists with scope toggle
- [x] Add tray management pages (list.html, detail.html)
- [x] Add exchange/browse public stocks page (browse.html)
- [x] Add stock request management pages (requests.html, admin/requests.html)
- [x] Update sidebar with new sections (Trays, Exchange)

### Phase 6: Testing & Verification ✅
- [x] Write unit tests for Organization service (10 tests)
- [x] Write unit tests for Tray service (12 tests)
- [x] Write unit tests for Stock Request service (12 tests)
- [x] Verify all 112 tests pass

---

# Enhanced Batch Import System

## Current Task
Implementing enhanced batch import with smart detection, preview, and tray support.

**Date Started:** 2026-02-02
**Date Completed:** 2026-02-02
**All Phases Complete:** Yes

## Implementation Checklist

### Phase 1: Smart Repository Detection ✅
- [x] Add REPOSITORY_ALIASES dict for fuzzy matching (Bloomington→bdsc, Vienna→vdrc, etc.)
- [x] Implement normalize_repository() function
- [x] Implement infer_origin() function for smart origin detection
- [x] Add detect_repository_from_columns() for column-based hints

### Phase 2: Tray Support in Import ✅
- [x] Add tray_name and position to COLUMN_MAPPINGS
- [x] Add tray_name and position to ImportRow schema
- [x] Implement auto-create trays during import
- [x] Track created trays in import result

### Phase 3: Preview & Validation UI ✅
- [x] Create ImportPreview, ImportStats, ImportConfig schemas
- [x] Implement /api/imports/preview endpoint
- [x] Compute import statistics (repository counts, trays to create)
- [x] Build validation warnings for unmapped columns
- [x] Rewrite import.html with 3-step wizard UI

### Phase 4: Auto-Fetch Repository Metadata ✅
- [x] Integrate BDSC plugin for metadata fetch
- [x] Add external_metadata population during import
- [x] Track metadata_fetched count in result

### Phase 5: Example Templates ✅
- [x] Generate basic template (stock_id + genotype)
- [x] Generate repository template (+ source, stock center ID)
- [x] Generate full template (+ trays, positions, all fields)
- [x] Add template type parameter to /api/imports/template

### Phase 6: Testing ✅
- [x] Write 37 unit tests for import parsers
- [x] Test repository normalization (Bloomington, VDRC, Kyoto, etc.)
- [x] Test origin inference logic
- [x] Test column mapping variations
- [x] Test CSV parsing with BOM
- [x] Test validation errors

---

# Interactive Column Mapping for Import System

## Current Task
Adding interactive column mapping to the import wizard, allowing users to manually map columns, store extra data as metadata, and generate fields from patterns.

**Date Started:** 2026-02-02
**Date Completed:** 2026-02-02
**All Phases Complete:** Yes

## Implementation Checklist

### Phase 1: Schema Changes ✅
- [x] Add ColumnInfo schema with name, sample_values, auto_detected
- [x] Add UserColumnMapping schema with column_name, target_field, store_as_metadata, metadata_key
- [x] Add FieldGenerator schema with target_field and pattern
- [x] Add ImportPreviewV2 schema with columns, available_fields, required_fields
- [x] Add ImportExecuteV2Request schema with column_mappings, field_generators, config

### Phase 2: Parser Functions ✅
- [x] Add AVAILABLE_FIELDS constant (11 fields)
- [x] Add REQUIRED_FIELDS constant (stock_id, genotype)
- [x] Implement get_column_info() for extracting column info with samples and auto-detection
- [x] Implement apply_field_generators() for pattern-based field generation
- [x] Implement apply_user_mappings() for transforming rows based on user mappings

### Phase 3: API Endpoints ✅
- [x] Add /api/imports/preview-v2 endpoint for interactive column preview
- [x] Add /api/imports/execute-v2 endpoint for import with user mappings
- [x] Support JSON-encoded mappings via form data
- [x] Handle user metadata merging with external metadata

### Phase 4: UI Implementation ✅
- [x] Add progress step indicator (Upload → Map Columns → Preview & Import)
- [x] Implement Step 2: Map Your Columns with column mapping table
- [x] Add dropdown for target field selection with duplicate prevention
- [x] Add "store as metadata" checkbox with key input
- [x] Add field generator section for creating required fields
- [x] Show live preview of generated values
- [x] Update Step 3 with mapping summary and transformed preview

### Phase 5: Testing ✅
- [x] Test AVAILABLE_FIELDS and REQUIRED_FIELDS configuration
- [x] Test get_column_info() with auto-detection and sample limits
- [x] Test apply_field_generators() with patterns and edge cases
- [x] Test apply_user_mappings() with metadata and repository normalization

---

# FlyBase Multi-Repository Support

## Current Task
Renaming BDSC plugin to FlyBase and adding support for all stock centers available in FlyBase data.

**Date Started:** 2026-02-04
**Date Completed:** 2026-02-04
**Status:** Complete

## Available Stock Centers

| Repository | Collection Name | Stock ID Format |
|------------|-----------------|-----------------|
| BDSC | Bloomington | numeric (e.g., 80563) |
| VDRC | Vienna | v-prefix (e.g., v10004) |
| Kyoto | Kyoto | numeric |
| NIG-Fly | NIG-Fly | numeric |
| KDRC | KDRC | numeric |
| FlyORF | FlyORF | varies |
| NDSSC | NDSSC | varies |

## Implementation Checklist

### Phase 1: Refactor Data Loader ✅
- [x] Rename `app/plugins/bdsc/` → `app/plugins/flybase/`
- [x] Update `FlyBaseDataLoader` to load ALL collections (not just Bloomington)
- [x] Create index structure: `{collection: {stock_num: data}}`
- [x] Add `get_repository_stats()` method to return counts per collection
- [x] Map collection names to repository IDs (Bloomington→bdsc, Vienna→vdrc, etc.)

### Phase 2: Update Plugin Class ✅
- [x] Rename `BDSCPlugin` → `FlyBasePlugin`
- [x] Update `source_id = "flybase"`
- [x] Update `name = "FlyBase Stock Database"`
- [x] Add `repository: Optional[str]` parameter to `search()`
- [x] Add `list_repositories()` method
- [x] Update `get_details()` to work across all collections

### Phase 3: Update Router ✅
- [x] Update imports from `bdsc` to `flybase`
- [x] Add `repository` query parameter to search endpoint
- [x] Update `/sources` endpoint to include repository info
- [x] Add `/sources/flybase/repositories` endpoint
- [x] Add backward compatibility: 'bdsc', 'vdrc', etc. map to flybase with repository filter

### Phase 4: Update Import Integration ✅
- [x] Update `app/imports/router.py` references from bdsc to flybase
- [x] Support repository detection from stock ID format
- [x] Updated `_fetch_repository_metadata()` to accept repository hint
- [x] Updated `_find_repository_matches()` to search all repositories

### Phase 5: Update UI ✅
- [x] Update external stock search template (`import_bdsc.html`)
- [x] Add repository filter dropdown (pill buttons)
- [x] Show repository counts in UI
- [x] Color-coded repository badges in search results

### Phase 6: Update Tests ✅
- [x] Created `test_flybase_data_loader.py` (14 tests)
- [x] Created `test_flybase_client.py` (26 tests)
- [x] Updated `test_plugins_router.py` (19 tests)
- [x] All 59 plugin tests pass

### Phase 7: Backward Compatibility ✅
- [x] Keep `bdsc` as alias for `flybase` in router
- [x] Keep `get_bdsc_plugin()` as alias for `get_flybase_plugin()`
- [x] Keep `BDSCPlugin` as alias for `FlyBasePlugin`

## Files Modified

| File | Changes |
|------|---------|
| `app/plugins/bdsc/` | → `app/plugins/flybase/` (renamed) |
| `app/plugins/flybase/__init__.py` | New exports with backward compat |
| `app/plugins/flybase/client.py` | FlyBasePlugin with multi-repo support |
| `app/plugins/flybase/data_loader.py` | Multi-collection loading |
| `app/plugins/__init__.py` | Updated imports |
| `app/plugins/router.py` | Multi-repo search, backward compat |
| `app/plugins/schemas.py` | Added RepositoryInfo schema |
| `app/imports/router.py` | Updated metadata fetching |
| `app/templates/stocks/import_bdsc.html` | Multi-repo UI |
| `tests/test_plugins/test_flybase_*.py` | New test files |

## API Endpoints

### Enhanced Endpoints
```
GET /api/plugins/sources
# Returns repositories array with counts

GET /api/plugins/sources/{source}/stats
# Returns repositories array with counts

GET /api/plugins/sources/{source}/repositories
# New: List available repositories

GET /api/plugins/search?query=...&source=flybase&repository=vdrc
# New: Optional repository filter

GET /api/plugins/details/{source}/{id}?repository=bdsc
# New: Optional repository hint
```

### Backward Compatibility
- `source=bdsc` automatically filters to BDSC repository
- `source=vdrc` automatically filters to VDRC repository
- All existing BDSC-specific URLs continue to work
