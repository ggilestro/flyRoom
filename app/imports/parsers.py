"""CSV and Excel parsing utilities for stock import."""

import csv
import io
import re
from typing import BinaryIO

import pandas as pd
from pydantic import BaseModel, Field, ValidationError


class ImportRow(BaseModel):
    """Schema for a single import row.

    Note: Either repository_stock_id OR genotype must be provided.
    stock_id is optional and will be auto-generated if not provided.
    """

    stock_id: str | None = Field(None, max_length=100)
    genotype: str | None = None
    origin: str | None = Field(None, max_length=50)  # repository, internal, external
    repository: str | None = Field(None, max_length=50)  # bdsc, vdrc, etc.
    repository_stock_id: str | None = Field(None, max_length=50)
    external_source: str | None = Field(None, max_length=255)  # Lab/researcher name
    notes: str | None = None
    tags: str | None = None  # Comma or semicolon-separated tag names
    tray_name: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=20)
    visibility: str | None = Field(None, max_length=20)


class ImportResult(BaseModel):
    """Result of import validation."""

    valid_rows: list[dict]
    errors: list[dict]
    total_rows: int
    valid_count: int
    error_count: int


# Repository name aliases for fuzzy matching
# Maps canonical enum value to list of aliases
REPOSITORY_ALIASES: dict[str, list[str]] = {
    "bdsc": [
        "bdsc",
        "bloomington",
        "bl",
        "indiana",
        "bloomington drosophila",
        "bloomington drosophila stock center",
        "bloomington stock center",
        "bdsc#",
        "bl#",
    ],
    "vdrc": [
        "vdrc",
        "vienna",
        "vienna drosophila",
        "vienna drosophila resource center",
        "vienna drc",
    ],
    "kyoto": [
        "kyoto",
        "dgrc-kyoto",
        "kyoto dgrc",
        "kyoto stock center",
        "drosophila genetic resource center kyoto",
    ],
    "nig": [
        "nig",
        "nig-fly",
        "national institute of genetics",
        "nig fly",
    ],
    "dgrc": [
        "dgrc",
        "indiana dgrc",
        "drosophila genomics",
        "drosophila genomics resource center",
    ],
    "flyorf": [
        "flyorf",
        "zurich",
        "orf",
        "fly orf",
        "zurich orf",
        "flyorf zurich",
    ],
    "trip": [
        "trip",
        "harvard rnai",
        "transgenic rnai",
        "transgenic rnai project",
        "trc",
        "trip harvard",
    ],
    "exelixis": [
        "exelixis",
        "harvard exelixis",
        "exelixis collection",
    ],
}


# Expected column mappings (case-insensitive)
COLUMN_MAPPINGS = {
    "stock_id": [
        "stock_id",
        "stockid",
        "stock id",
        "id",
        "stock",
        "stock#",
        "stock #",
        "local_id",
        "local id",
        "lab_id",
        "lab id",
        "internal_id",
    ],
    "genotype": [
        "genotype",
        "geno",
        "genotypes",
        "full genotype",
        "full_genotype",
    ],
    "origin": [
        "origin",
        "type",
        "source_type",
        "stock_type",
    ],
    "repository": [
        "repository",
        "repo",
        "stock_center",
        "source",
        "center",
        "stock center",
        "from",
        "obtained_from",
        "obtained from",
    ],
    "repository_stock_id": [
        "repository_stock_id",
        "repo_id",
        "external_id",
        "bdsc_id",
        "vdrc_id",
        "center_id",
        "stock_center_id",
        "source_id",
        "catalog",
        "catalog_number",
        "catalog#",
        "bdsc#",
        "vdrc#",
        "bl#",
        "stock number",
        "bdsc",
        "vdrc",
        "bl",  # Column named just "BDSC" or "VDRC"
    ],
    "external_source": [
        "external_source",
        "lab",
        "researcher",
        "from_lab",
        "lab_name",
        "received_from",
        "donor",
        "donor_lab",
    ],
    "notes": [
        "notes",
        "note",
        "comments",
        "comment",
        "description",
        "remarks",
    ],
    "tags": [
        "tags",
        "tag",
        "labels",
        "categories",
        "keywords",
    ],
    "tray_name": [
        "tray",
        "tray_name",
        "rack",
        "shelf",
        "location",
        "box",
        "container",
        "storage",
        "freezer",
    ],
    "position": [
        "position",
        "pos",
        "slot",
        "well",
        "spot",
        "tray_position",
        "tray_pos",
    ],
    "visibility": [
        "visibility",
        "visible",
        "sharing",
        "share",
        "access",
    ],
}


