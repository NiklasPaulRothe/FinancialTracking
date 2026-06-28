"""Category model for Haushaltsbuch.

Provides the categories table referenced by transactions and splits.
Full service logic will be added in a later task.

Validates: Requirement 20.1
"""

from app.extensions import db


class Category(db.Model):
    """A user-defined category for classifying transactions.

    Categories are scoped as personal or shared and must have unique names
    within the same user + scope combination.
    """

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    scope = db.Column(db.String(10), nullable=False)  # 'personal' or 'shared'
    icon = db.Column(db.String(50), nullable=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint("name", "user_id", "scope", name="uq_categories_name_user_scope"),
    )

    def __repr__(self) -> str:
        return f"<Category {self.name!r}>"
