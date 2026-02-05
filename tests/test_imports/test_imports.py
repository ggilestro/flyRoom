"""Tests for the enhanced import system."""

import io

import pytest

from app.imports.parsers import (
    AVAILABLE_FIELDS,
    REPOSITORY_ALIASES,
    REQUIRED_FIELDS,
    REQUIRED_FIELDS_ONE_OF,
    apply_field_generators,
    apply_user_mappings,
    build_column_mapping,
    generate_csv_template,
    get_column_info,
    infer_origin,
    normalize_column_name,
    normalize_repository,
    normalize_rows,
    parse_csv_raw,
    parse_tags,
    validate_import_data,
)


class TestNormalizeRepository:
    """Tests for repository name normalization."""

    def test_normalize_bloomington(self):
        """Test Bloomington variations map to bdsc."""
        assert normalize_repository("bloomington") == "bdsc"
        assert normalize_repository("Bloomington") == "bdsc"
        assert normalize_repository("BLOOMINGTON") == "bdsc"
        assert normalize_repository("bdsc") == "bdsc"
        assert normalize_repository("BDSC") == "bdsc"
        assert normalize_repository("bl") == "bdsc"
        assert normalize_repository("indiana") == "bdsc"
        assert normalize_repository("Bloomington Drosophila Stock Center") == "bdsc"

    def test_normalize_vdrc(self):
        """Test Vienna variations map to vdrc."""
        assert normalize_repository("vdrc") == "vdrc"
        assert normalize_repository("VDRC") == "vdrc"
        assert normalize_repository("vienna") == "vdrc"
        assert normalize_repository("Vienna") == "vdrc"
        assert normalize_repository("vienna drosophila") == "vdrc"

    def test_normalize_kyoto(self):
        """Test Kyoto variations map to kyoto."""
        assert normalize_repository("kyoto") == "kyoto"
        assert normalize_repository("Kyoto") == "kyoto"
        assert normalize_repository("dgrc-kyoto") == "kyoto"
        assert normalize_repository("kyoto dgrc") == "kyoto"

    def test_normalize_other_repos(self):
        """Test other repository variations."""
        assert normalize_repository("nig") == "nig"
        assert normalize_repository("NIG-Fly") == "nig"
        assert normalize_repository("dgrc") == "dgrc"
        assert normalize_repository("flyorf") == "flyorf"
        assert normalize_repository("trip") == "trip"
        assert normalize_repository("exelixis") == "exelixis"

    def test_normalize_none_and_empty(self):
        """Test None and empty values."""
        assert normalize_repository(None) is None
        assert normalize_repository("") is None
        assert normalize_repository("  ") is None

    def test_normalize_unknown_returns_lowercase(self):
        """Test unknown repository returns lowercase value."""
        assert normalize_repository("unknown_repo") == "unknown_repo"
        assert normalize_repository("Custom Source") == "custom source"


class TestInferOrigin:
    """Tests for origin inference from row data."""

    def test_explicit_origin_repository(self):
        """Test explicit origin is respected."""
        row = {"origin": "repository", "repository": "bdsc"}
        assert infer_origin(row) == "repository"

    def test_explicit_origin_internal(self):
        """Test explicit internal origin."""
        row = {"origin": "internal"}
        assert infer_origin(row) == "internal"

    def test_explicit_origin_external(self):
        """Test explicit external origin."""
        row = {"origin": "external", "external_source": "Smith Lab"}
        assert infer_origin(row) == "external"

    def test_infer_repository_from_repo_column(self):
        """Test inferring repository origin from repository column."""
        row = {"repository": "bloomington", "repository_stock_id": "3605"}
        assert infer_origin(row) == "repository"

        row = {"repository": "VDRC"}
        assert infer_origin(row) == "repository"

    def test_infer_external_from_source(self):
        """Test inferring external origin from external_source."""
        row = {"external_source": "Smith Lab"}
        assert infer_origin(row) == "external"

    def test_default_internal(self):
        """Test default to internal when no indicators."""
        row = {}
        assert infer_origin(row) == "internal"

        row = {"stock_id": "LAB-001", "genotype": "w1118"}
        assert infer_origin(row) == "internal"

    def test_case_insensitive_origin(self):
        """Test origin values are case-insensitive."""
        assert infer_origin({"origin": "REPOSITORY"}) == "repository"
        assert infer_origin({"origin": "Internal"}) == "internal"
        assert infer_origin({"origin": "EXTERNAL"}) == "external"