def normalize_column_name(col: str) -> str | None:
    """Normalize a column name to standard field name.

    Args:
        col: Column name from file.

    Returns:
        str | None: Normalized field name or None if not recognized.
    """
    col_lower = col.lower().strip()
    for field, aliases in COLUMN_MAPPINGS.items():
        if col_lower in aliases:
            return field
    return None


def normalize_repository(value: str | None) -> str | None:
    """Normalize a repository name to its canonical enum value.

    Uses fuzzy matching against REPOSITORY_ALIASES to handle common
    variations like "Bloomington" -> "bdsc".

    Args:
        value: Raw repository value from import.

    Returns:
        str | None: Canonical repository enum value or None.
    """
    if not value:
        return None

    value_lower = value.lower().strip()
    if not value_lower:
        return None

    # Remove common suffixes/prefixes for matching
    cleaned = value_lower.replace("#", "").replace("stock center", "").strip()

    for canonical, aliases in REPOSITORY_ALIASES.items():
        if value_lower in aliases or cleaned in aliases:
            return canonical

    # Check for partial match at start
    for canonical, aliases in REPOSITORY_ALIASES.items():
        for alias in aliases:
            if value_lower.startswith(alias) or alias.startswith(value_lower):
                return canonical

    # If no match found, return lowercase value (might be "other")
    return value_lower if value_lower else None


def infer_origin(row: dict) -> str:
    """Infer the origin type from row data.

    Logic:
    1. If origin is explicitly set and valid, use it.
    2. If repository column has a known repo name -> repository.
    3. If external_source or from_lab has value -> external.
    4. Otherwise -> internal.

    Args:
        row: Row data dictionary.

    Returns:
        str: Inferred origin (repository, internal, or external).
    """
    # Check if origin is explicitly provided and valid
    explicit_origin = row.get("origin", "").lower().strip() if row.get("origin") else ""
    if explicit_origin in ("repository", "internal", "external"):
        return explicit_origin

    # Check for repository indicator
    repo_value = row.get("repository")
    if repo_value:
        normalized = normalize_repository(repo_value)
        if normalized and normalized in REPOSITORY_ALIASES:
            return "repository"

    # Check for repository_stock_id without explicit repository
    # (e.g., user put BDSC stock number but no source column)
    repo_stock_id = row.get("repository_stock_id")
    if repo_stock_id:
        # If there's a repository stock ID, this is a repository stock
        # even if we don't know which repository
        return "repository"

    # Check for external source indicator
    external_source = row.get("external_source")
    if external_source:
        return "external"

    # Default to internal
    return "internal"


def detect_repository_from_columns(columns: list[str]) -> dict[str, str]:
    """Detect if any column names suggest a specific repository.

    For example, "BDSC#" column suggests BDSC repository.

    Args:
        columns: List of column names.

    Returns:
        dict: Mapping of detected hints.
    """
    hints = {}
    for col in columns:
        col_lower = col.lower().strip()
        if "bdsc" in col_lower or col_lower.startswith("bl"):
            hints["repository_hint"] = "bdsc"
        elif "vdrc" in col_lower:
            hints["repository_hint"] = "vdrc"
        elif "kyoto" in col_lower:
            hints["repository_hint"] = "kyoto"
    return hints


def parse_csv_raw(file: BinaryIO) -> tuple[list[str], list[dict]]:
    """Parse CSV file into column names and raw row dictionaries.

    Args:
        file: File-like object containing CSV data.

    Returns:
        tuple: (list of column names, list of raw row dicts).
    """
    content = file.read().decode("utf-8-sig")  # Handle BOM
    reader = csv.DictReader(io.StringIO(content))
    columns = reader.fieldnames or []
    rows = [dict(row) for row in reader]
    return list(columns), rows


