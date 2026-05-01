"""
Auto-migration helper — keeps DB schema in sync with SQLAlchemy models on boot.

Why this exists:
  SQLAlchemy's db.create_all() only creates MISSING tables. It does NOT
  ALTER existing tables. So when a new column is added to a model and
  deployed, the DB is missing that column and the app crashes at the first
  query (e.g. psycopg2.errors.UndefinedColumn: users.password_hash).

What it does:
  Iterates every table declared in db.metadata; for each model column that
  is missing in the DB, runs:
      ALTER TABLE "<t>" ADD COLUMN IF NOT EXISTS "<c>" <type>
  It is additive only — never drops columns, never changes types, never
  touches constraints. Existing rows are preserved.

Usage:
  After db.create_all(), call auto_migrate(db) once on startup.
"""
from sqlalchemy import inspect, text


def auto_migrate(db):
    """Add columns declared on models that are missing from the DB."""
    engine = db.engine
    inspector = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table_name, table in db.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue  # brand-new table — create_all will handle it
            existing = {c['name'] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                ddl = (
                    f'ALTER TABLE "{table_name}" '
                    f'ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                )
                try:
                    conn.execute(text(ddl))
                    added.append(f'{table_name}.{col.name}')
                    print(f'[AUTO-MIGRATE] Added: {table_name}.{col.name} ({col_type})')
                except Exception as e:
                    print(f'[AUTO-MIGRATE] FAILED {table_name}.{col.name}: {e}')
    if added:
        print(f'[AUTO-MIGRATE] {len(added)} column(s) added this boot.')
    else:
        print('[AUTO-MIGRATE] No schema changes needed.')
    return added

