"""
Add an is_sandbox_token boolean field to the Device table.

Revision ID: 246a7af2a944
Revises: 377d7daad8e1
Create Date: 2022-08-29 21:14:05.998325

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "246a7af2a944"
down_revision = "377d7daad8e1"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("device", sa.Column("is_sandbox_token", sa.Boolean(), nullable=True))
    op.execute("UPDATE device SET is_sandbox_token=True")
    with op.batch_alter_table("device") as batch_op:
        batch_op.alter_column("is_sandbox_token", nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("device", "is_sandbox_token")
    # ### end Alembic commands ###
