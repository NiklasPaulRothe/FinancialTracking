"""CSV Import models for Haushaltsbuch.

Defines ImportColumnMapping and ImportLog tables for tracking CSV bank
statement imports including column mapping configuration and import history.

Validates: Requirements 17.1, 17.5
"""

from datetime import datetime, timezone

from app.extensions import db


class ImportColumnMapping(db.Model):
    """Stores column mapping configuration for CSV bank statement imports.

    Each mapping ties an account to a specific bank format, recording which
    CSV columns contain date, amount, and description data along with
    parsing parameters (date format, delimiter, decimal separator, encoding).

    The UNIQUE constraint on (account_id, bank_name) ensures one mapping
    per bank per account.
    """

    __tablename__ = "import_column_mappings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    bank_name = db.Column(db.String(100), nullable=True)
    date_column = db.Column(db.Integer, nullable=False)
    amount_column = db.Column(db.Integer, nullable=False)
    description_column = db.Column(db.Integer, nullable=True)
    date_format = db.Column(db.String(20), nullable=False)
    delimiter = db.Column(db.String(1), nullable=False)
    decimal_separator = db.Column(db.String(1), nullable=False)
    encoding = db.Column(db.String(20), nullable=False, default="utf-8")
    skip_header_rows = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship(
        "User",
        backref=db.backref("import_column_mappings", lazy="dynamic"),
    )
    account = db.relationship(
        "Account",
        backref=db.backref("import_column_mappings", lazy="dynamic"),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "account_id", "bank_name",
            name="uq_import_column_mappings_account_bank",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ImportColumnMapping account_id={self.account_id} "
            f"bank_name={self.bank_name!r}>"
        )


class ImportLog(db.Model):
    """Records the outcome of a CSV import operation.

    Tracks filename, total rows processed, rows successfully imported,
    and rows skipped (duplicates or parse errors) for audit purposes.
    """

    __tablename__ = "import_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.id"), nullable=False
    )
    filename = db.Column(db.String(255), nullable=False)
    total_rows = db.Column(db.Integer, nullable=False)
    imported_rows = db.Column(db.Integer, nullable=False)
    skipped_rows = db.Column(db.Integer, nullable=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account = db.relationship(
        "Account",
        backref=db.backref("import_logs", lazy="dynamic"),
    )
    user = db.relationship(
        "User",
        backref=db.backref("import_logs", lazy="dynamic"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImportLog filename={self.filename!r} "
            f"imported={self.imported_rows}/{self.total_rows}>"
        )