class TestColumnMapping:
    """Tests for column name normalization and mapping."""

    def test_normalize_stock_id_columns(self):
        """Test stock_id column variations."""
        assert normalize_column_name("stock_id") == "stock_id"
        assert normalize_column_name("Stock ID") == "stock_id"
        assert normalize_column_name("STOCKID") == "stock_id"
        assert normalize_column_name("stock") == "stock_id"
        assert normalize_column_name("id") == "stock_id"
        assert normalize_column_name("stock#") == "stock_id"

    def test_normalize_genotype_columns(self):
        """Test genotype column variations."""
        assert normalize_column_name("genotype") == "genotype"
        assert normalize_column_name("Genotype") == "genotype"
        assert normalize_column_name("geno") == "genotype"
        assert normalize_column_name("genotypes") == "genotype"

    def test_normalize_repository_columns(self):
        """Test repository column variations."""
        assert normalize_column_name("repository") == "repository"
        assert normalize_column_name("source") == "repository"
        assert normalize_column_name("stock_center") == "repository"
        assert normalize_column_name("from") == "repository"

    def test_normalize_tray_columns(self):
        """Test tray column variations."""
        assert normalize_column_name("tray") == "tray_name"
        assert normalize_column_name("tray_name") == "tray_name"
        assert normalize_column_name("rack") == "tray_name"
        assert normalize_column_name("shelf") == "tray_name"
        assert normalize_column_name("location") == "tray_name"
        assert normalize_column_name("box") == "tray_name"

    def test_normalize_position_columns(self):
        """Test position column variations."""
        assert normalize_column_name("position") == "position"
        assert normalize_column_name("pos") == "position"
        assert normalize_column_name("slot") == "position"
        assert normalize_column_name("well") == "position"

    def test_unknown_column_returns_none(self):
        """Test unknown columns return None."""
        assert normalize_column_name("unknown_col") is None
        assert normalize_column_name("xyz") is None

    def test_build_column_mapping(self):
        """Test building column mapping from column list."""
        columns = ["Stock ID", "Genotype", "Source", "Notes", "Unknown Col"]
        mapping, unmapped = build_column_mapping(columns)

        assert mapping == {
            "Stock ID": "stock_id",
            "Genotype": "genotype",
            "Source": "repository",
            "Notes": "notes",
        }
        assert unmapped == ["Unknown Col"]


class TestNormalizeRows:
    """Tests for row normalization with smart inference."""

    def test_normalize_basic_rows(self):
        """Test basic row normalization."""
        raw_rows = [
            {"Stock ID": "LAB-001", "Genotype": "w1118", "Notes": "Test"},
        ]
        column_map = {"Stock ID": "stock_id", "Genotype": "genotype", "Notes": "notes"}

        result = normalize_rows(raw_rows, column_map)

        assert len(result) == 1
        assert result[0]["stock_id"] == "LAB-001"
        assert result[0]["genotype"] == "w1118"
        assert result[0]["notes"] == "Test"
        assert result[0]["origin"] == "internal"

    def test_normalize_with_repository_detection(self):
        """Test repository detection during normalization."""
        raw_rows = [
            {"Stock ID": "BL-001", "Genotype": "w1118", "Source": "Bloomington", "BDSC#": "3605"},
        ]
        column_map = {
            "Stock ID": "stock_id",
            "Genotype": "genotype",
            "Source": "repository",
            "BDSC#": "repository_stock_id",
        }

        result = normalize_rows(raw_rows, column_map)

        assert result[0]["repository"] == "bdsc"
        assert result[0]["origin"] == "repository"

    def test_normalize_with_external_source(self):
        """Test external source detection."""
        raw_rows = [
            {"Stock ID": "EXT-001", "Genotype": "w1118", "Lab": "Smith Lab"},
        ]
        column_map = {
            "Stock ID": "stock_id",
            "Genotype": "genotype",
            "Lab": "external_source",
        }

        result = normalize_rows(raw_rows, column_map)

        assert result[0]["external_source"] == "Smith Lab"
        assert result[0]["origin"] == "external"


