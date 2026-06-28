"""ETF blueprint for Haushaltsbuch.

Provides portfolio overview, add_position, buy, and sell routes
for ETF investment tracking.

Validates: Requirements 13.1, 13.5, 13.6, 14.1
"""

from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.account import Account
from app.models.etf import ETFPosition, ETFTransaction, ETFTransactionType
from app.blueprints.etf.forms import ETFPositionForm, ETFBuySellForm

etf_bp = Blueprint(
    "etf",
    __name__,
    url_prefix="/etf",
    template_folder="templates",
)


def _get_user_accounts():
    """Get active accounts for the current user."""
    return Account.query.filter_by(owner_id=current_user.id, active=True).all()


@etf_bp.route("/")
@login_required
def portfolio():
    """Display all ETF positions with current value, gain/loss, and savings plans.

    Validates: Requirement 13.1
    Shows portfolio overview with each position's ticker, name, shares,
    average buy price, current price, total value, and unrealized gain/loss.
    """
    positions = ETFPosition.query.filter_by(user_id=current_user.id).all()

    # Compute derived values for display
    portfolio_data = []
    total_value = 0
    total_invested = 0

    for pos in positions:
        current_price = pos.current_price
        invested = float(pos.shares * pos.average_buy_price)
        current_val = float(pos.shares * current_price) if current_price else None
        gain_loss = (current_val - invested) if current_val is not None else None
        gain_loss_pct = (
            (gain_loss / invested * 100) if gain_loss is not None and invested > 0 else None
        )

        portfolio_data.append({
            "position": pos,
            "invested": invested,
            "current_value": current_val,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
        })

        total_invested += invested
        if current_val is not None:
            total_value += current_val

    return render_template(
        "etf/portfolio.html",
        portfolio_data=portfolio_data,
        total_value=total_value,
        total_invested=total_invested,
    )


@etf_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_position():
    """Add a new ETF position to the portfolio.

    Validates: Requirement 13.1
    Form fields: ticker, exchange_suffix, name, initial shares, average_buy_price.
    """
    form = ETFPositionForm()

    if form.validate_on_submit():
        position = ETFPosition(
            ticker=form.ticker.data,
            exchange_suffix=form.exchange_suffix.data,
            name=form.name.data,
            shares=form.shares.data,
            average_buy_price=form.average_buy_price.data,
            user_id=current_user.id,
        )
        db.session.add(position)
        db.session.commit()
        flash("ETF-Position erfolgreich hinzugefügt.", "success")
        return redirect(url_for("etf.portfolio"))

    return render_template("etf/add_position.html", form=form)


@etf_bp.route("/buy/<int:id>", methods=["GET", "POST"])
@login_required
def buy(id):
    """Record a buy transaction for an ETF position.

    Validates: Requirement 13.5
    Increases shares and recalculates average_buy_price.
    Optionally deducts total_amount from linked account.
    """
    position = db.session.get(ETFPosition, id)
    if position is None or position.user_id != current_user.id:
        flash("ETF-Position nicht gefunden.", "danger")
        return redirect(url_for("etf.portfolio"))

    accounts = _get_user_accounts()
    form = ETFBuySellForm(accounts=accounts)

    if form.validate_on_submit():
        shares_qty = form.shares_quantity.data
        price = form.price_per_share.data
        total_amount = shares_qty * price
        linked_account_id = (
            form.linked_account_id.data
            if form.linked_account_id.data and form.linked_account_id.data != 0
            else None
        )

        # Recalculate average buy price
        existing_value = position.shares * position.average_buy_price
        new_value = shares_qty * price
        new_total_shares = position.shares + shares_qty
        position.average_buy_price = (existing_value + new_value) / new_total_shares
        position.shares = new_total_shares

        # Create transaction record
        transaction = ETFTransaction(
            position_id=position.id,
            type=ETFTransactionType.buy,
            shares_quantity=shares_qty,
            price_per_share=price,
            total_amount=total_amount,
            linked_account_id=linked_account_id,
            date=form.date.data,
            user_id=current_user.id,
        )
        db.session.add(transaction)

        # Deduct from linked account if specified
        if linked_account_id:
            account = db.session.get(Account, linked_account_id)
            if account and account.owner_id == current_user.id:
                account.balance -= total_amount

        db.session.commit()
        flash("Kauftransaktion erfolgreich gebucht.", "success")
        return redirect(url_for("etf.portfolio"))

    # Default date to today for new form
    if not form.date.data:
        form.date.data = date.today()

    return render_template("etf/buy.html", form=form, position=position)


@etf_bp.route("/sell/<int:id>", methods=["GET", "POST"])
@login_required
def sell(id):
    """Record a sell transaction for an ETF position.

    Validates: Requirement 13.6
    Decreases shares using average cost method (average_buy_price unchanged).
    Optionally adds total_amount to linked account.
    """
    position = db.session.get(ETFPosition, id)
    if position is None or position.user_id != current_user.id:
        flash("ETF-Position nicht gefunden.", "danger")
        return redirect(url_for("etf.portfolio"))

    accounts = _get_user_accounts()
    form = ETFBuySellForm(accounts=accounts)

    if form.validate_on_submit():
        shares_qty = form.shares_quantity.data
        price = form.price_per_share.data
        total_amount = shares_qty * price
        linked_account_id = (
            form.linked_account_id.data
            if form.linked_account_id.data and form.linked_account_id.data != 0
            else None
        )

        # Check sufficient shares
        if shares_qty > position.shares:
            flash(
                "Nicht genügend Anteile vorhanden. "
                f"Verfügbar: {position.shares} Anteile.",
                "danger",
            )
            return render_template("etf/sell.html", form=form, position=position)

        # Decrease shares (average_buy_price remains unchanged per average cost method)
        position.shares -= shares_qty

        # Create transaction record
        transaction = ETFTransaction(
            position_id=position.id,
            type=ETFTransactionType.sell,
            shares_quantity=shares_qty,
            price_per_share=price,
            total_amount=total_amount,
            linked_account_id=linked_account_id,
            date=form.date.data,
            user_id=current_user.id,
        )
        db.session.add(transaction)

        # Add to linked account if specified
        if linked_account_id:
            account = db.session.get(Account, linked_account_id)
            if account and account.owner_id == current_user.id:
                account.balance += total_amount

        db.session.commit()
        flash("Verkaufstransaktion erfolgreich gebucht.", "success")
        return redirect(url_for("etf.portfolio"))

    # Default date to today for new form
    if not form.date.data:
        form.date.data = date.today()

    return render_template("etf/sell.html", form=form, position=position)
