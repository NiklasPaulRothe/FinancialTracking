"""CSV Import blueprint for Haushaltsbuch.

Provides a multi-step upload flow: upload → map columns → preview → confirm.
Delegates all business logic to ImportService.

Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9
"""

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session,
)
from flask_login import login_required, current_user

from app.models.account import Account
from app.services.import_service import ImportService

imports_bp = Blueprint(
    "imports", __name__, url_prefix="/import", template_folder="templates"
)

import_service = ImportService()


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


@imports_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Step 1: Upload CSV file and select target account.

    GET: Display file upload form with account selection.
    POST: Validate file, store in session, check for existing mapping.

    Validates: Requirements 17.1, 17.9
    """
    accounts = _get_user_accounts()

    if request.method == "POST":
        # Validate file presence
        if "csv_file" not in request.files:
            flash("Bitte eine CSV-Datei auswählen.", "danger")
            return render_template("imports/upload.html", accounts=accounts)

        csv_file = request.files["csv_file"]
        if csv_file.filename == "":
            flash("Bitte eine CSV-Datei auswählen.", "danger")
            return render_template("imports/upload.html", accounts=accounts)

        account_id = request.form.get("account_id", type=int)
        if not account_id:
            flash("Bitte ein Zielkonto auswählen.", "danger")
            return render_template("imports/upload.html", accounts=accounts)

        # Verify account belongs to user
        account = Account.query.filter_by(
            id=account_id, owner_id=current_user.id, active=True
        ).first()
        if account is None:
            flash("Ungültiges Konto.", "danger")
            return render_template("imports/upload.html", accounts=accounts)

        # Read and validate file
        file_content = csv_file.read()
        error = import_service.validate_file(file_content)
        if error:
            flash(error, "danger")
            return render_template("imports/upload.html", accounts=accounts)

        # Store file data in session for next steps
        session["import_file_content"] = file_content.decode(
            "utf-8", errors="replace"
        )
        session["import_filename"] = csv_file.filename
        session["import_account_id"] = account_id

        # Check for existing mapping (Req 17.1)
        existing_mapping = import_service.get_mapping(account_id)
        if existing_mapping:
            # Store mapping in session and skip to preview
            session["import_mapping"] = {
                "date_column": existing_mapping.date_column,
                "amount_column": existing_mapping.amount_column,
                "description_column": existing_mapping.description_column,
                "date_format": existing_mapping.date_format,
                "delimiter": existing_mapping.delimiter,
                "decimal_separator": existing_mapping.decimal_separator,
                "encoding": existing_mapping.encoding,
            }
            flash(
                "Bestehende Spaltenzuordnung geladen. "
                "Überprüfen Sie die Vorschau oder passen Sie die Zuordnung an.",
                "info",
            )
            return redirect(url_for("imports.preview"))

        # No existing mapping — go to column mapping step
        return redirect(url_for("imports.map_columns"))

    return render_template("imports/upload.html", accounts=accounts)


@imports_bp.route("/map-columns", methods=["GET", "POST"])
@login_required
def map_columns():
    """Step 2: Map CSV columns to required fields.

    GET: Display column mapping interface with detected headers.
    POST: Save mapping and proceed to preview.

    Validates: Requirements 17.2, 17.3
    """
    # Ensure upload step was completed
    if "import_file_content" not in session:
        flash("Bitte zuerst eine Datei hochladen.", "warning")
        return redirect(url_for("imports.upload"))

    file_content_str = session["import_file_content"]
    account_id = session["import_account_id"]

    # Detect headers from the first line (using default delimiter for preview)
    delimiter = request.form.get("delimiter", ";") if request.method == "POST" else ";"
    import csv
    import io

    lines = file_content_str.split("\n")
    # Try to detect headers with given delimiter
    try:
        reader = csv.reader(io.StringIO(lines[0] if lines else ""), delimiter=delimiter)
        headers = next(reader, [])
    except Exception:
        headers = []

    # Show sample rows for context
    sample_rows = []
    try:
        sample_reader = csv.reader(
            io.StringIO("\n".join(lines[1:6])), delimiter=delimiter
        )
        for row in sample_reader:
            if row:
                sample_rows.append(row)
    except Exception:
        pass

    if request.method == "POST":
        # Collect mapping configuration
        try:
            date_column = int(request.form.get("date_column", 0))
            amount_column = int(request.form.get("amount_column", 1))
            description_column_raw = request.form.get("description_column", "")
            description_column = (
                int(description_column_raw) if description_column_raw != "" else None
            )
            date_format = request.form.get("date_format", "%d.%m.%Y")
            delimiter = request.form.get("delimiter", ";")
            decimal_separator = request.form.get("decimal_separator", ",")
            encoding = request.form.get("encoding", "utf-8")
            bank_name = request.form.get("bank_name", "").strip() or None
        except (ValueError, TypeError):
            flash("Ungültige Eingabe bei der Spaltenzuordnung.", "danger")
            return render_template(
                "imports/map_columns.html",
                headers=headers,
                sample_rows=sample_rows,
                num_columns=len(headers),
            )

        # Save mapping (Req 17.3)
        try:
            import_service.save_mapping(
                account_id=account_id,
                date_column=date_column,
                amount_column=amount_column,
                date_format=date_format,
                delimiter=delimiter,
                decimal_separator=decimal_separator,
                encoding=encoding,
                description_column=description_column,
                bank_name=bank_name,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return render_template(
                "imports/map_columns.html",
                headers=headers,
                sample_rows=sample_rows,
                num_columns=len(headers),
            )

        # Store mapping in session
        session["import_mapping"] = {
            "date_column": date_column,
            "amount_column": amount_column,
            "description_column": description_column,
            "date_format": date_format,
            "delimiter": delimiter,
            "decimal_separator": decimal_separator,
            "encoding": encoding,
        }

        flash("Spaltenzuordnung gespeichert.", "success")
        return redirect(url_for("imports.preview"))

    return render_template(
        "imports/map_columns.html",
        headers=headers,
        sample_rows=sample_rows,
        num_columns=len(headers),
    )


@imports_bp.route("/preview", methods=["GET", "POST"])
@login_required
def preview():
    """Step 3: Preview parsed rows with duplicate/error flags.

    GET: Parse CSV and display preview table.
    POST: Re-parse with updated mapping if user changes settings.

    Validates: Requirements 17.4, 17.8
    """
    # Ensure previous steps were completed
    if "import_file_content" not in session or "import_mapping" not in session:
        flash("Bitte zuerst eine Datei hochladen und Spalten zuordnen.", "warning")
        return redirect(url_for("imports.upload"))

    file_content_str = session["import_file_content"]
    mapping = session["import_mapping"]
    account_id = session["import_account_id"]

    # Re-encode to bytes for parsing
    encoding = mapping.get("encoding", "utf-8")
    try:
        file_bytes = file_content_str.encode("utf-8")
    except Exception:
        file_bytes = file_content_str.encode("utf-8", errors="replace")

    # Parse CSV using stored mapping
    try:
        parse_result = import_service.parse_csv(
            file_content=file_bytes,
            date_column=mapping["date_column"],
            amount_column=mapping["amount_column"],
            date_format=mapping["date_format"],
            delimiter=mapping["delimiter"],
            decimal_separator=mapping["decimal_separator"],
            encoding="utf-8",  # Already decoded to utf-8 string in session
            description_column=mapping.get("description_column"),
            has_header=True,
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("imports.upload"))

    # Run duplicate detection (Req 17.4)
    parse_result = import_service.preview(parse_result, account_id)

    # Store parse result summary in session for confirm step
    session["import_parse_result"] = {
        "total_rows": parse_result.total_rows,
        "valid_rows": parse_result.valid_rows,
        "error_rows": parse_result.error_rows,
        "duplicate_rows": parse_result.duplicate_rows,
    }

    # Handle POST for going to mapping adjustment
    if request.method == "POST" and request.form.get("action") == "remap":
        return redirect(url_for("imports.map_columns"))

    account = Account.query.get(account_id)

    return render_template(
        "imports/preview.html",
        parse_result=parse_result,
        account=account,
        mapping=mapping,
    )


@imports_bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    """Step 4: Confirm import and bulk-insert transactions.

    POST: Execute the import with user-selected options.

    Validates: Requirements 17.5, 17.6
    """
    # Ensure previous steps were completed
    if "import_file_content" not in session or "import_mapping" not in session:
        flash("Bitte zuerst eine Datei hochladen und Spalten zuordnen.", "warning")
        return redirect(url_for("imports.upload"))

    file_content_str = session["import_file_content"]
    mapping = session["import_mapping"]
    account_id = session["import_account_id"]
    filename = session.get("import_filename", "unknown.csv")

    # Re-parse file for confirm
    try:
        file_bytes = file_content_str.encode("utf-8")
    except Exception:
        file_bytes = file_content_str.encode("utf-8", errors="replace")

    try:
        parse_result = import_service.parse_csv(
            file_content=file_bytes,
            date_column=mapping["date_column"],
            amount_column=mapping["amount_column"],
            date_format=mapping["date_format"],
            delimiter=mapping["delimiter"],
            decimal_separator=mapping["decimal_separator"],
            encoding="utf-8",
            description_column=mapping.get("description_column"),
            has_header=True,
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("imports.upload"))

    # Run duplicate detection again
    parse_result = import_service.preview(parse_result, account_id)

    # Determine skip settings
    skip_duplicates = request.form.get("skip_duplicates", "true") == "true"

    # Collect override rows (user explicitly chose to import despite duplicate flag)
    override_rows = set()
    for key in request.form:
        if key.startswith("override_row_"):
            try:
                row_num = int(key.replace("override_row_", ""))
                override_rows.add(row_num)
            except ValueError:
                pass

    # Execute import
    try:
        result = import_service.confirm_import(
            parse_result=parse_result,
            account_id=account_id,
            user=current_user,
            filename=filename,
            skip_duplicates=skip_duplicates,
            override_rows=override_rows,
        )
    except Exception as e:
        flash(f"Fehler beim Import: {e}", "danger")
        return redirect(url_for("imports.preview"))

    # Clean up session data
    session.pop("import_file_content", None)
    session.pop("import_filename", None)
    session.pop("import_account_id", None)
    session.pop("import_mapping", None)
    session.pop("import_parse_result", None)

    flash(
        f"Import abgeschlossen: {result.imported_rows} Transaktionen importiert, "
        f"{result.skipped_rows} übersprungen.",
        "success",
    )
    return redirect(url_for("transactions.index"))