class TestParseCSV:
    """Tests for CSV parsing."""

    def test_parse_csv_raw_basic(self):
        """Test basic CSV parsing."""
        csv_content = b"stock_id,genotype,notes\nLAB-001,w1118,Test stock"
        file = io.BytesIO(csv_content)

        columns, rows = parse_csv_raw(file)

        assert columns == ["stock_id", "genotype", "notes"]
        assert len(rows) == 1
        assert rows[0]["stock_id"] == "LAB-001"
        assert rows[0]["genotype"] == "w1118"

    def test_parse_csv_with_bom(self):
        """Test CSV parsing handles BOM."""
        csv_content = b"\xef\xbb\xbfstock_id,genotype\nLAB-001,w1118"
        file = io.BytesIO(csv_content)

        columns, rows = parse_csv_raw(file)

        assert columns == ["stock_id", "genotype"]
        assert rows[0]["stock_id"] == "LAB-001"

    def test_parse_csv_with_various_columns(self):
        """Test CSV parsing with various column names."""
        csv_content = (
            b"Stock ID,Genotype,Source,BDSC#,Tray,Position\nBL-001,w1118,Bloomington,3605,Rack A,1"
        )
        file = io.BytesIO(csv_content)

        columns, rows = parse_csv_raw(file)

        assert "Stock ID" in columns
        assert "Source" in columns
        assert "Tray" in columns
        assert rows[0]["BDSC#"] == "3605"


