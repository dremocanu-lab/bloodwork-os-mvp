"""phase10 timeline projection

Revision ID: a1c9d4e7f203
Revises: ff84f15530a9
Create Date: 2026-09-16 09:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9d4e7f203'
down_revision: Union[str, Sequence[str], None] = 'ff84f15530a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clinical Document Intelligence V3, Phase 10: additive, nullable
    provenance columns on `patient_events` so a Timeline entry can be a
    real, idempotent PROJECTION of a canonical `PatientMedication` state
    change — see app/models.py's PatientEvent.source_document_id/
    source_medication_id docstring for why each ondelete rule differs,
    and app/services/clinical_document/timeline_projection.py for the
    projection logic itself. Both columns stay null for every existing
    and future manually-created event (POST /patient-events) — this is
    additive, not a behavior change to that route.

    Autogenerate also proposed dropping the same 8 harmless historical
    duplicate indexes documented in every prior Clinical Document
    Intelligence V3 migration (ix_eas_*/ix_eal_*/ix_ec_patient) —
    deliberately omitted here for the same reason as always: unrelated
    to Phase 10, not a side effect of these columns.
    """
    op.add_column('patient_events', sa.Column('source_document_id', sa.Integer(), nullable=True))
    op.add_column('patient_events', sa.Column('source_medication_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_patient_events_source_document_id'), 'patient_events', ['source_document_id'], unique=False)
    op.create_index(op.f('ix_patient_events_source_medication_id'), 'patient_events', ['source_medication_id'], unique=False)
    op.create_foreign_key(
        'patient_events_source_document_id_fkey',
        'patient_events', 'documents', ['source_document_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'patient_events_source_medication_id_fkey',
        'patient_events', 'patient_medications', ['source_medication_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('patient_events_source_medication_id_fkey', 'patient_events', type_='foreignkey')
    op.drop_constraint('patient_events_source_document_id_fkey', 'patient_events', type_='foreignkey')
    op.drop_index(op.f('ix_patient_events_source_medication_id'), table_name='patient_events')
    op.drop_index(op.f('ix_patient_events_source_document_id'), table_name='patient_events')
    op.drop_column('patient_events', 'source_medication_id')
    op.drop_column('patient_events', 'source_document_id')
