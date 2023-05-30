"""change_researchuser_count_column

Revision ID: 399801a80e7a
Revises: e07c83ed0bda
Create Date: 2023-05-29 09:37:31.007336

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "399801a80e7a"
down_revision = "edde808b4556"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        table_name="reporting",
        column_name="researchuser_count",
        nullable=False,
        new_column_name="researcher_count",
        type_=sa.Integer(),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        table_name="reporting",
        column_name="researcher_count",
        nullable=False,
        new_column_name="researchuser_count",
        type_=sa.Integer(),
    )
    # ### end Alembic commands ###
