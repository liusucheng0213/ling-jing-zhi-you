"""为景点坐标增加来源、精度和核验状态。

Revision ID: 20260712_01
Revises: None
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spots", sa.Column("coordinate_system", sa.String(length=20), nullable=True))
    op.add_column("spots", sa.Column("coordinate_status", sa.String(length=20), nullable=True))
    op.add_column("spots", sa.Column("coordinate_source", sa.Text(), nullable=True))
    op.add_column("spots", sa.Column("coordinate_source_id", sa.String(length=100), nullable=True))
    op.add_column("spots", sa.Column("coordinate_accuracy_meters", sa.Float(), nullable=True))
    op.add_column("spots", sa.Column("coordinate_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("spots", sa.Column("source_latitude", sa.Float(), nullable=True))
    op.add_column("spots", sa.Column("source_longitude", sa.Float(), nullable=True))
    op.add_column("spots", sa.Column("source_coordinate_system", sa.String(length=20), nullable=True))

    op.execute("UPDATE spots SET coordinate_system = 'WGS84' WHERE coordinate_system IS NULL")
    op.execute("UPDATE spots SET coordinate_status = 'estimated' WHERE coordinate_status IS NULL")


def downgrade() -> None:
    op.drop_column("spots", "source_coordinate_system")
    op.drop_column("spots", "source_longitude")
    op.drop_column("spots", "source_latitude")
    op.drop_column("spots", "coordinate_verified_at")
    op.drop_column("spots", "coordinate_accuracy_meters")
    op.drop_column("spots", "coordinate_source_id")
    op.drop_column("spots", "coordinate_source")
    op.drop_column("spots", "coordinate_status")
    op.drop_column("spots", "coordinate_system")
