"""VL (Vermögenswirksame Leistungen) blueprint for Haushaltsbuch.

Provides index, create, and detail routes for VL contract management.

Validates: Requirements 16.1, 16.5
"""

from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.bav import VL, VLContributionLog
from app.models.etf import ETFPosition
from app.blueprints.vl.forms import VLCreateForm
from app.services.vl_service import VLService

vl_bp = Blueprint(
    "vl",
    __name__,
    url_prefix="/vl",
    template_folder="templates",
)


def _get_user_etf_positions():
    """Get ETF positions for the current user."""
    return ETFPosition.query.filter_by(user_id=current_user.id).all()


def _resolve_ticker_from_isin(isin: str, exchange: str = "DE") -> str | None:
    """Resolve a Yahoo Finance ticker symbol from an ISIN.

    Uses Yahoo Finance's search API to find the ticker symbol for a given ISIN.

    Args:
        isin: The ISIN to look up (e.g. IE00B4L5Y983).
        exchange: Preferred exchange suffix (e.g. DE for Xetra).

    Returns:
        The ticker symbol (e.g. "EUNL.DE") or None if not found.
    """
    if not isin or not isin.strip():
        return None

    isin = isin.upper().strip()
    from flask import current_app

    # Approach 1: yfinance Search API
    try:
        import yfinance as yf
        results = yf.Search(isin)
        quotes = getattr(results, 'quotes', None)
        if quotes:
            current_app.logger.info(f"VL ISIN resolve: yf.Search returned {len(quotes)} results for {isin}")
            # Prefer result matching desired exchange
            for quote in quotes:
                symbol = quote.get("symbol", "") if isinstance(quote, dict) else ""
                if symbol.endswith(f".{exchange}"):
                    return symbol
            # Return first result
            first = quotes[0]
            return first.get("symbol", "") if isinstance(first, dict) else str(first)
        else:
            current_app.logger.info(f"VL ISIN resolve: yf.Search returned no results for {isin}")
    except Exception as e:
        current_app.logger.warning(f"VL ISIN resolve via yf.Search failed: {e}")

    # Approach 2: Yahoo Finance query API directly
    try:
        import urllib.request
        import json

        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=5&newsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            quotes = data.get("quotes", [])
            current_app.logger.info(f"VL ISIN resolve: Yahoo API returned {len(quotes)} results for {isin}")
            if quotes:
                for q in quotes:
                    symbol = q.get("symbol", "")
                    if symbol.endswith(f".{exchange}"):
                        return symbol
                return quotes[0].get("symbol")
    except Exception as e:
        current_app.logger.warning(f"VL ISIN resolve via Yahoo API failed: {e}")

    return None