def parse_excel_raw(file: BinaryIO) -> tuple[list[str], list[dict]]:
    """Parse Excel file into column names and raw row dictionaries.

    Args:
        file: File-like object containing Excel data.

    Returns:
        tuple: (list of column names, list of raw row dicts).
    """
    df = pd.read_excel(file, engine="openpyxl")
    columns = [str(c) for c in df.columns]

    # Convert to list of dicts, handling NaN values
    rows = []
    for _, row in df.iterrows():
        row_dict = {}
        for col in columns:
            value = row[col]
            if pd.isna(value):
                row_dict[col] = None
            else:
                row_dict[col] = str(value).strip()
        rows.append(row_dict)

    return columns, rows


def normalize_rows(rows: list[dict], column_map: dict[str, str]) -> list[dict]:
    """Normalize row dictionaries using column mapping.

    Also applies repository normalization and origin inference.

    Args:
        rows: Raw row dictionaries.
        column_map: Map of original column name to normalized field name.

    Returns:
        list[dict]: Normalized row dictionaries.
    """
    normalized = []

    for raw_row in rows:
        norm_row = {}

        # Map columns
        for orig_col, value in raw_row.items():
            mapped = column_map.get(orig_col)
            if mapped:
                norm_row[mapped] = value.strip() if value else None

        # Normalize repository name
        if norm_row.get("repository"):
            norm_row["repository"] = normalize_repository(norm_row["repository"])

        # Infer origin if not set or invalid
        norm_row["origin"] = infer_origin(norm_row)

        normalized.append(norm_row)

    return normalized


