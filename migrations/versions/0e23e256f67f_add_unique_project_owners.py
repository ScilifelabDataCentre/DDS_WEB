"""add_unique_project_owners

Revision ID: 0e23e256f67f
Revises: 399801a80e7a
Create Date: 2023-05-29 10:17:54.309735

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '0e23e256f67f'
down_revision = '399801a80e7a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('reporting', sa.Column('project_owner_unique_count', sa.Integer(), nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('reporting', 'project_owner_unique_count')
    # ### end Alembic commands ###