def _get_or_create_etf_position(isin, name, ticker, exchange, user_id, manual_price=None):
    """Create a new ETF position for the VL contract.

    Each VL contract always gets its own dedicated ETFPosition (even for the
    same ISIN) because VL contracts have separate lock-up rules and must be
    tracked independently (Req 16.8).

    After creation, attempts to fetch the current price via yfinance so that
    historic backfill can calculate shares. Falls back to manual_price if
    the automatic fetch fails.

    Args:
        isin: The ISIN of the ETF (e.g. IE00BK5BQT80).
        name: Human-readable name of the ETF.
        ticker: Ticker symbol (e.g. EUNL).
        exchange: Exchange suffix (e.g. DE).
        user_id: The owning user's ID.
        manual_price: Optional fallback price if yfinance fetch fails.

    Returns:
        A newly created ETFPosition (with current_price if fetch succeeded).
    """
    from datetime import datetime, timezone
    from decimal import Decimal
    from flask import current_app

    effective_exchange = (exchange or "DE").upper().strip()[:10]

    # Auto-resolve ticker from ISIN if not provided
    resolved_full_symbol = None
    if not ticker or not ticker.strip():
        resolved = _resolve_ticker_from_isin(isin, effective_exchange)
        if resolved:
            resolved_full_symbol = resolved
            # Extract base ticker for storage
            if "." in resolved:
                parts = resolved.rsplit(".", 1)
                ticker = parts[0]
                # Use the exchange where it was actually found for price fetch
                # but store user's preferred exchange for future reference
            else:
                ticker = resolved
            current_app.logger.info(
                f"VL: ISIN {isin} resolved to {resolved}"
            )

    effective_ticker = (ticker or "UNKNOWN").upper().strip()[:10]

    position = ETFPosition(
        isin=isin.upper().strip() if isin else None,
        ticker=effective_ticker,
        exchange_suffix=effective_exchange,
        name=name or f"ETF {isin or ticker}",
        shares=Decimal("0.000000"),
        average_buy_price=Decimal("0.000000"),
        user_id=user_id,
    )
    db.session.add(position)
    db.session.flush()

    # Attempt to fetch current price immediately so backfill can work
    try:
        import yfinance as yf

        price = None

        # Strategy 1: Try the full resolved symbol as-is (e.g. IWDA.L)
        if price is None and resolved_full_symbol:
            current_app.logger.info(f"VL price fetch attempt 1 (resolved): {resolved_full_symbol}")
            yf_ticker = yf.Ticker(resolved_full_symbol)
            hist = yf_ticker.history(period="5d")
            if not hist.empty:
                price = Decimal(str(hist["Close"].iloc[-1])).quantize(Decimal("0.0001"))
                # Update position to use the working ticker/exchange
                if "." in resolved_full_symbol:
                    parts = resolved_full_symbol.rsplit(".", 1)
                    position.ticker = parts[0][:10]
                    position.exchange_suffix = parts[1][:10]

        # Strategy 2: Try ticker.preferred_exchange (e.g. IWDA.DE)
        if price is None and ticker and ticker.strip():
            ticker_symbol = f"{effective_ticker}.{effective_exchange}"
            current_app.logger.info(f"VL price fetch attempt 2 (preferred): {ticker_symbol}")
            yf_ticker = yf.Ticker(ticker_symbol)
            hist = yf_ticker.history(period="5d")
            if not hist.empty:
                price = Decimal(str(hist["Close"].iloc[-1])).quantize(Decimal("0.0001"))

        # Strategy 3: Try ISIN directly
        if price is None and isin and isin.strip():
            current_app.logger.info(f"VL price fetch attempt 3 (ISIN): {isin.upper().strip()}")
            yf_ticker = yf.Ticker(isin.upper().strip())
            hist = yf_ticker.history(period="5d")
            if not hist.empty:
                price = Decimal(str(hist["Close"].iloc[-1])).quantize(Decimal("0.0001"))

        if price is not None:
            position.current_price = price
            position.current_price_updated_at = datetime.now(timezone.utc)
            db.session.flush()
            current_app.logger.info(f"VL price fetched successfully: {price}")
        else:
            current_app.logger.warning(
                f"VL price fetch: no price found for ticker={effective_ticker}, "
                f"isin={isin}, exchange={effective_exchange}"
            )
    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"VL price fetch failed: {e}")
        # Price fetch failed — will try manual price below

    # Fallback: use manual price if yfinance didn't work
    if position.current_price is None and manual_price is not None:
        position.current_price = Decimal(str(manual_price)).quantize(Decimal("0.0001"))
        position.current_price_updated_at = datetime.now(timezone.utc)
        position.manual_price_override = True
        db.session.flush()

    return position


@vl_bp.route("/")
@login_required
def index():
    """Display all VL contracts for the current user.

    Validates: Requirement 16.1
    """
    contracts = VL.query.filter_by(user_id=current_user.id).order_by(
        VL.active.desc(), VL.start_date.desc()
    ).all()

    active_contracts = [c for c in contracts if c.active]
    inactive_contracts = [c for c in contracts if not c.active]
    today = date.today()

    return render_template(
        "vl/index.html",
        active_contracts=active_contracts,
        inactive_contracts=inactive_contracts,
        today=today,
    )


