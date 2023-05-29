"""total_number_of_projects_added

Revision ID: 6b6e42ec28c0
Revises: b976f6cda95c
Create Date: 2023-05-29 08:50:56.171867

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "6b6e42ec28c0"
down_revision = "b976f6cda95c"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("reporting", sa.Column("total_projects_count", sa.Integer(), nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("reporting", "total_projects_count")
    # ### end Alembic commands ###