class TestValidateImportData:
    """Tests for import data validation."""

    def test_validate_valid_rows(self):
        """Test validation of valid rows."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w1118", "origin": "internal"},
            {"stock_id": "LAB-002", "genotype": "yw", "origin": "internal"},
        ]

        result = validate_import_data(rows, set())

        assert result.valid_count == 2
        assert result.error_count == 0
        assert len(result.valid_rows) == 2

    def test_validate_auto_generates_stock_id(self):
        """Test validation auto-generates stock_id when missing but genotype present."""
        rows = [
            {"genotype": "w1118"},
        ]

        result = validate_import_data(rows, set())

        # Row is valid because genotype is present (satisfies "one of" requirement)
        # and stock_id will be auto-generated
        assert result.valid_count == 1
        assert result.error_count == 0
        # Auto-generated stock_id should follow the pattern IMP-0001
        assert result.valid_rows[0]["stock_id"] == "IMP-0001"

    def test_validate_missing_genotype_and_repo_id(self):
        """Test validation requires either genotype or repository_stock_id."""
        rows = [
            {"stock_id": "LAB-001"},  # Has neither genotype nor repository_stock_id
        ]

        result = validate_import_data(rows, set())

        assert result.valid_count == 0
        assert result.error_count == 1
        assert "must have either a repository stock ID" in result.errors[0]["errors"][0]

    def test_validate_with_repo_id_no_genotype(self):
        """Test validation passes with repository_stock_id but no genotype."""
        rows = [
            {"repository_stock_id": "3605", "repository": "bdsc"},
        ]

        result = validate_import_data(rows, set())

        # Row is valid because repository_stock_id is present
        assert result.valid_count == 1
        assert result.error_count == 0
        # Auto-generated stock_id should use repository info
        assert result.valid_rows[0]["stock_id"] == "BDSC-3605"

    def test_validate_duplicate_in_file(self):
        """Test validation catches duplicates in file."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w1118"},
            {"stock_id": "LAB-001", "genotype": "yw"},  # Duplicate
        ]

        result = validate_import_data(rows, set())

        assert result.valid_count == 1
        assert result.error_count == 1
        assert "Duplicate stock_id in file" in result.errors[0]["errors"][0]

    def test_validate_existing_stock(self):
        """Test validation catches existing stock IDs."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w1118"},
        ]
        existing = {"LAB-001"}

        result = validate_import_data(rows, existing)

        assert result.valid_count == 0
        assert result.error_count == 1
        assert "already exists" in result.errors[0]["errors"][0]


class TestGenerateTemplate:
    """Tests for template generation."""

    def test_generate_basic_template(self):
        """Test basic template generation."""
        template = generate_csv_template("basic")

        assert "stock_id" in template
        assert "genotype" in template
        assert "notes" in template
        assert "tags" in template
        # Should have header + 2 example rows
        lines = template.strip().split("\n")
        assert len(lines) == 3

    def test_generate_repository_template(self):
        """Test repository template generation."""
        template = generate_csv_template("repository")

        assert "stock_id" in template
        assert "repository" in template
        assert "repository_stock_id" in template
        assert "Bloomington" in template
        assert "VDRC" in template
        assert "Kyoto" in template

    def test_generate_full_template(self):
        """Test full template generation."""
        template = generate_csv_template("full")

        assert "stock_id" in template
        assert "origin" in template
        assert "repository" in template
        assert "tray" in template
        assert "position" in template
        assert "external_source" in template


class TestRepositoryAliases:
    """Tests for repository aliases configuration."""

    def test_all_repositories_have_aliases(self):
        """Test all repositories have aliases defined."""
        expected_repos = ["bdsc", "vdrc", "kyoto", "nig", "dgrc", "flyorf", "trip", "exelixis"]
        for repo in expected_repos:
            assert repo in REPOSITORY_ALIASES
            assert len(REPOSITORY_ALIASES[repo]) > 0

    def test_aliases_are_lowercase(self):
        """Test all aliases are lowercase."""
        for repo, aliases in REPOSITORY_ALIASES.items():
            for alias in aliases:
                assert alias == alias.lower(), f"Alias '{alias}' for {repo} not lowercase"

    def test_canonical_name_in_aliases(self):
        """Test canonical name is included in its own aliases."""
        for repo, aliases in REPOSITORY_ALIASES.items():
            assert repo in aliases, f"Canonical name '{repo}' not in its aliases"


# --- Tests for Interactive Column Mapping (V2) ---


class TestAvailableAndRequiredFields:
    """Tests for available and required fields configuration."""

    def test_available_fields_contains_required(self):
        """Test all required fields are in available fields."""
        for field in REQUIRED_FIELDS:
            assert field in AVAILABLE_FIELDS, f"Required field '{field}' not in available fields"

    def test_required_fields_empty(self):
        """Test REQUIRED_FIELDS is empty (stock_id auto-generated, genotype optional)."""
        # No strictly required fields - stock_id is auto-generated
        assert len(REQUIRED_FIELDS) == 0

    def test_required_fields_one_of(self):
        """Test REQUIRED_FIELDS_ONE_OF contains genotype and repository_stock_id."""
        assert "genotype" in REQUIRED_FIELDS_ONE_OF
        assert "repository_stock_id" in REQUIRED_FIELDS_ONE_OF
        assert len(REQUIRED_FIELDS_ONE_OF) == 2

    def test_available_fields_complete(self):
        """Test available fields include all expected fields."""
        expected = [
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
        for field in expected:
            assert field in AVAILABLE_FIELDS, f"Expected field '{field}' not in available fields"


class TestGetColumnInfo:
    """Tests for get_column_info function."""

    def test_get_column_info_basic(self):
        """Test basic column info extraction."""
        columns = ["Stock ID", "Genotype", "Notes"]
        rows = [
            {"Stock ID": "LAB-001", "Genotype": "w1118", "Notes": "Test 1"},
            {"Stock ID": "LAB-002", "Genotype": "yw", "Notes": "Test 2"},
        ]

        result = get_column_info(columns, rows)

        assert len(result) == 3
        assert result[0]["name"] == "Stock ID"
        assert result[0]["sample_values"] == ["LAB-001", "LAB-002"]
        assert result[0]["auto_detected"] == "stock_id"

    def test_get_column_info_auto_detection(self):
        """Test auto-detection of known columns."""
        columns = ["stock_id", "genotype", "unknown_col"]
        rows = [{"stock_id": "1", "genotype": "w", "unknown_col": "x"}]

        result = get_column_info(columns, rows)

        assert result[0]["auto_detected"] == "stock_id"
        assert result[1]["auto_detected"] == "genotype"
        assert result[2]["auto_detected"] is None

    def test_get_column_info_sample_limit(self):
        """Test sample values are limited."""
        columns = ["id"]
        rows = [{"id": str(i)} for i in range(10)]

        result = get_column_info(columns, rows, max_samples=3)

        assert len(result[0]["sample_values"]) == 3
        assert result[0]["sample_values"] == ["0", "1", "2"]

    def test_get_column_info_skips_empty_values(self):
        """Test empty values are skipped in samples."""
        columns = ["col"]
        rows = [
            {"col": ""},
            {"col": None},
            {"col": "value1"},
            {"col": "   "},
            {"col": "value2"},
        ]

        result = get_column_info(columns, rows)

        assert result[0]["sample_values"] == ["value1", "value2"]


class TestApplyFieldGenerators:
    """Tests for apply_field_generators function."""

    def test_apply_simple_generator(self):
        """Test simple field generator."""
        rows = [
            {"Source": "BDSC", "Number": "3605"},
        ]
        generators = [
            {"target_field": "stock_id", "pattern": "{Source}-{Number}"},
        ]

        result = apply_field_generators(rows, generators)

        assert result[0]["stock_id"] == "BDSC-3605"

    def test_apply_multiple_generators(self):
        """Test multiple generators."""
        rows = [
            {"A": "x", "B": "y", "C": "z"},
        ]
        generators = [
            {"target_field": "field1", "pattern": "{A}_{B}"},
            {"target_field": "field2", "pattern": "{B}:{C}"},
        ]

        result = apply_field_generators(rows, generators)

        assert result[0]["field1"] == "x_y"
        assert result[0]["field2"] == "y:z"

    def test_apply_generator_missing_column(self):
        """Test generator with missing column replaces with empty string."""
        rows = [
            {"Source": "BDSC"},
        ]
        generators = [
            {"target_field": "stock_id", "pattern": "{Source}-{MissingCol}"},
        ]

        result = apply_field_generators(rows, generators)

        assert result[0]["stock_id"] == "BDSC-"

    def test_apply_generator_empty_list(self):
        """Test empty generators list returns original rows."""
        rows = [{"col": "value"}]

        result = apply_field_generators(rows, [])

        assert result == rows

    def test_apply_generator_preserves_existing_fields(self):
        """Test generators don't remove existing fields."""
        rows = [
            {"existing": "keep_me", "A": "x"},
        ]
        generators = [
            {"target_field": "new_field", "pattern": "{A}"},
        ]

        result = apply_field_generators(rows, generators)

        assert result[0]["existing"] == "keep_me"
        assert result[0]["new_field"] == "x"

    def test_apply_generator_with_none_value(self):
        """Test generator handles None values."""
        rows = [
            {"A": None, "B": "val"},
        ]
        generators = [
            {"target_field": "result", "pattern": "{A}-{B}"},
        ]

        result = apply_field_generators(rows, generators)

        assert result[0]["result"] == "-val"


