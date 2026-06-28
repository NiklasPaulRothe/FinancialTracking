"""Unit tests for ImportColumnMapping and ImportLog models.

Validates: Requirements 17.1, 17.5
"""

import pytest
from decimal import Decimal

from app.models.csv_import import ImportColumnMapping, ImportLog


class TestImportColumnMappingModel:
    """Tests for the ImportColumnMapping model definition."""

    def test_tablename(self):
        assert ImportColumnMapping.__tablename__ == "import_column_mappings"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ImportColumnMapping.__table__
        assert table.c.account_id.nullable is False
        assert table.c.date_column.nullable is False
        assert table.c.amount_column.nullable is False
        assert table.c.date_format.nullable is False
        assert table.c.delimiter.nullable is False
        assert table.c.decimal_separator.nullable is False
        assert table.c.encoding.nullable is False

    def test_nullable_fields(self):
        """Optional fields should be nullable."""
        table = ImportColumnMapping.__table__
        assert table.c.bank_name.nullable is True
        assert table.c.description_column.nullable is True

    def test_default_encoding(self):
        """Encoding should default to 'utf-8'."""
        assert ImportColumnMapping.__table__.c.encoding.default.arg == "utf-8"

    def test_unique_constraint_account_bank(self):
        """UNIQUE(account_id, bank_name) should exist."""
        table = ImportColumnMapping.__table__
        unique_constraints = [
            c for c in table.constraints
            if hasattr(c, "columns") and hasattr(c, "name")
            and c.name == "uq_import_column_mappings_account_bank"
        ]
        assert len(unique_constraints) == 1

    def test_unique_constraint_columns(self):
        """UNIQUE constraint should cover account_id and bank_name."""
        table = ImportColumnMapping.__table__
        for constraint in table.constraints:
            if getattr(constraint, "name", None) == "uq_import_column_mappings_account_bank":
                col_names = [col.name for col in constraint.columns]
                assert "account_id" in col_names
                assert "bank_name" in col_names
                break
        else:
            pytest.fail("UNIQUE constraint not found")

    def test_account_id_foreign_key(self):
        """account_id should reference accounts.id."""
        table = ImportColumnMapping.__table__
        fks = [fk for fk in table.c.account_id.foreign_keys]
        assert len(fks) == 1
        assert fks[0].column.table.name == "accounts"

    def test_repr(self):
        mapping = ImportColumnMapping(account_id=1, bank_name="Sparkasse")
        assert repr(mapping) == "<ImportColumnMapping account_id=1 bank_name='Sparkasse'>"

    def test_repr_no_bank_name(self):
        mapping = ImportColumnMapping(account_id=2, bank_name=None)
        assert repr(mapping) == "<ImportColumnMapping account_id=2 bank_name=None>"

    def test_string_length_bank_name(self):
        """bank_name column should have length 100."""
        col = ImportColumnMapping.__table__.c.bank_name
        assert col.type.length == 100

    def test_string_length_date_format(self):
        """date_format column should have length 20."""
        col = ImportColumnMapping.__table__.c.date_format
        assert col.type.length == 20

    def test_string_length_delimiter(self):
        """delimiter column should have length 1."""
        col = ImportColumnMapping.__table__.c.delimiter
        assert col.type.length == 1

    def test_string_length_decimal_separator(self):
        """decimal_separator column should have length 1."""
        col = ImportColumnMapping.__table__.c.decimal_separator
        assert col.type.length == 1

    def test_string_length_encoding(self):
        """encoding column should have length 20."""
        col = ImportColumnMapping.__table__.c.encoding
        assert col.type.length == 20


class TestImportLogModel:
    """Tests for the ImportLog model definition."""

    def test_tablename(self):
        assert ImportLog.__tablename__ == "import_logs"

    def test_non_nullable_fields(self):
        """Required fields should not be nullable."""
        table = ImportLog.__table__
        assert table.c.account_id.nullable is False
        assert table.c.filename.nullable is False
        assert table.c.total_rows.nullable is False
        assert table.c.imported_rows.nullable is False
        assert table.c.skipped_rows.nullable is False
        assert table.c.user_id.nullable is False
        assert table.c.created_at.nullable is False

    def test_account_id_foreign_key(self):
        """account_id should reference accounts.id."""
        table = ImportLog.__table__
        fks = [fk for fk in table.c.account_id.foreign_keys]
        assert len(fks) == 1
        assert fks[0].column.table.name == "accounts"

    def test_user_id_foreign_key(self):
        """user_id should reference users.id."""
        table = ImportLog.__table__
        fks = [fk for fk in table.c.user_id.foreign_keys]
        assert len(fks) == 1
        assert fks[0].column.table.name == "users"

    def test_string_length_filename(self):
        """filename column should have length 255."""
        col = ImportLog.__table__.c.filename
        assert col.type.length == 255

    def test_repr(self):
        log = ImportLog(filename="export_2024.csv", imported_rows=95, total_rows=100)
        assert repr(log) == "<ImportLog filename='export_2024.csv' imported=95/100>"

    def test_repr_all_imported(self):
        log = ImportLog(filename="bank.csv", imported_rows=50, total_rows=50)
        assert repr(log) == "<ImportLog filename='bank.csv' imported=50/50>"

    def test_created_at_has_default(self):
        """created_at should have a default value."""
        col = ImportLog.__table__.c.created_at
        assert col.default is not None
