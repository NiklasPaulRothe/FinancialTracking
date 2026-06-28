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

vl_bp = Blueprint(
    "vl",
    __name__,
    url_prefix="/vl",
    template_folder="templates",
)


def _get_user_etf_positions():
    """Get ETF positions for the current user."""
    return ETFPosition.query.filter_by(user_id=current_user.id).all()


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

    Validates: Requirement 16.1
    """
    etf_positions = _get_user_etf_positions()
    form = VLCreateForm(etf_positions=etf_positions)

    if form.validate_on_submit():
        employer = form.employer_contribution_monthly.data
        employee = form.employee_contribution_monthly.data or 0
        total = employer + employee

        etf_position_id = form.etf_position_id.data
        if etf_position_id == 0:
            etf_position_id = None

        contract = VL(
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
        db.session.commit()

        flash("VL-Vertrag erfolgreich angelegt.", "success")
        return redirect(url_for("vl.index"))

    return render_template("vl/create.html", form=form)


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
