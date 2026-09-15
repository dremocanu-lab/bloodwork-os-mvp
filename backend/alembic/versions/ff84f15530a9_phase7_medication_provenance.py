"""phase7 medication provenance

Revision ID: ff84f15530a9
Revises: b52c5c35f707
Create Date: 2026-09-15 12:50:00.845789

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff84f15530a9'
down_revision: Union[str, Sequence[str], None] = 'b52c5c35f707'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clinical Document Intelligence V3, Phase 7: additive, nullable
    provenance columns for document-derived medication facts — see
    app/models.py's PatientMedication.source_document_id/
    source_segment_id/stop_date_basis and SourceEvidence.medication_id
    docstrings for why each is genuinely necessary.

    Autogenerate also proposed dropping the same 8 harmless historical
    duplicate indexes documented in 0003_phase3_hardening.py and
    b52c5c35f707_phase6_derived_artifact_kind.py
    (ix_eas_*/ix_eal_*/ix_ec_patient) — deliberately omitted here for the
    same reason: unrelated to Phase 7, not a side effect of these columns.
    """
    op.add_column('patient_medications', sa.Column('source_document_id', sa.Integer(), nullable=True))
    op.add_column('patient_medications', sa.Column('source_segment_id', sa.String(), nullable=True))
    op.add_column('patient_medications', sa.Column('stop_date_basis', sa.String(), nullable=True))
    op.create_index(op.f('ix_patient_medications_source_document_id'), 'patient_medications', ['source_document_id'], unique=False)
    op.create_foreign_key(
        'patient_medications_source_document_id_fkey',
        'patient_medications', 'documents', ['source_document_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('source_evidence', sa.Column('medication_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_source_evidence_medication_id'), 'source_evidence', ['medication_id'], unique=False)
    op.create_foreign_key(
        'source_evidence_medication_id_fkey',
        'source_evidence', 'patient_medications', ['medication_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('source_evidence_medication_id_fkey', 'source_evidence', type_='foreignkey')
    op.drop_index(op.f('ix_source_evidence_medication_id'), table_name='source_evidence')
    op.drop_column('source_evidence', 'medication_id')

    op.drop_constraint('patient_medications_source_document_id_fkey', 'patient_medications', type_='foreignkey')
    op.drop_index(op.f('ix_patient_medications_source_document_id'), table_name='patient_medications')
    op.drop_column('patient_medications', 'stop_date_basis')
    op.drop_column('patient_medications', 'source_segment_id')
    op.drop_column('patient_medications', 'source_document_id')
