"""normalize suppression keys

Revision ID: 20260315_0006
Revises: 20260227_0005
Create Date: 2026-03-15 00:06:00
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260315_0006"
down_revision = "20260227_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE suppression_normalized_tmp AS
        WITH normalized AS (
            SELECT
                id,
                created_at,
                lower(btrim(email_or_domain)) AS raw_value,
                coalesce(nullif(lower(btrim(reason)), ''), 'manual') AS normalized_reason
            FROM suppression
            WHERE email_or_domain IS NOT NULL
              AND btrim(email_or_domain) <> ''
        ),
        canonicalized AS (
            SELECT
                id,
                created_at,
                normalized_reason,
                raw_value,
                CASE
                    WHEN position('@' IN raw_value) > 0 THEN raw_value
                    ELSE nullif(
                        split_part(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(raw_value, '^[a-z][a-z0-9+.-]*://', '', 'i'),
                                    '^/*',
                                    ''
                                ),
                                '[/?#].*$',
                                ''
                            ),
                            ':',
                            1
                        ),
                        ''
                    )
                END AS canonical_value
            FROM normalized
        ),
        ranked AS (
            SELECT
                id,
                created_at,
                normalized_reason,
                coalesce(canonical_value, raw_value) AS key_value,
                row_number() OVER (
                    PARTITION BY coalesce(canonical_value, raw_value)
                    ORDER BY created_at ASC NULLS FIRST, id ASC
                ) AS row_num
            FROM canonicalized
            WHERE coalesce(canonical_value, raw_value) <> ''
        )
        SELECT id, key_value AS email_or_domain, normalized_reason AS reason, created_at
        FROM ranked
        WHERE row_num = 1
        """
    )
    op.execute("DELETE FROM suppression")
    op.execute(
        """
        INSERT INTO suppression (id, email_or_domain, reason, created_at)
        SELECT id, email_or_domain, reason, created_at
        FROM suppression_normalized_tmp
        ORDER BY created_at ASC NULLS FIRST, id ASC
        """
    )
    op.execute("DROP TABLE suppression_normalized_tmp")


def downgrade() -> None:
    # Data normalization/backfill is irreversible.
    pass

