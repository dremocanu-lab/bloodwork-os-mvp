"""source evidence field bboxes

Revision ID: c7d2e91a4b6f
Revises: a1c9d4e7f203
Create Date: 2026-09-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d2e91a4b6f'
down_revision: Union[str, Sequence[str], None] = 'a1c9d4e7f203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Pre-Phase-11 exact provenance session: one additive, nullable column
    on `source_evidence` persisting the real per-field citation rects
    Reducto Extract already returns per lab row (test_name/value/unit/
    reference_range, whichever were cited), as JSON.

    Root cause of the reported coarse-highlight bug (NEUT# covering
    neighboring PCT/NRBC#/NRBC% rows): `row_bbox_*` is a UNION of those
    same per-field rects padded by a fixed ratio of its own height, which
    on a dense lab table bleeds into adjacent rows. The fix is not a
    better padding formula (still guessable-wrong for some table density);
    it's to stop discarding the real, independently-precise per-field
    citations and let the UI highlight each cited field's own exact box
    instead of one padded union.

    A migration (not a read-time fix) is required because these per-field
    rects are computed transiently inside `extract_lab_results()` at
    extraction time and never persisted individually today — only their
    lossy union (`row_bbox_*`) survives, so they cannot be reconstructed
    later from what's already in the database. Nullable and additive:
    every existing row keeps working unchanged via the existing
    row_bbox_*/bbox_* fallback.
    """
    op.add_column('source_evidence', sa.Column('field_bboxes_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('source_evidence', 'field_bboxes_json')
