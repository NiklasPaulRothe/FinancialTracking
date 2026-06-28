"""Unit tests for ImportService.

Tests CSV parsing, column mapping persistence, duplicate detection,
file validation, and bulk import functionality.

Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9
"""

import pytest
from datetime import date
from decimal import Decimal

from app.services.import_service import (
    ImportService,
    ParsedRow,
    MAX_FILE_SIZE_BYTES,
    MAX_ROW_COUNT,
)


@pytest.fixture
def import_service():
    """Create an ImportService instance."""
    return ImportService()


# ---------------------------------------------------------------------------
# Helper to create CSV content
# ---------------------------------------------------------------------------


def make_csv_bytes(
    rows: list[list[str]],
    delimiter: str = ";",
    encoding: str = "utf-8",
) -> bytes:
    """Create CSV file content as bytes."""
    lines = [delimiter.join(row) for row in rows]
    content = "\n".join(lines)
    return content.encode(encoding)


# ---------------------------------------------------------------------------
# Tests: CSV Parsing (Req 17.6, 17.7, 17.8)
# ---------------------------------------------------------------------------


class TestParseCSV:
    """Tests for CSV parsing with various configurations."""

    def test_parse_semicolon_delimiter_comma_decimal(self, import_service):
        """Parse CSV with semicolon delimiter and comma decimal separator."""
        csv_data = make_csv_bytes([
            ["Datum", "Betrag", "Beschreibung"],
            ["01.01.2024", "-50,00", "Einkauf Supermarkt"],
            ["02.01.2024", "1.500,75", "Gehalt"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.total_rows == 2
        assert result.valid_rows == 2
        assert result.error_rows == 0

    def test_positive_amount_creates_income(self, import_service):
        """Positive amounts should map to income transaction type (Req 17.6)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount", "Desc"],
            ["02.01.2024", "1500,75", "Salary"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        row = result.rows[0]
        assert row.transaction_type == "income"
        assert row.amount == Decimal("1500.75")

    def test_negative_amount_creates_expense_with_abs_value(self, import_service):
        """Negative amounts should map to expense with absolute value (Req 17.6)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount", "Desc"],
            ["01.01.2024", "-50,00", "Purchase"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        row = result.rows[0]
        assert row.transaction_type == "expense"
        assert row.amount == Decimal("50.00")

    def test_parse_comma_delimiter_dot_decimal(self, import_service):
        """Parse CSV with comma delimiter and dot decimal separator (Req 17.7)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount", "Description"],
            ["2024-01-01", "-50.00", "Grocery shopping"],
            ["2024-01-02", "1500.75", "Salary"],
        ], delimiter=",")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%Y-%m-%d",
            delimiter=",",
            decimal_separator=".",
            description_column=2,
        )

        assert result.total_rows == 2
        assert result.valid_rows == 2
        assert result.rows[0].amount == Decimal("50.00")
        assert result.rows[0].transaction_type == "expense"
        assert result.rows[0].description == "Grocery shopping"
        assert result.rows[1].amount == Decimal("1500.75")
        assert result.rows[1].transaction_type == "income"

    def test_parse_iso_8859_1_encoding(self, import_service):
        """Parse CSV with ISO-8859-1 encoding (Req 17.7)."""
        csv_data = make_csv_bytes([
            ["Datum", "Betrag", "Beschreibung"],
            ["01.01.2024", "-25,50", "Bücher kaufen"],
        ], delimiter=";", encoding="iso-8859-1")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            encoding="iso-8859-1",
            description_column=2,
        )

        assert result.total_rows == 1
        assert result.valid_rows == 1
        assert result.rows[0].description == "Bücher kaufen"
        assert result.rows[0].amount == Decimal("25.50")

    def test_parse_with_header_row(self, import_service):
        """First row is treated as header when has_header=True."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "100,00"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            has_header=True,
        )

        assert result.headers == ["Date", "Amount"]
        assert result.total_rows == 1

    def test_parse_without_header_row(self, import_service):
        """All rows are data when has_header=False."""
        csv_data = make_csv_bytes([
            ["01.01.2024", "100,00"],
            ["02.01.2024", "200,00"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            has_header=False,
        )

        assert result.headers == []
        assert result.total_rows == 2

    def test_unparseable_date_flagged_as_error(self, import_service):
        """Rows with unparseable dates are flagged as errors (Req 17.8)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["invalid-date", "100,00"],
            ["01.01.2024", "200,00"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.total_rows == 2
        assert result.error_rows == 1
        assert result.valid_rows == 1
        assert result.rows[0].error is not None
        assert "Unparseable date" in result.rows[0].error
        assert result.rows[1].is_valid is True

    def test_non_numeric_amount_flagged_as_error(self, import_service):
        """Rows with non-numeric amounts are flagged as errors (Req 17.8)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "not-a-number"],
            ["02.01.2024", "50,00"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.error_rows == 1
        assert result.valid_rows == 1
        assert "Non-numeric amount" in result.rows[0].error

    def test_missing_columns_flagged_as_error(self, import_service):
        """Rows with fewer columns than required are errors (Req 17.8)."""
        csv_data = make_csv_bytes([
            ["Date", "Amount", "Desc"],
            ["01.01.2024"],  # Missing amount column
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.error_rows == 1
        assert "columns" in result.rows[0].error.lower()

    def test_thousands_separator_comma_decimal(self, import_service):
        """Thousands separators are stripped properly with comma decimal."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "1.234.567,89"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.rows[0].amount == Decimal("1234567.89")

    def test_thousands_separator_dot_decimal(self, import_service):
        """Thousands separators are stripped properly with dot decimal."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["2024-01-01", "1,234,567.89"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%Y-%m-%d",
            delimiter=";",
            decimal_separator=".",
        )

        assert result.rows[0].amount == Decimal("1234567.89")

    def test_currency_symbols_stripped(self, import_service):
        """Currency symbols in amounts are stripped before parsing."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "€ 50,00"],
            ["02.01.2024", "-25,00 €"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.valid_rows == 2
        assert result.rows[0].amount == Decimal("50.00")
        assert result.rows[1].amount == Decimal("25.00")

    def test_amount_zero_flagged_as_error(self, import_service):
        """Zero amounts are out of valid range."""
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "0,00"],
        ], delimiter=";")

        result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        assert result.error_rows == 1
        assert "out of valid range" in result.rows[0].error


# ---------------------------------------------------------------------------
# Tests: File Validation (Req 17.9)
# ---------------------------------------------------------------------------


class TestFileValidation:
    """Tests for file size and row count validation."""

    def test_file_within_size_limit(self, import_service):
        """Files within 10 MB should pass validation."""
        content = b"x" * (MAX_FILE_SIZE_BYTES - 1)
        assert import_service.validate_file(content) is None

    def test_file_exceeds_size_limit(self, import_service):
        """Files over 10 MB should fail validation (Req 17.9)."""
        content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        error = import_service.validate_file(content)
        assert error is not None
        assert "10 MB" in error

    def test_row_count_within_limit(self, import_service):
        """Row counts within 10,000 should pass validation."""
        content = b"small"
        assert import_service.validate_file(content, row_count=MAX_ROW_COUNT) is None

    def test_row_count_exceeds_limit(self, import_service):
        """Row counts over 10,000 should fail validation (Req 17.9)."""
        content = b"small"
        error = import_service.validate_file(content, row_count=MAX_ROW_COUNT + 1)
        assert error is not None
        assert "10,000" in error

    def test_parse_csv_rejects_oversized_file(self, import_service):
        """parse_csv raises ValueError for oversized files."""
        content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        with pytest.raises(ValueError, match="10 MB"):
            import_service.parse_csv(
                file_content=content,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter=";",
                decimal_separator=",",
            )

    def test_parse_csv_rejects_too_many_rows(self, import_service):
        """parse_csv raises ValueError when row limit is exceeded."""
        # Create a CSV with more than MAX_ROW_COUNT rows
        rows = [["Date", "Amount"]]
        for i in range(MAX_ROW_COUNT + 1):
            rows.append(["01.01.2024", "10,00"])
        csv_data = make_csv_bytes(rows, delimiter=";")

        with pytest.raises(ValueError, match="10,000"):
            import_service.parse_csv(
                file_content=csv_data,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter=";",
                decimal_separator=",",
            )


# ---------------------------------------------------------------------------
# Tests: Parameter Validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    """Tests for unsupported parameter rejection."""

    def test_unsupported_delimiter_rejected(self, import_service):
        """Unsupported delimiters raise ValueError."""
        csv_data = b"a|b\n1|2"
        with pytest.raises(ValueError, match="delimiter"):
            import_service.parse_csv(
                file_content=csv_data,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter="|",
                decimal_separator=".",
            )

    def test_unsupported_decimal_separator_rejected(self, import_service):
        """Unsupported decimal separators raise ValueError."""
        csv_data = b"a;b\n1;2"
        with pytest.raises(ValueError, match="decimal separator"):
            import_service.parse_csv(
                file_content=csv_data,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter=";",
                decimal_separator="/",
            )

    def test_unsupported_encoding_rejected(self, import_service):
        """Unsupported encodings raise ValueError."""
        csv_data = b"a;b\n1;2"
        with pytest.raises(ValueError, match="encoding"):
            import_service.parse_csv(
                file_content=csv_data,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter=";",
                decimal_separator=",",
                encoding="utf-16",
            )

    def test_invalid_encoding_decode_error(self, import_service):
        """Files that can't be decoded with specified encoding raise ValueError."""
        # Create bytes that are invalid UTF-8
        csv_data = b"\xff\xfe" + "Date;Amount\n01.01.2024;100".encode("utf-8")
        with pytest.raises(ValueError, match="decode"):
            import_service.parse_csv(
                file_content=csv_data,
                date_column=0,
                amount_column=1,
                date_format="%d.%m.%Y",
                delimiter=";",
                decimal_separator=",",
                encoding="utf-8",
            )


# ---------------------------------------------------------------------------
# Tests: Duplicate Detection (Req 17.4)
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    """Tests for duplicate detection during preview."""

    def test_preview_marks_duplicates(self, app, db_session, import_service):
        """Preview flags rows matching existing transactions (Req 17.4)."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.transaction import Transaction, TransactionType, TransactionScope

        user = UserFactory()
        account = AccountFactory(owner=user)
        db_session.flush()

        # Create an existing transaction
        existing_txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("50.00"),
            date=date(2024, 1, 1),
            scope=TransactionScope.personal,
            account_id=account.id,
            posted=True,
            user_id=user.id,
        )
        db_session.add(existing_txn)
        db_session.flush()

        # Parse CSV with a matching row
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "-50,00"],  # Matches existing
            ["02.01.2024", "-75,00"],  # No match
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        result = import_service.preview(parse_result, account.id)

        assert result.duplicate_rows == 1
        assert result.rows[0].is_duplicate is True
        assert result.rows[1].is_duplicate is False

    def test_preview_no_duplicates_different_account(self, app, db_session, import_service):
        """Duplicate detection is scoped to the target account."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.transaction import Transaction, TransactionType, TransactionScope

        user = UserFactory()
        account1 = AccountFactory(owner=user, name="Account 1")
        account2 = AccountFactory(owner=user, name="Account 2")
        db_session.flush()

        # Transaction on account1
        existing_txn = Transaction(
            type=TransactionType.expense,
            amount=Decimal("50.00"),
            date=date(2024, 1, 1),
            scope=TransactionScope.personal,
            account_id=account1.id,
            posted=True,
            user_id=user.id,
        )
        db_session.add(existing_txn)
        db_session.flush()

        # Import to account2 — should not detect duplicates
        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "-50,00"],
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        result = import_service.preview(parse_result, account2.id)
        assert result.duplicate_rows == 0
        assert result.rows[0].is_duplicate is False


# ---------------------------------------------------------------------------
# Tests: Column Mapping Persistence (Req 17.1, 17.3)
# ---------------------------------------------------------------------------


class TestColumnMappingPersistence:
    """Tests for saving and retrieving column mappings."""

    def test_save_new_mapping(self, app, db_session, import_service):
        """Save a new column mapping for an account (Req 17.3)."""
        from tests.factories import UserFactory, AccountFactory

        user = UserFactory()
        account = AccountFactory(owner=user)
        db_session.flush()

        mapping = import_service.save_mapping(
            account_id=account.id,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            encoding="utf-8",
            description_column=2,
            bank_name="Sparkasse",
        )

        assert mapping.id is not None
        assert mapping.account_id == account.id
        assert mapping.bank_name == "Sparkasse"
        assert mapping.date_column == 0
        assert mapping.amount_column == 1
        assert mapping.description_column == 2
        assert mapping.delimiter == ";"
        assert mapping.decimal_separator == ","
        assert mapping.encoding == "utf-8"

    def test_retrieve_existing_mapping(self, app, db_session, import_service):
        """Retrieve a saved mapping for an account (Req 17.1)."""
        from tests.factories import UserFactory, AccountFactory

        user = UserFactory()
        account = AccountFactory(owner=user)
        db_session.flush()

        import_service.save_mapping(
            account_id=account.id,
            date_column=0,
            amount_column=3,
            date_format="%Y-%m-%d",
            delimiter=",",
            decimal_separator=".",
            encoding="iso-8859-1",
            bank_name="DKB",
        )

        retrieved = import_service.get_mapping(account.id, bank_name="DKB")
        assert retrieved is not None
        assert retrieved.date_column == 0
        assert retrieved.amount_column == 3
        assert retrieved.date_format == "%Y-%m-%d"
        assert retrieved.delimiter == ","
        assert retrieved.decimal_separator == "."
        assert retrieved.encoding == "iso-8859-1"

    def test_update_existing_mapping(self, app, db_session, import_service):
        """Updating a mapping overwrites existing values (Req 17.3)."""
        from tests.factories import UserFactory, AccountFactory

        user = UserFactory()
        account = AccountFactory(owner=user)
        db_session.flush()

        # Create initial mapping
        import_service.save_mapping(
            account_id=account.id,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            bank_name="ING",
        )

        # Update it
        updated = import_service.save_mapping(
            account_id=account.id,
            date_column=2,
            amount_column=3,
            date_format="%Y-%m-%d",
            delimiter=",",
            decimal_separator=".",
            bank_name="ING",
        )

        assert updated.date_column == 2
        assert updated.amount_column == 3
        assert updated.delimiter == ","

    def test_get_mapping_returns_none_when_not_found(self, app, db_session, import_service):
        """get_mapping returns None when no mapping exists."""
        from tests.factories import UserFactory, AccountFactory

        user = UserFactory()
        account = AccountFactory(owner=user)
        db_session.flush()

        result = import_service.get_mapping(account.id, bank_name="NonExistent")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: Confirm Import (Req 17.5, 17.6)
# ---------------------------------------------------------------------------


class TestConfirmImport:
    """Tests for bulk-inserting transactions from parsed CSV data."""

    def test_confirm_import_creates_transactions(self, app, db_session, import_service):
        """Confirmed import creates transactions and import log (Req 17.5)."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.transaction import Transaction

        user = UserFactory()
        account = AccountFactory(owner=user, balance=Decimal("1000.00"))
        db_session.flush()

        csv_data = make_csv_bytes([
            ["Date", "Amount", "Description"],
            ["01.01.2024", "-50,00", "Supermarket"],
            ["02.01.2024", "1500,00", "Salary"],
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
            description_column=2,
        )

        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account.id,
            user=user,
            filename="bank_export.csv",
        )

        assert result.imported_rows == 2
        assert result.skipped_rows == 0
        assert result.import_log_id is not None

        # Check transactions were created
        transactions = Transaction.query.filter_by(
            account_id=account.id
        ).all()
        assert len(transactions) == 2

        # Check account balance updated
        assert account.balance == Decimal("2450.00")  # 1000 - 50 + 1500

    def test_confirm_import_skips_duplicates_by_default(self, app, db_session, import_service):
        """Duplicates are skipped by default during import (Req 17.5)."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.transaction import Transaction, TransactionType, TransactionScope

        user = UserFactory()
        account = AccountFactory(owner=user, balance=Decimal("500.00"))
        db_session.flush()

        # Create existing transaction
        existing = Transaction(
            type=TransactionType.expense,
            amount=Decimal("50.00"),
            date=date(2024, 1, 1),
            scope=TransactionScope.personal,
            account_id=account.id,
            posted=True,
            user_id=user.id,
        )
        db_session.add(existing)
        db_session.flush()

        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "-50,00"],  # Duplicate
            ["03.01.2024", "-30,00"],  # New
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        # Mark duplicates via preview
        parse_result = import_service.preview(parse_result, account.id)

        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account.id,
            user=user,
            filename="export.csv",
            skip_duplicates=True,
        )

        assert result.imported_rows == 1
        assert result.skipped_rows == 1
        assert account.balance == Decimal("470.00")  # 500 - 30

    def test_confirm_import_override_individual_duplicates(self, app, db_session, import_service):
        """User can override individual duplicate rows (Req 17.5)."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.transaction import Transaction, TransactionType, TransactionScope

        user = UserFactory()
        account = AccountFactory(owner=user, balance=Decimal("500.00"))
        db_session.flush()

        # Create existing transaction
        existing = Transaction(
            type=TransactionType.expense,
            amount=Decimal("50.00"),
            date=date(2024, 1, 1),
            scope=TransactionScope.personal,
            account_id=account.id,
            posted=True,
            user_id=user.id,
        )
        db_session.add(existing)
        db_session.flush()

        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "-50,00"],  # Duplicate — user overrides
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )
        parse_result = import_service.preview(parse_result, account.id)

        # Override the duplicate row
        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account.id,
            user=user,
            filename="export.csv",
            skip_duplicates=True,
            override_rows={1},  # Row 1 overridden
        )

        assert result.imported_rows == 1
        assert result.skipped_rows == 0

    def test_confirm_import_skips_error_rows(self, app, db_session, import_service):
        """Error rows are skipped during import."""
        from tests.factories import UserFactory, AccountFactory

        user = UserFactory()
        account = AccountFactory(owner=user, balance=Decimal("500.00"))
        db_session.flush()

        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["invalid-date", "100,00"],  # Error row
            ["01.01.2024", "200,00"],   # Valid row
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account.id,
            user=user,
            filename="export.csv",
        )

        assert result.imported_rows == 1
        assert result.skipped_rows == 1
        assert account.balance == Decimal("700.00")  # 500 + 200

    def test_confirm_import_creates_import_log(self, app, db_session, import_service):
        """Import log records counts correctly (Req 17.5)."""
        from tests.factories import UserFactory, AccountFactory
        from app.models.csv_import import ImportLog

        user = UserFactory()
        account = AccountFactory(owner=user, balance=Decimal("0.00"))
        db_session.flush()

        csv_data = make_csv_bytes([
            ["Date", "Amount"],
            ["01.01.2024", "100,00"],
            ["02.01.2024", "200,00"],
            ["invalid", "nope"],
        ], delimiter=";")

        parse_result = import_service.parse_csv(
            file_content=csv_data,
            date_column=0,
            amount_column=1,
            date_format="%d.%m.%Y",
            delimiter=";",
            decimal_separator=",",
        )

        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account.id,
            user=user,
            filename="test_import.csv",
        )

        log = db_session.get(ImportLog, result.import_log_id)
        assert log is not None
        assert log.filename == "test_import.csv"
        assert log.total_rows == 3
        assert log.imported_rows == 2
        assert log.skipped_rows == 1
        assert log.account_id == account.id
        assert log.user_id == user.id


# ---------------------------------------------------------------------------
# Tests: ParsedRow data class
# ---------------------------------------------------------------------------


class TestParsedRow:
    """Tests for ParsedRow validation logic."""

    def test_valid_row(self):
        """A row with date and amount and no error is valid."""
        row = ParsedRow(
            row_number=1,
            date=date(2024, 1, 1),
            amount=Decimal("50.00"),
            description="Test",
            transaction_type="expense",
        )
        assert row.is_valid is True

    def test_row_with_error_is_invalid(self):
        """A row with an error is not valid."""
        row = ParsedRow(
            row_number=1,
            date=None,
            amount=None,
            description=None,
            transaction_type=None,
            error="Bad date",
        )
        assert row.is_valid is False

    def test_row_missing_date_is_invalid(self):
        """A row without a parsed date is not valid."""
        row = ParsedRow(
            row_number=1,
            date=None,
            amount=Decimal("50.00"),
            description=None,
            transaction_type="expense",
        )
        assert row.is_valid is False

    def test_row_missing_amount_is_invalid(self):
        """A row without a parsed amount is not valid."""
        row = ParsedRow(
            row_number=1,
            date=date(2024, 1, 1),
            amount=None,
            description=None,
            transaction_type=None,
        )
        assert row.is_valid is False