def build_column_mapping(columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """Build column mapping from raw column names.

    Args:
        columns: Original column names from file.

    Returns:
        tuple: (mapping dict, unmapped columns list).
    """
    mapping = {}
    unmapped = []

    for col in columns:
        normalized = normalize_column_name(col)
        if normalized:
            mapping[col] = normalized
        else:
            unmapped.append(col)

    return mapping, unmapped


def parse_csv(file: BinaryIO) -> list[dict]:
    """Parse CSV file into list of normalized dictionaries.

    Args:
        file: File-like object containing CSV data.

    Returns:
        list[dict]: List of row dictionaries.
    """
    columns, raw_rows = parse_csv_raw(file)
    column_map, _ = build_column_mapping(columns)
    return normalize_rows(raw_rows, column_map)


def parse_excel(file: BinaryIO) -> list[dict]:
    """Parse Excel file into list of normalized dictionaries.

    Args:
        file: File-like object containing Excel data.

    Returns:
        list[dict]: List of row dictionaries.
    """
    columns, raw_rows = parse_excel_raw(file)
    column_map, _ = build_column_mapping(columns)
    return normalize_rows(raw_rows, column_map)


def validate_import_data(
    rows: list[dict],
    existing_stock_ids: set[str],
    auto_generate_stock_id: bool = True,
    stock_id_prefix: str = "IMP",
) -> ImportResult:
    """Validate import data and return results.

    Validation rules:
    - Each row must have either repository_stock_id OR genotype (or both)
    - stock_id is optional and will be auto-generated if not provided
    - stock_id must be unique within file and not already exist in tenant

    Args:
        rows: List of row dictionaries.
        existing_stock_ids: Set of existing stock IDs in the tenant.
        auto_generate_stock_id: Whether to auto-generate missing stock_ids.
        stock_id_prefix: Prefix for auto-generated stock IDs.

    Returns:
        ImportResult: Validation results.
    """
    valid_rows = []
    errors = []
    seen_stock_ids = set()

    for i, row in enumerate(rows, start=1):
        row_errors = []

        # Validate required fields (must have repo_id OR genotype)
        field_errors = validate_required_fields(row)
        row_errors.extend(field_errors)

        # Handle stock_id - auto-generate if missing
        stock_id = row.get("stock_id")
        if not stock_id and auto_generate_stock_id and not row_errors:
            stock_id = generate_stock_id(row, i, stock_id_prefix)
            row["stock_id"] = stock_id

        # Check for duplicate/existing stock_id
        if stock_id:
            if stock_id in seen_stock_ids:
                row_errors.append(f"Duplicate stock_id in file: {stock_id}")
            elif stock_id in existing_stock_ids:
                row_errors.append(f"Stock ID already exists: {stock_id}")
            else:
                seen_stock_ids.add(stock_id)

        # Validate using Pydantic (field length limits, etc.)
        if not row_errors:
            try:
                ImportRow(**row)
            except ValidationError as e:
                for error in e.errors():
                    row_errors.append(f"{error['loc'][0]}: {error['msg']}")

        if row_errors:
            errors.append(
                {
                    "row": i,
                    "data": row,
                    "errors": row_errors,
                }
            )
        else:
            valid_rows.append(row)

    return ImportResult(
        valid_rows=valid_rows,
        errors=errors,
        total_rows=len(rows),
        valid_count=len(valid_rows),
        error_count=len(errors),
    )


def generate_csv_template(template_type: str = "basic") -> str:
    """Generate a CSV template for import.

    Args:
        template_type: Type of template (basic, repository, full).

    Returns:
        str: CSV template content.
    """
    if template_type == "basic":
        headers = ["stock_id", "genotype", "notes", "tags"]
        example_rows = [
            [
                "LAB-001",
                "w[1118]; P{GAL4-elav.L}3",
                "Elav-GAL4 driver line",
                "driver,nervous system",
            ],
            ["LAB-002", "y[1] w[*]; P{UAS-GFP}", "GFP reporter", "reporter,UAS"],
        ]
    elif template_type == "repository":
        headers = ["stock_id", "genotype", "repository", "repository_stock_id", "notes", "tags"]
        example_rows = [
            [
                "BL-3605",
                "w[1118]; P{GAL4-elav.L}3",
                "Bloomington",
                "3605",
                "Elav-GAL4 driver",
                "driver",
            ],
            ["VDRC-100821", "w[1118]; P{KK}", "VDRC", "100821", "RNAi line", "rnai"],
            ["KY-109706", "w[*]; P{GawB}NP", "Kyoto", "109706", "GAL4 trap", "trap"],
        ]
    else:  # full
        headers = [
            "stock_id",
            "genotype",
            "origin",
            "repository",
            "repository_stock_id",
            "external_source",
            "tray",
            "position",
            "notes",
            "tags",
        ]
        example_rows = [
            [
                "BL-3605",
                "w[1118]; P{GAL4-elav.L}3",
                "repository",
                "bdsc",
                "3605",
                "",
                "Rack A",
                "1",
                "Elav-GAL4 driver",
                "driver",
            ],
            [
                "LAB-001",
                "w[1118]; Sp/CyO",
                "internal",
                "",
                "",
                "",
                "Rack A",
                "2",
                "Balancer stock",
                "balancer",
            ],
            [
                "EXT-001",
                "yw; UAS-ChR2",
                "external",
                "",
                "",
                "Smith Lab",
                "Rack B",
                "1",
                "Optogenetic line",
                "optogenetics",
            ],
        ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in example_rows:
        writer.writerow(row)
    return output.getvalue()


# --- Interactive Column Mapping Constants and Functions (V2) ---


# Fields available for mapping
AVAILABLE_FIELDS = [
    "stock_id",
    "genotype",
    "origin",
    "repository",
    "repository_stock_id",
    "external_source",
    "notes",
    "tags",
    "tray_name",
    "position",
    "visibility",
]

# Fields that must be mapped or generated for import to succeed
# At least ONE of these must be present per row
REQUIRED_FIELDS_ONE_OF = ["repository_stock_id", "genotype"]

# For backwards compatibility - empty since stock_id can be auto-generated
REQUIRED_FIELDS: list[str] = []


def validate_required_fields(row: dict) -> list[str]:
    """Validate that a row has the minimum required fields.

    A row must have either:
    - repository_stock_id (external reference number), OR
    - genotype description

    Args:
        row: Row dictionary to validate.

    Returns:
        list[str]: List of error messages (empty if valid).
    """
    errors = []

    has_repo_id = bool(row.get("repository_stock_id"))
    has_genotype = bool(row.get("genotype"))

    if not has_repo_id and not has_genotype:
        errors.append("Row must have either a repository stock ID (e.g., BDSC#) or a genotype")

    return errors


def generate_stock_id(row: dict, index: int, prefix: str = "IMP") -> str:
    """Generate a stock_id for a row if not provided.

    Priority for generating ID:
    1. If repository + repository_stock_id: use "{repo}-{id}" (e.g., "BDSC-3605")
    2. Otherwise: use "{prefix}-{index:04d}" (e.g., "IMP-0001")

    Args:
        row: Row dictionary.
        index: Row index (1-based).
        prefix: Prefix for auto-generated IDs.

    Returns:
        str: Generated stock ID.
    """
    repo = row.get("repository", "").upper()
    repo_id = row.get("repository_stock_id", "")

    if repo and repo_id:
        # Use repository prefix
        return f"{repo}-{repo_id}"
    elif repo_id:
        # Just the repo ID
        return f"EXT-{repo_id}"
    else:
        # Auto-generate with prefix and index
        return f"{prefix}-{index:04d}"


def parse_tags(tags_string: str | None) -> list[str]:
    """Parse a tags string into a list of tag names.

    Supports both comma and semicolon as separators.
    Examples:
        "GAL4, UAS" -> ["GAL4", "UAS"]
        "GAL4; screening" -> ["GAL4", "screening"]
        "driver, GAL4; nervous system" -> ["driver", "GAL4", "nervous system"]

    Args:
        tags_string: String containing tags separated by comma or semicolon.

    Returns:
        list[str]: List of cleaned tag names.
    """
    if not tags_string:
        return []

    # Replace semicolons with commas to normalize, then split
    normalized = tags_string.replace(";", ",")
    return [tag.strip() for tag in normalized.split(",") if tag.strip()]


def get_column_info(columns: list[str], rows: list[dict], max_samples: int = 5) -> list[dict]:
    """Get column info with sample values and auto-detection.

    Args:
        columns: List of column names from file.
        rows: List of raw row dictionaries.
        max_samples: Maximum number of sample values per column.

    Returns:
        list[dict]: List of column info dicts with name, sample_values, auto_detected.
    """
    result = []
    for col in columns:
        # Collect non-empty sample values
        samples = []
        for row in rows:
            value = row.get(col)
            if value and str(value).strip():
                samples.append(str(value).strip())
            if len(samples) >= max_samples:
                break

        # Check auto-detection
        auto_detected = normalize_column_name(col)

        result.append(
            {
                "name": col,
                "sample_values": samples,
                "auto_detected": auto_detected,
            }
        )

    return result


def apply_field_generators(rows: list[dict], generators: list[dict]) -> list[dict]:
    """Apply field generation patterns to rows.

    Replaces {ColumnName} placeholders with actual column values.

    Args:
        rows: List of row dictionaries.
        generators: List of generator dicts with target_field and pattern.

    Returns:
        list[dict]: Modified rows with generated fields.
    """
    if not generators:
        return rows

    for row in rows:
        for gen in generators:
            target_field = gen.get("target_field")
            pattern = gen.get("pattern", "")

            if not target_field or not pattern:
                continue

            # Find all {ColumnName} placeholders
            value = pattern
            for match in re.finditer(r"\{([^}]+)\}", pattern):
                col_name = match.group(1)
                col_value = row.get(col_name, "")
                if col_value is None:
                    col_value = ""
                value = value.replace(match.group(0), str(col_value))

            row[target_field] = value

    return rows


def apply_user_mappings(rows: list[dict], mappings: list[dict]) -> tuple[list[dict], list[str]]:
    """Apply user-defined column mappings to rows with coalesce support.

    When multiple columns map to the same target field (coalesce mapping),
    the first non-empty value is used. Coalesce conflicts (multiple non-empty
    values) are tracked in _coalesce_conflicts for later conflict resolution.

    Special target_field value "custom" stores the column value in metadata
    using the column name (lowercased, spaces replaced with underscores) as key.

    Args:
        rows: List of raw row dictionaries.
        mappings: List of user mapping dicts with column_name, target_field.

    Returns:
        tuple: (normalized_rows, metadata_keys_used).
    """
    if not mappings:
        return rows, []

    # Build lookup: column_name -> mapping
    mapping_lookup = {m["column_name"]: m for m in mappings}
    metadata_keys_used = []

    # Build reverse lookup: target_field -> list of column names (for coalesce)
    # Exclude "custom" from coalesce tracking since each custom maps independently
    field_to_columns: dict[str, list[str]] = {}
    for mapping in mappings:
        target = mapping.get("target_field")
        if target and target != "custom":
            if target not in field_to_columns:
                field_to_columns[target] = []
            field_to_columns[target].append(mapping["column_name"])

    # Detect repository hints from columns mapped to repository_stock_id
    # e.g., "BDSC#" -> bdsc, "VDRC#" -> vdrc
    repo_hints: dict[str, str] = {}  # column_name -> repository
    for mapping in mappings:
        if mapping.get("target_field") == "repository_stock_id":
            col_lower = mapping["column_name"].lower()
            if "bdsc" in col_lower or col_lower.startswith("bl"):
                repo_hints[mapping["column_name"]] = "bdsc"
            elif "vdrc" in col_lower:
                repo_hints[mapping["column_name"]] = "vdrc"
            elif "kyoto" in col_lower:
                repo_hints[mapping["column_name"]] = "kyoto"
            elif "nig" in col_lower:
                repo_hints[mapping["column_name"]] = "nig"

    normalized = []
    for raw_row in rows:
        norm_row: dict = {}
        metadata: dict = {}
        coalesce_conflicts: list[dict] = []  # Track conflicts for this row
        coalesce_sources: dict[str, str] = {}  # field -> column that provided value

        # Process columns in mapping order for deterministic coalesce
        for col_name, value in raw_row.items():
            if value is None:
                continue
            value_str = str(value).strip() if value else ""
            if not value_str:
                continue

            mapping = mapping_lookup.get(col_name)
            if not mapping:
                # No explicit mapping - skip column
                continue

            target_field = mapping.get("target_field")

            if target_field == "custom":
                # Store in metadata using custom_key if provided, else auto-generate from column name
                metadata_key = mapping.get("custom_key") or col_name.lower().replace(
                    " ", "_"
                ).replace("-", "_")
                metadata[metadata_key] = value_str
                if metadata_key not in metadata_keys_used:
                    metadata_keys_used.append(metadata_key)
            elif target_field:
                # Coalesce logic: use first non-empty value
                if target_field in norm_row:
                    # Field already has a value - this is a coalesce conflict!
                    existing_col = coalesce_sources.get(target_field, "unknown")
                    coalesce_conflicts.append(
                        {
                            "field": target_field,
                            "columns": {
                                existing_col: norm_row[target_field],
                                col_name: value_str,
                            },
                        }
                    )
                else:
                    # First non-empty value - use it
                    norm_row[target_field] = value_str
                    coalesce_sources[target_field] = col_name

        # Add metadata if any
        if metadata:
            norm_row["_user_metadata"] = metadata

        # Track coalesce conflicts for conflict resolution phase
        if coalesce_conflicts:
            norm_row["_coalesce_conflicts"] = coalesce_conflicts

        # Track which column provided each value (for repository hint)
        norm_row["_coalesce_sources"] = coalesce_sources

        # Auto-set repository from column name hint if not explicitly set
        # Use the column that actually provided the repository_stock_id value
        if not norm_row.get("repository") and norm_row.get("repository_stock_id"):
            source_col = coalesce_sources.get("repository_stock_id")
            if source_col and source_col in repo_hints:
                norm_row["repository"] = repo_hints[source_col]

        # Normalize repository name
        if norm_row.get("repository"):
            norm_row["repository"] = normalize_repository(norm_row["repository"])

        # Infer origin if not set
        if "origin" not in norm_row:
            norm_row["origin"] = infer_origin(norm_row)

        normalized.append(norm_row)

    return normalized, metadata_keys_used
