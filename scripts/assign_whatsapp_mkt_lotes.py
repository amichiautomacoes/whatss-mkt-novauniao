import os

import _path  # noqa: F401
from dotenv import load_dotenv
import psycopg
from psycopg import sql


EXPECTED_TOTAL = 347
TABLE_NAME = "whatsapp_mkt"
LOT_COUNT = 5


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def pick_order_column(conn: psycopg.Connection, schema: str) -> str | None:
    preferred_columns = ("id", "created_at", "phone", "telefone", "nome", "name")
    with conn.cursor() as cur:
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = %s
              and table_name = %s
            """,
            (schema, TABLE_NAME),
        )
        columns = {row[0] for row in cur.fetchall()}

    for column in preferred_columns:
        if column in columns:
            return column

    return None


def resolve_schema(conn: psycopg.Connection, preferred_schema: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            select table_schema
            from information_schema.tables
            where table_name = %s
              and table_schema = %s
            """,
            (TABLE_NAME, preferred_schema),
        )
        if cur.fetchone():
            return preferred_schema

        cur.execute(
            """
            select table_schema
            from information_schema.tables
            where table_name = %s
            order by case when table_schema = 'public' then 0 else 1 end, table_schema
            """,
            (TABLE_NAME,),
        )
        schemas = [row[0] for row in cur.fetchall()]

    if len(schemas) == 1:
        return schemas[0]

    if not schemas:
        raise RuntimeError(f"Table {TABLE_NAME} was not found in any schema.")

    raise RuntimeError(
        f"Table {TABLE_NAME} exists in multiple schemas: {', '.join(schemas)}. "
        "Set SUPABASE_SCHEMA to the desired schema."
    )


def main() -> None:
    load_dotenv()
    database_url = get_required_env("SUPABASE_DATABASE_URL")
    preferred_schema = os.getenv("SUPABASE_SCHEMA", "public")

    with psycopg.connect(database_url) as conn:
        schema = resolve_schema(conn, preferred_schema)
        order_column = pick_order_column(conn, schema)
        order_expression = (
            sql.Identifier(order_column) if order_column else sql.SQL("ctid")
        )

        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("alter table {}.{} add column if not exists lote text").format(
                    sql.Identifier(schema),
                    sql.Identifier(TABLE_NAME),
                )
            )

            cur.execute(
                sql.SQL("select count(*) from {}.{}").format(
                    sql.Identifier(schema),
                    sql.Identifier(TABLE_NAME),
                )
            )
            total = cur.fetchone()[0]
            if total != EXPECTED_TOTAL:
                conn.rollback()
                raise RuntimeError(
                    f"Expected {EXPECTED_TOTAL} rows in {schema}.{TABLE_NAME}, found {total}. "
                    "No lote values were changed."
                )

            cur.execute(
                sql.SQL(
                    """
                    with numbered as (
                        select
                            ctid,
                            ntile({lot_count}) over (order by {order_expression}) as lot_number
                        from {schema}.{table}
                    ),
                    updated as (
                        update {schema}.{table} target
                        set lote = 'lote' || numbered.lot_number::text
                        from numbered
                        where target.ctid = numbered.ctid
                        returning target.lote
                    )
                    select lote, count(*)
                    from updated
                    group by lote
                    order by lote
                    """
                ).format(
                    lot_count=sql.Literal(LOT_COUNT),
                    order_expression=order_expression,
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(TABLE_NAME),
                )
            )
            distribution = cur.fetchall()
            conn.commit()

    print(f"Updated {EXPECTED_TOTAL} rows in {schema}.{TABLE_NAME}.")
    print(f"Order column: {order_column or 'ctid'}")
    for lote, count in distribution:
        print(f"{lote}: {count}")


if __name__ == "__main__":
    main()
