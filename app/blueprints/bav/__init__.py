"""bAV (betriebliche Altersvorsorge) blueprint for Haushaltsbuch.

Provides index, create, and detail routes for bAV contract management.

Validates: Requirements 15.1
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.bav import BaV, BaVType, BaVContributionLog
from app.blueprints.bav.forms import BaVCreateForm

bav_bp = Blueprint(
    "bav",
    __name__,
    url_prefix="/bav",
    template_folder="templates",
)


@bav_bp.route("/")
@login_required
def index():
    """Display all bAV contracts for the current user.

    Validates: Requirement 15.1
    """
    contracts = BaV.query.filter_by(user_id=current_user.id).order_by(
        BaV.active.desc(), BaV.start_date.desc()
    ).all()

    active_contracts = [c for c in contracts if c.active]
    inactive_contracts = [c for c in contracts if not c.active]

    return render_template(
        "bav/index.html",
        active_contracts=active_contracts,
        inactive_contracts=inactive_contracts,
    )


@bav_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new bAV contract.

    Validates: Requirement 15.1
    """
    form = BaVCreateForm()

    if form.validate_on_submit():
        employee = form.employee_contribution_monthly.data
        employer = form.employer_contribution_monthly.data
        total = employee + employer

        contract = BaV(
            provider=form.provider.data,
            type=BaVType(form.type.data),
            start_date=form.start_date.data,
            employee_contribution_monthly=employee,
            employer_contribution_monthly=employer,
            total_contribution_monthly=total,
            user_id=current_user.id,
        )
        db.session.add(contract)
        db.session.commit()

        flash("bAV-Vertrag erfolgreich angelegt.", "success")
        return redirect(url_for("bav.index"))

    return render_template("bav/create.html", form=form)


@bav_bp.route("/detail/<int:id>")
@login_required
def detail(id):
    """Show bAV contract details with contribution history.

    Validates: Requirement 15.1
    """
    contract = BaV.query.get(id)
    if contract is None or contract.user_id != current_user.id:
        flash("bAV-Vertrag nicht gefunden.", "danger")
        return redirect(url_for("bav.index"))

    contributions = BaVContributionLog.query.filter_by(
        bav_id=contract.id
    ).order_by(BaVContributionLog.month.desc()).all()

    return render_template(
        "bav/detail.html",
        contract=contract,
        contributions=contributions,
    )