class TestApplyUserMappings:
    """Tests for apply_user_mappings function."""

    def test_apply_basic_mappings(self):
        """Test basic user mappings."""
        rows = [
            {"Stock ID": "LAB-001", "Geno": "w1118"},
        ]
        mappings = [
            {"column_name": "Stock ID", "target_field": "stock_id"},
            {"column_name": "Geno", "target_field": "genotype"},
        ]

        result, metadata_keys = apply_user_mappings(rows, mappings)

        assert result[0]["stock_id"] == "LAB-001"
        assert result[0]["genotype"] == "w1118"
        assert len(metadata_keys) == 0

    def test_apply_metadata_mappings(self):
        """Test storing columns as metadata using target_field='custom'."""
        rows = [
            {"Custom Field": "custom_value", "stock_id": "LAB-001", "genotype": "w"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "Custom Field", "target_field": "custom"},
        ]

        result, metadata_keys = apply_user_mappings(rows, mappings)

        assert result[0]["stock_id"] == "LAB-001"
        # Key is auto-generated from column name (lowercased, spaces → underscores)
        assert result[0]["_user_metadata"]["custom_field"] == "custom_value"
        assert "custom_field" in metadata_keys

    def test_apply_mappings_ignores_unmapped(self):
        """Test unmapped columns are ignored."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w", "extra": "ignored"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            # "extra" not mapped
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert "extra" not in result[0]
        assert "_user_metadata" not in result[0]

    def test_apply_mappings_normalizes_repository(self):
        """Test repository values are normalized."""
        rows = [
            {"stock_id": "BL-001", "genotype": "w", "Source": "Bloomington"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "Source", "target_field": "repository"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert result[0]["repository"] == "bdsc"

    def test_apply_mappings_infers_repo_from_bdsc_column(self):
        """Test repository is auto-set when BDSC# column is mapped to repository_stock_id."""
        rows = [
            {"genotype": "w1118", "BDSC#": "3605"},
        ]
        mappings = [
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "BDSC#", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # Repository should be auto-set from column name hint
        assert result[0]["repository"] == "bdsc"
        assert result[0]["repository_stock_id"] == "3605"
        assert result[0]["origin"] == "repository"

    def test_apply_mappings_infers_repo_from_vdrc_column(self):
        """Test repository is auto-set when VDRC# column is mapped to repository_stock_id."""
        rows = [
            {"genotype": "w1118", "VDRC#": "100821"},
        ]
        mappings = [
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "VDRC#", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # Repository should be auto-set from column name hint
        assert result[0]["repository"] == "vdrc"
        assert result[0]["repository_stock_id"] == "100821"

    def test_apply_mappings_explicit_repo_overrides_column_hint(self):
        """Test explicit repository mapping takes precedence over column name hint."""
        rows = [
            {"genotype": "w1118", "BDSC#": "3605", "Source": "vdrc"},
        ]
        mappings = [
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "BDSC#", "target_field": "repository_stock_id"},
            {"column_name": "Source", "target_field": "repository"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # Explicit repository mapping should take precedence
        assert result[0]["repository"] == "vdrc"

    def test_apply_mappings_infers_origin(self):
        """Test origin is inferred when not mapped."""
        rows = [
            {"stock_id": "BL-001", "genotype": "w", "repo": "bdsc"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "repo", "target_field": "repository"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert result[0]["origin"] == "repository"

    def test_apply_mappings_empty_list(self):
        """Test empty mappings returns original rows unchanged."""
        rows = [{"col": "value"}]

        result, metadata_keys = apply_user_mappings(rows, [])

        # Empty mappings returns original rows
        assert result == rows
        assert len(metadata_keys) == 0

    def test_apply_multiple_metadata_columns(self):
        """Test multiple columns stored as metadata using target_field='custom'."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w", "Meta-1": "v1", "Meta 2": "v2"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            {"column_name": "Meta-1", "target_field": "custom"},
            {"column_name": "Meta 2", "target_field": "custom"},
        ]

        result, metadata_keys = apply_user_mappings(rows, mappings)

        # Keys are auto-generated from column names (lowercased, spaces/hyphens → underscores)
        assert result[0]["_user_metadata"]["meta_1"] == "v1"
        assert result[0]["_user_metadata"]["meta_2"] == "v2"
        assert "meta_1" in metadata_keys
        assert "meta_2" in metadata_keys

    def test_apply_custom_key_override(self):
        """Test custom_key overrides auto-generated metadata key."""
        rows = [
            {"stock_id": "LAB-001", "genotype": "w", "Some Column": "value123"},
        ]
        mappings = [
            {"column_name": "stock_id", "target_field": "stock_id"},
            {"column_name": "genotype", "target_field": "genotype"},
            {
                "column_name": "Some Column",
                "target_field": "custom",
                "custom_key": "my_custom_field",
            },
        ]

        result, metadata_keys = apply_user_mappings(rows, mappings)

        # custom_key should be used instead of auto-generated key
        assert result[0]["_user_metadata"]["my_custom_field"] == "value123"
        assert "my_custom_field" in metadata_keys
        # Auto-generated key should NOT exist
        assert "some_column" not in result[0]["_user_metadata"]


class TestParseTags:
    """Tests for parse_tags function."""

    def test_parse_tags_comma_separated(self):
        """Test parsing comma-separated tags."""
        result = parse_tags("GAL4, UAS, driver")
        assert result == ["GAL4", "UAS", "driver"]

    def test_parse_tags_semicolon_separated(self):
        """Test parsing semicolon-separated tags."""
        result = parse_tags("GAL4; screening; nervous system")
        assert result == ["GAL4", "screening", "nervous system"]

    def test_parse_tags_mixed_separators(self):
        """Test parsing tags with both comma and semicolon."""
        result = parse_tags("driver, GAL4; nervous system")
        assert result == ["driver", "GAL4", "nervous system"]

    def test_parse_tags_with_whitespace(self):
        """Test tags with extra whitespace are trimmed."""
        result = parse_tags("  GAL4  ;  UAS  ,  driver  ")
        assert result == ["GAL4", "UAS", "driver"]

    def test_parse_tags_empty_string(self):
        """Test empty string returns empty list."""
        result = parse_tags("")
        assert result == []

    def test_parse_tags_none(self):
        """Test None returns empty list."""
        result = parse_tags(None)
        assert result == []

    def test_parse_tags_single_tag(self):
        """Test single tag without separators."""
        result = parse_tags("GAL4")
        assert result == ["GAL4"]

    def test_parse_tags_skips_empty_entries(self):
        """Test empty entries are skipped."""
        result = parse_tags("GAL4,,UAS;;driver")
        assert result == ["GAL4", "UAS", "driver"]

    def test_parse_tags_project_collection_example(self):
        """Test real-world example from user request."""
        result = parse_tags("GAL4; screening")
        assert result == ["GAL4", "screening"]


class TestCoalesceMapping:
    """Tests for coalesce mapping (multiple columns to same field)."""

    def test_coalesce_single_value(self):
        """Test coalesce with only one non-empty value."""
        rows = [
            {"BDSC": "12345", "VDRC": ""},
            {"BDSC": "", "VDRC": "v98765"},
            {"BDSC": "67890", "VDRC": None},
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert result[0]["repository_stock_id"] == "12345"
        assert result[1]["repository_stock_id"] == "v98765"
        assert result[2]["repository_stock_id"] == "67890"

    def test_coalesce_conflict_detected(self):
        """Test coalesce conflict is detected when both columns have values."""
        rows = [
            {"BDSC": "12345", "VDRC": "v98765"},  # Both have values
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # First value should be used
        assert result[0]["repository_stock_id"] == "12345"
        # Conflict should be tracked
        assert "_coalesce_conflicts" in result[0]
        conflicts = result[0]["_coalesce_conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "repository_stock_id"
        assert "BDSC" in conflicts[0]["columns"]
        assert "VDRC" in conflicts[0]["columns"]

    def test_coalesce_uses_first_nonempty(self):
        """Test that first non-empty value is used in coalesce."""
        rows = [
            {"ColA": "", "ColB": "valueB", "ColC": "valueC"},
        ]
        mappings = [
            {"column_name": "ColA", "target_field": "notes"},
            {"column_name": "ColB", "target_field": "notes"},
            {"column_name": "ColC", "target_field": "notes"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # ColB is the first non-empty, so it should be used
        assert result[0]["notes"] == "valueB"

    def test_coalesce_tracks_source_column(self):
        """Test that the source column is tracked for coalesce."""
        rows = [
            {"BDSC": "12345", "VDRC": ""},
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert "_coalesce_sources" in result[0]
        assert result[0]["_coalesce_sources"]["repository_stock_id"] == "BDSC"

    def test_coalesce_repository_hint_from_source_column(self):
        """Test that repository is inferred from the column that provided the value."""
        rows = [
            {"BDSC": "", "VDRC#": "v12345"},
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC#", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        # VDRC# provided the value, so repository should be vdrc
        assert result[0]["repository"] == "vdrc"


class TestConflictDetection:
    """Tests for conflict detection system."""

    def test_coalesce_conflict_type(self):
        """Test coalesce conflict is created with correct type."""
        rows = [
            {"BDSC": "12345", "VDRC": "v98765"},
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)
        conflicts = result[0].get("_coalesce_conflicts", [])

        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "repository_stock_id"
        assert conflicts[0]["columns"]["BDSC"] == "12345"
        assert conflicts[0]["columns"]["VDRC"] == "v98765"

    def test_no_conflict_single_value(self):
        """Test no conflict when only one column has a value."""
        rows = [
            {"BDSC": "12345", "VDRC": ""},
        ]
        mappings = [
            {"column_name": "BDSC", "target_field": "repository_stock_id"},
            {"column_name": "VDRC", "target_field": "repository_stock_id"},
        ]

        result, _ = apply_user_mappings(rows, mappings)

        assert "_coalesce_conflicts" not in result[0] or len(result[0]["_coalesce_conflicts"]) == 0


class TestConflictDetectorModule:
    """Tests for the conflict detector module."""

    @pytest.mark.asyncio
    async def test_rule_based_detector_coalesce(self):
        """Test RuleBasedDetector detects coalesce conflicts."""
        from app.imports.conflict_detectors import (
            DetectionContext,
            RuleBasedDetector,
        )

        detector = RuleBasedDetector()
        context = DetectionContext()

        # Row with coalesce conflict
        row = {
            "repository_stock_id": "12345",
            "_coalesce_conflicts": [
                {
                    "field": "repository_stock_id",
                    "columns": {"BDSC": "12345", "VDRC": "v98765"},
                }
            ],
        }

        conflicts = await detector.detect(row, 1, context)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type.value == "coalesce_conflict"
        assert conflicts[0].field == "repository_stock_id"

    @pytest.mark.asyncio
    async def test_rule_based_detector_duplicate_stock(self):
        """Test RuleBasedDetector detects duplicate stock IDs."""
        from app.imports.conflict_detectors import (
            DetectionContext,
            RuleBasedDetector,
        )

        detector = RuleBasedDetector()
        context = DetectionContext(existing_stock_ids={"EXISTING-001"})

        row = {"stock_id": "EXISTING-001", "genotype": "w1118"}

        conflicts = await detector.detect(row, 1, context)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type.value == "duplicate_stock"

    @pytest.mark.asyncio
    async def test_rule_based_detector_missing_required(self):
        """Test RuleBasedDetector detects missing required fields."""
        from app.imports.conflict_detectors import (
            DetectionContext,
            RuleBasedDetector,
        )

        detector = RuleBasedDetector()
        context = DetectionContext()

        # Row missing both genotype and repository_stock_id
        row = {"stock_id": "TEST-001", "notes": "some notes"}

        conflicts = await detector.detect(row, 1, context)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type.value == "missing_required"

    @pytest.mark.asyncio
    async def test_rule_based_detector_genotype_mismatch(self):
        """Test RuleBasedDetector detects genotype mismatch."""
        from app.imports.conflict_detectors import (
            DetectionContext,
            RuleBasedDetector,
        )

        detector = RuleBasedDetector()
        context = DetectionContext(
            remote_metadata={"12345": {"genotype": "w[1118]; P{da-GAL4.w[-]}3"}}
        )

        row = {
            "repository_stock_id": "12345",
            "genotype": "w[1118]; P{GAL4-da.G32}UH1",  # Different
        }

        conflicts = await detector.detect(row, 1, context)

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type.value == "genotype_mismatch"
        assert conflicts[0].remote_value == "w[1118]; P{da-GAL4.w[-]}3"

    @pytest.mark.asyncio
    async def test_composite_detector(self):
        """Test CompositeDetector combines multiple detectors."""
        from app.imports.conflict_detectors import (
            DetectionContext,
            get_conflict_detector,
        )

        detector = get_conflict_detector()
        context = DetectionContext()

        # Row with multiple issues
        row = {
            "stock_id": "TEST-001",
            "notes": "some notes",
            # Missing genotype and repository_stock_id
        }

        conflicts = await detector.detect(row, 1, context)

        # Should detect missing required
        assert len(conflicts) >= 1
        assert any(c.conflict_type.value == "missing_required" for c in conflicts)
