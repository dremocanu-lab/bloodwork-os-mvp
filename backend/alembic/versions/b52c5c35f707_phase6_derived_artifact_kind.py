"""phase6 derived artifact kind

Revision ID: b52c5c35f707
Revises: 2398fbce8a2c
Create Date: 2026-09-15 11:07:53.352476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b52c5c35f707'
down_revision: Union[str, Sequence[str], None] = '2398fbce8a2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clinical Document Intelligence V3, Phase 6: one additive, nullable
    column distinguishing a derived-artifact Document (Phase 6's
    embedded-lab derived report) from an ordinary uploaded/Reducto-Split
    child Document that also uses `parent_document_id` — see
    app/models.py's Document.derived_artifact_kind docstring for why this
    is genuinely necessary rather than reusing parent_document_id alone.

    Autogenerate also proposed dropping the same 8 harmless historical
    duplicate indexes documented in 0003_phase3_hardening.py
    (ix_eas_*/ix_eal_*/ix_ec_patient) — deliberately omitted here for the
    same reason: unrelated to Phase 6, not a side effect of this column.
    """
    op.add_column('documents', sa.Column('derived_artifact_kind', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'derived_artifact_kind')
