"""change_active_nullable_and_default

Revision ID: 666003748d14
Revises: a5a40d843415
Create Date: 2022-02-24 16:35:34.228040

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = "666003748d14"
down_revision = "a5a40d843415"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    user_table = sa.sql.table("users", sa.sql.column("active", mysql.TINYINT(display_width=1)))
    op.execute(user_table.update().where(user_table.c.active == None).values(active=False))
    op.alter_column("users", "active", existing_type=mysql.TINYINT(display_width=1), nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("users", "active", existing_type=mysql.TINYINT(display_width=1), nullable=True)
    # ### end Alembic commands ###
