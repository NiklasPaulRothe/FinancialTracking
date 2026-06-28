"""CSV Import service for Haushaltsbuch.

Implements CSV file parsing, column mapping persistence, duplicate detection,
preview generation, and bulk transaction insertion from bank statement exports.

Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.extensions import db
from app.models.account import Account
from app.models.csv_import import ImportColumnMapping, ImportLog
from app.models.transaction import Transaction, TransactionType, TransactionScope
from app.models.user import User


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROW_COUNT = 10_000

SUPPORTED_DELIMITERS = {",", ";"}
SUPPORTED_DECIMAL_SEPARATORS = {",", "."}
SUPPORTED_ENCODINGS = {"utf-8", "iso-8859-1"}


# ---------------------------------------------------------------------------
# Data classes for parsed results
# ---------------------------------------------------------------------------


@dataclass
class ParsedRow:
    """Represents a single parsed row from a CSV file."""

    row_number: int
    date: Optional[date_type]
    amount: Optional[Decimal]
    description: Optional[str]
    transaction_type: Optional[str]  # "income" or "expense"
    raw_amount: Optional[str] = None
    is_duplicate: bool = False
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """Whether this row parsed successfully without errors."""
        return self.error is None and self.date is not None and self.amount is not None


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    rows: list[ParsedRow] = field(default_factory=list)
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    duplicate_rows: int = 0
    headers: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    """Result of confirming an import."""

    total_rows: int = 0
    imported_rows: int = 0
    skipped_rows: int = 0
    import_log_id: Optional[int] = None


# ---------------------------------------------------------------------------
# ImportService
# ---------------------------------------------------------------------------


class ImportService:
    """Service for CSV bank statement import with configurable parsing.

    Supports:
    - Configurable delimiters (semicolon/comma)
    - Configurable decimal separators (comma/dot)
    - Multiple encodings (UTF-8/ISO-8859-1)
    - Column mapping persistence and retrieval
    - Duplicate detection (date + amount + account)
    - File size and row count validation
    - Error flagging for unparseable rows
    """

    # -------------------------------------------------------------------------
    # Column mapping persistence (Req 17.1, 17.2, 17.3)
    # -------------------------------------------------------------------------

    def get_mapping(self, account_id: int, bank_name: Optional[str] = None) -> Optional[ImportColumnMapping]:
        """Retrieve saved column mapping for an account/bank combination.

        Validates: Requirement 17.1

        Args:
            account_id: The target account ID.
            bank_name: Optional bank name to find specific mapping.

        Returns:
            The ImportColumnMapping if found, None otherwise.
        """
        query = ImportColumnMapping.query.filter_by(account_id=account_id)
        if bank_name is not None:
            query = query.filter_by(bank_name=bank_name)
        else:
            query = query.filter(ImportColumnMapping.bank_name.is_(None))
        return query.first()

    def save_mapping(
        self,
        account_id: int,
        date_column: int,
        amount_column: int,
        date_format: str,
        delimiter: str,
        decimal_separator: str,
        encoding: str = "utf-8",
        description_column: Optional[int] = None,
        bank_name: Optional[str] = None,
    ) -> ImportColumnMapping:
        """Save or update a column mapping for an account/bank combination.

        Validates: Requirement 17.3

        Args:
            account_id: The target account ID.
            date_column: Zero-based index of the date column.
            amount_column: Zero-based index of the amount column.
            date_format: strftime-compatible date format string.
            delimiter: CSV delimiter character (',' or ';').
            decimal_separator: Decimal separator character (',' or '.').
            encoding: File encoding ('utf-8' or 'iso-8859-1').
            description_column: Optional zero-based index of description column.
            bank_name: Optional bank identifier for the mapping.

        Returns:
            The saved or updated ImportColumnMapping instance.

        Raises:
            ValueError: If delimiter, decimal_separator, or encoding is unsupported.
        """
        self._validate_mapping_params(delimiter, decimal_separator, encoding)

        # Try to find existing mapping
        existing = self.get_mapping(account_id, bank_name)

        if existing is not None:
            existing.date_column = date_column
            existing.amount_column = amount_column
            existing.description_column = description_column
            existing.date_format = date_format
            existing.delimiter = delimiter
            existing.decimal_separator = decimal_separator
            existing.encoding = encoding
            db.session.commit()
            return existing

        mapping = ImportColumnMapping(
            account_id=account_id,
            bank_name=bank_name,
            date_column=date_column,
            amount_column=amount_column,
            description_column=description_column,
            date_format=date_format,
            delimiter=delimiter,
            decimal_separator=decimal_separator,
            encoding=encoding,
        )
        db.session.add(mapping)
        db.session.commit()
        return mapping

    # -------------------------------------------------------------------------
    # File validation (Req 17.9)
    # -------------------------------------------------------------------------

    def validate_file(self, file_content: bytes, row_count: Optional[int] = None) -> Optional[str]:
        """Validate file size and optionally row count.

        Validates: Requirement 17.9

        Args:
            file_content: Raw bytes of the uploaded file.
            row_count: If known, the number of data rows in the file.

        Returns:
            Error message string if validation fails, None if valid.
        """
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            return (
                f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            )
        if row_count is not None and row_count > MAX_ROW_COUNT:
            return (
                f"File exceeds maximum of {MAX_ROW_COUNT:,} rows."
            )
        return None

    # -------------------------------------------------------------------------
    # CSV parsing (Req 17.4, 17.6, 17.7, 17.8)
    # -------------------------------------------------------------------------

    def parse_csv(
        self,
        file_content: bytes,
        date_column: int,
        amount_column: int,
        date_format: str,
        delimiter: str = ";",
        decimal_separator: str = ",",
        encoding: str = "utf-8",
        description_column: Optional[int] = None,
        has_header: bool = True,
    ) -> ParseResult:
        """Parse a CSV file into structured rows using the given column mapping.

        Validates: Requirements 17.4, 17.6, 17.7, 17.8

        Args:
            file_content: Raw bytes of the CSV file.
            date_column: Zero-based column index for date.
            amount_column: Zero-based column index for amount.
            date_format: strftime format for parsing dates (e.g., '%d.%m.%Y').
            delimiter: Column delimiter (',' or ';').
            decimal_separator: Decimal separator in amounts (',' or '.').
            encoding: File encoding ('utf-8' or 'iso-8859-1').
            description_column: Optional zero-based column index for description.
            has_header: Whether the first row is a header row.

        Returns:
            ParseResult with all parsed rows, counts, and headers.

        Raises:
            ValueError: If file exceeds size/row limits or parameters invalid.
        """
        # Validate file size
        size_error = self.validate_file(file_content)
        if size_error:
            raise ValueError(size_error)

        self._validate_mapping_params(delimiter, decimal_separator, encoding)

        # Decode file content
        try:
            text_content = file_content.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            raise ValueError(f"Failed to decode file with encoding '{encoding}': {e}")

        # Parse CSV
        reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
        rows_iter = iter(reader)

        result = ParseResult()

        # Handle header
        if has_header:
            try:
                result.headers = next(rows_iter)
            except StopIteration:
                return result

        # Parse data rows
        row_number = 0
        for csv_row in rows_iter:
            row_number += 1

            # Validate row count limit
            if row_number > MAX_ROW_COUNT:
                raise ValueError(
                    f"File exceeds maximum of {MAX_ROW_COUNT:,} rows."
                )

            parsed_row = self._parse_row(
                csv_row=csv_row,
                row_number=row_number,
                date_column=date_column,
                amount_column=amount_column,
                date_format=date_format,
                decimal_separator=decimal_separator,
                description_column=description_column,
            )
            result.rows.append(parsed_row)

        # Calculate counts
        result.total_rows = len(result.rows)
        result.valid_rows = sum(1 for r in result.rows if r.is_valid)
        result.error_rows = sum(1 for r in result.rows if not r.is_valid)

        return result

    # -------------------------------------------------------------------------
    # Preview with duplicate detection (Req 17.4)
    # -------------------------------------------------------------------------

    def preview(
        self,
        parse_result: ParseResult,
        account_id: int,
    ) -> ParseResult:
        """Mark duplicate rows in the parse result based on existing transactions.

        Validates: Requirement 17.4

        Duplicates are detected by matching (date + amount + account_id) against
        existing transactions in the database.

        Args:
            parse_result: The result from parse_csv.
            account_id: The target account for duplicate detection.

        Returns:
            The same ParseResult with is_duplicate flags set on matching rows.
        """
        # Load existing transactions for this account for duplicate checking
        existing_transactions = Transaction.query.filter_by(
            account_id=account_id
        ).all()

        # Build a set of (date, amount) tuples for quick lookup
        existing_set = set()
        for txn in existing_transactions:
            existing_set.add((txn.date, txn.amount))

        duplicate_count = 0
        for row in parse_result.rows:
            if not row.is_valid:
                continue

            # Check if this row matches an existing transaction
            if (row.date, row.amount) in existing_set:
                row.is_duplicate = True
                duplicate_count += 1

        parse_result.duplicate_rows = duplicate_count
        return parse_result

    # -------------------------------------------------------------------------
    # Confirm import (Req 17.5, 17.6)
    # -------------------------------------------------------------------------

    def confirm_import(
        self,
        parse_result: ParseResult,
        account_id: int,
        user: User,
        filename: str,
        skip_duplicates: bool = True,
        override_rows: Optional[set[int]] = None,
    ) -> ImportResult:
        """Bulk-insert valid transactions from parsed CSV data.

        Validates: Requirements 17.5, 17.6

        Args:
            parse_result: The previewed ParseResult.
            account_id: Target account for imported transactions.
            user: The user performing the import.
            filename: Original filename for the import log.
            skip_duplicates: Whether to skip duplicate rows (default True).
            override_rows: Set of row_numbers to import even if flagged as duplicate.

        Returns:
            ImportResult with counts and import log ID.
        """
        if override_rows is None:
            override_rows = set()

        result = ImportResult(total_rows=parse_result.total_rows)
        imported_count = 0
        skipped_count = 0

        for row in parse_result.rows:
            # Skip error rows
            if not row.is_valid:
                skipped_count += 1
                continue

            # Handle duplicates
            if row.is_duplicate and skip_duplicates:
                if row.row_number not in override_rows:
                    skipped_count += 1
                    continue

            # Determine transaction type from amount sign (Req 17.6)
            txn_type = TransactionType.income if row.transaction_type == "income" else TransactionType.expense

            transaction = Transaction(
                type=txn_type,
                amount=row.amount,
                date=row.date,
                description=row.description,
                scope=TransactionScope.personal,
                account_id=account_id,
                posted=True,
                user_id=user.id,
            )
            db.session.add(transaction)
            imported_count += 1

        # Update account balance for imported transactions
        if imported_count > 0:
            account = db.session.get(Account, account_id)
            if account is not None:
                for row in parse_result.rows:
                    if not row.is_valid:
                        continue
                    if row.is_duplicate and skip_duplicates and row.row_number not in override_rows:
                        continue
                    if row.transaction_type == "income":
                        account.balance += row.amount
                    else:
                        account.balance -= row.amount

        # Create import log (Req 17.5)
        import_log = ImportLog(
            account_id=account_id,
            filename=filename,
            total_rows=parse_result.total_rows,
            imported_rows=imported_count,
            skipped_rows=skipped_count,
            user_id=user.id,
        )
        db.session.add(import_log)
        db.session.commit()

        result.imported_rows = imported_count
        result.skipped_rows = skipped_count
        result.import_log_id = import_log.id

        return result

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _validate_mapping_params(
        self, delimiter: str, decimal_separator: str, encoding: str
    ) -> None:
        """Validate that mapping parameters are within supported values.

        Raises:
            ValueError: If any parameter is unsupported.
        """
        if delimiter not in SUPPORTED_DELIMITERS:
            raise ValueError(
                f"Unsupported delimiter: {delimiter!r}. "
                f"Supported: {sorted(SUPPORTED_DELIMITERS)}"
            )
        if decimal_separator not in SUPPORTED_DECIMAL_SEPARATORS:
            raise ValueError(
                f"Unsupported decimal separator: {decimal_separator!r}. "
                f"Supported: {sorted(SUPPORTED_DECIMAL_SEPARATORS)}"
            )
        if encoding.lower() not in SUPPORTED_ENCODINGS:
            raise ValueError(
                f"Unsupported encoding: {encoding!r}. "
                f"Supported: {sorted(SUPPORTED_ENCODINGS)}"
            )

    def _parse_row(
        self,
        csv_row: list[str],
        row_number: int,
        date_column: int,
        amount_column: int,
        date_format: str,
        decimal_separator: str,
        description_column: Optional[int],
    ) -> ParsedRow:
        """Parse a single CSV row into a ParsedRow.

        Validates: Requirement 17.8

        Handles:
        - Missing required columns (date, amount)
        - Unparseable dates
        - Non-numeric amounts
        - Transaction type determination from amount sign (Req 17.6)
        """
        # Check if required columns exist in this row
        max_needed_col = max(
            date_column, amount_column,
            description_column if description_column is not None else 0,
        )
        if len(csv_row) <= max_needed_col:
            return ParsedRow(
                row_number=row_number,
                date=None,
                amount=None,
                description=None,
                transaction_type=None,
                error=f"Row has {len(csv_row)} columns, but column index {max_needed_col} is required.",
            )

        # Parse date
        raw_date = csv_row[date_column].strip()
        parsed_date = self._parse_date(raw_date, date_format)
        if parsed_date is None:
            return ParsedRow(
                row_number=row_number,
                date=None,
                amount=None,
                description=None,
                transaction_type=None,
                error=f"Unparseable date: {raw_date!r} (expected format: {date_format}).",
            )

        # Parse amount
        raw_amount = csv_row[amount_column].strip()
        parsed_amount = self._parse_amount(raw_amount, decimal_separator)
        if parsed_amount is None:
            return ParsedRow(
                row_number=row_number,
                date=parsed_date,
                amount=None,
                description=None,
                transaction_type=None,
                raw_amount=raw_amount,
                error=f"Non-numeric amount: {raw_amount!r}.",
            )

        # Determine transaction type from sign (Req 17.6)
        if parsed_amount >= 0:
            transaction_type = "income"
            abs_amount = parsed_amount
        else:
            transaction_type = "expense"
            abs_amount = abs(parsed_amount)

        # Validate amount range (must be positive after abs)
        if abs_amount < Decimal("0.01") or abs_amount > Decimal("999999999.99"):
            return ParsedRow(
                row_number=row_number,
                date=parsed_date,
                amount=None,
                description=None,
                transaction_type=None,
                raw_amount=raw_amount,
                error=f"Amount {abs_amount} out of valid range (0.01 to 999,999,999.99).",
            )

        # Parse description (optional)
        description = None
        if description_column is not None and len(csv_row) > description_column:
            description = csv_row[description_column].strip() or None

        return ParsedRow(
            row_number=row_number,
            date=parsed_date,
            amount=abs_amount,
            description=description,
            transaction_type=transaction_type,
            raw_amount=raw_amount,
        )

    def _parse_date(self, raw_date: str, date_format: str) -> Optional[date_type]:
        """Parse a date string using the given format.

        Args:
            raw_date: The raw date string from CSV.
            date_format: strftime format string.

        Returns:
            Parsed date or None if parsing fails.
        """
        if not raw_date:
            return None
        try:
            return datetime.strptime(raw_date, date_format).date()
        except (ValueError, TypeError):
            return None

    def _parse_amount(self, raw_amount: str, decimal_separator: str) -> Optional[Decimal]:
        """Parse an amount string with configurable decimal separator.

        Handles both comma and dot decimal separators, stripping thousands
        separators (the opposite character).

        Args:
            raw_amount: The raw amount string from CSV.
            decimal_separator: The character used as decimal separator.

        Returns:
            Parsed Decimal or None if parsing fails.
        """
        if not raw_amount:
            return None

        # Remove any whitespace and currency symbols
        cleaned = raw_amount.strip()
        # Remove common currency symbols
        for char in ("€", "$", "£", "CHF"):
            cleaned = cleaned.replace(char, "")
        cleaned = cleaned.strip()

        if not cleaned:
            return None

        # Handle thousands separator (opposite of decimal separator)
        if decimal_separator == ",":
            # Thousands separator is dot
            cleaned = cleaned.replace(".", "")
            # Replace comma with dot for Decimal parsing
            cleaned = cleaned.replace(",", ".")
        elif decimal_separator == ".":
            # Thousands separator is comma
            cleaned = cleaned.replace(",", "")

        try:
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None
