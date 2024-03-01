"""
Data migration to initialize the tiles and tile counts needed.

Revision ID: b3069b0347d5
Revises: 3ea1bfba1ae7
Create Date: 2020-06-14 18:40:13.666551

"""

from collections import defaultdict

from alembic import op
from slobsterble.constants import (
    CLASSIC_DISTRIBUTION,
    CLASSIC_LETTER_MULTIPLIERS,
    CLASSIC_WORD_MULTIPLIERS,
)
from slobsterble.models import (
    BoardLayout,
    Distribution,
    Modifier,
    PositionedModifier,
    Tile,
    TileCount,
)
from sqlalchemy import orm

# revision identifiers, used by Alembic.
revision = "b3069b0347d5"
down_revision = "3ea1bfba1ae7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    session = orm.Session(bind=bind)

    distribution = Distribution(name="Classic", creator_id=None)
    for tile_tuple, count in CLASSIC_DISTRIBUTION.items():
        letter = tile_tuple[0]
        value = tile_tuple[1]
        is_blank = letter is None
        tile = Tile(letter=letter, is_blank=is_blank, value=value)
        session.add(tile)
        for frequency in range(1, count + 1):
            tile_count = TileCount(tile=tile, count=frequency)
            session.add(tile_count)
            if frequency == count:
                distribution.tile_distribution.append(tile_count)

    for offset in range(26):
        letter = chr(ord("A") + offset)
        tile = Tile(letter=letter, is_blank=True, value=0)
        session.add(tile)
    session.commit()

    session.add(distribution)

    classic_rows = len(CLASSIC_LETTER_MULTIPLIERS)
    classic_columns = len(CLASSIC_LETTER_MULTIPLIERS[0])
    assert classic_rows == len(CLASSIC_WORD_MULTIPLIERS)
    assert classic_columns == len(CLASSIC_WORD_MULTIPLIERS[0])
    modifiers = defaultdict(dict)
    for row_index in range(classic_rows):
        for column_index in range(classic_columns):
            letter_multiplier = CLASSIC_LETTER_MULTIPLIERS[row_index][column_index]
            word_multiplier = CLASSIC_WORD_MULTIPLIERS[row_index][column_index]
            if letter_multiplier == 1 and word_multiplier == 1:
                continue
            if (
                letter_multiplier not in modifiers
                or word_multiplier not in modifiers[letter_multiplier]
            ):
                modifier = Modifier(
                    letter_multiplier=letter_multiplier, word_multiplier=word_multiplier
                )
                modifiers[letter_multiplier][word_multiplier] = modifier
                session.add(modifier)
    session.commit()
    board_layout = BoardLayout(
        name="Classic", creator_id=None, rows=classic_rows, columns=classic_columns
    )
    for row_index in range(classic_rows):
        for column_index in range(classic_columns):
            letter_multiplier = CLASSIC_LETTER_MULTIPLIERS[row_index][column_index]
            word_multiplier = CLASSIC_WORD_MULTIPLIERS[row_index][column_index]
            if letter_multiplier == 1 and word_multiplier == 1:
                continue
            modifier = (
                session.query(Modifier)
                .filter_by(
                    letter_multiplier=letter_multiplier, word_multiplier=word_multiplier
                )
                .first()
            )
            positioned_modifier = PositionedModifier(
                row=row_index, column=column_index, modifier_id=modifier.id
            )
            session.add(positioned_modifier)
            board_layout.modifiers.append(positioned_modifier)
    session.commit()
    session.add(board_layout)
    session.commit()
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