@vl_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new VL contract.

    If an ISIN is provided, the system will auto-create an ETFPosition
    (or reuse an existing one with the same ISIN for this user).

    Validates: Requirement 16.1
    """
    form = VLCreateForm()

    if form.validate_on_submit():
        employer = form.employer_contribution_monthly.data
        employee = form.employee_contribution_monthly.data or 0
        total = employer + employee

        # Auto-create or find ETF position if ISIN provided
        etf_position_id = None
        if form.etf_isin.data and form.etf_isin.data.strip():
            position = _get_or_create_etf_position(
                isin=form.etf_isin.data,
                name=form.etf_name.data,
                ticker=form.etf_ticker.data,
                exchange=form.etf_exchange.data,
                manual_price=form.etf_price.data,
                user_id=current_user.id,
            )
            etf_position_id = position.id

            if position.current_price is None:
                flash(
                    f"ETF-Kurs konnte nicht abgerufen werden. "
                    f"Ticker: {position.ticker}.{position.exchange_suffix}, ISIN: {form.etf_isin.data}. "
                    f"Bitte geben Sie einen manuellen Kurs an oder prüfen Sie den Ticker.",
                    "warning",
                )

        contract = VL(
            name=form.name.data,
            employer_contribution_monthly=employer,
            employee_contribution_monthly=employee,
            total_contribution_monthly=total,
            start_date=form.start_date.data,
            lock_up_end_date=form.lock_up_end_date.data,
            etf_position_id=etf_position_id,
            sparzulage_rate=form.sparzulage_rate.data,
            annual_eligible_max=form.annual_eligible_max.data,
            user_id=current_user.id,
        )
        db.session.add(contract)
        db.session.flush()

        # Backfill historic contributions if start_date is in the past
        from datetime import date as date_type
        if form.start_date.data <= date_type.today():
            vl_service = VLService()
            vl_service.backfill_contributions(contract, current_user)

        db.session.commit()

        flash("VL-Vertrag erfolgreich angelegt.", "success")
        return redirect(url_for("vl.index"))

    return render_template("vl/create.html", form=form)


@vl_bp.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    """Delete a VL contract and its contribution logs.

    Also deletes the linked ETF position and its transactions if it was
    created specifically for this VL contract.
    """
    contract = VL.query.get(id)
    if contract is None or contract.user_id != current_user.id:
        flash("VL-Vertrag nicht gefunden.", "danger")
        return redirect(url_for("vl.index"))

    # Delete contribution logs (cascade should handle, but be explicit)
    VLContributionLog.query.filter_by(vl_id=contract.id).delete()

    # If linked to an ETF position, delete the position too
    # (VL positions are created per-contract and not shared)
    if contract.etf_position_id is not None:
        position = db.session.get(ETFPosition, contract.etf_position_id)
        if position is not None:
            # Delete ETF transactions for this position
            from app.models.etf import ETFTransaction
            ETFTransaction.query.filter_by(position_id=position.id).delete()
            db.session.delete(position)

    db.session.delete(contract)
    db.session.commit()

    flash("VL-Vertrag erfolgreich gelöscht.", "success")
    return redirect(url_for("vl.index"))


@vl_bp.route("/detail/<int:id>")
@login_required
def detail(id):
    """Show VL contract details with contribution history and lock-up status.

    Validates: Requirements 16.1, 16.5
    """
    contract = VL.query.get(id)
    if contract is None or contract.user_id != current_user.id:
        flash("VL-Vertrag nicht gefunden.", "danger")
        return redirect(url_for("vl.index"))

    contributions = VLContributionLog.query.filter_by(
        vl_id=contract.id
    ).order_by(VLContributionLog.month.desc()).all()

    today = date.today()
    lock_up_active = today < contract.lock_up_end_date

    return render_template(
        "vl/detail.html",
        contract=contract,
        contributions=contributions,
        lock_up_active=lock_up_active,
        today=today,
    )
