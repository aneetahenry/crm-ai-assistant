import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import pymysql
import sqlparse
from sqlparse import tokens as sql_tokens

FORBIDDEN_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
    "LOAD",
    "ATTACH",
    "DETACH",
    "MERGE",
    "EXEC",
    "CALL",
    "WRITE",
)


def get_mysql_connection(settings: Dict[str, Any], database: str = None):
    """Connect to MySQL and propagate connection errors for actionable reporting."""
    return pymysql.connect(
        host=settings.get("MYSQL_HOST", "localhost"),
        port=int(settings.get("MYSQL_PORT", 3306)),
        user=settings.get("MYSQL_USER", "root"),
        password=settings.get("MYSQL_PASSWORD", ""),
        database=database,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def verify_mysql_connection(connection) -> None:
    connection.ping(reconnect=False)


def mysql_database_exists(connection, database_name: str) -> bool:
    cursor = connection.cursor()
    cursor.execute("SHOW DATABASES")
    return database_name in {next(iter(row.values())) for row in cursor.fetchall()}


def create_mysql_database(connection, database_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database_name):
        raise ValueError("Database names may contain only letters, numbers, and underscores.")
    cursor = connection.cursor()
    cursor.execute(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4")


def mysql_error_message(error: Exception) -> str:
    error_code = error.args[0] if getattr(error, "args", None) else None
    if error_code == 1045:
        return "MySQL rejected the username or password (access denied)."
    if error_code == 1049:
        return "The MySQL server is reachable, but the configured database does not exist."
    if error_code in (2003, 2006, 2013):
        return "Could not reach the MySQL server. Check that MySQL is running and the host/port are correct."
    return f"MySQL connection failed: {error}"


def get_sqlite_connection(db_path: str = ":memory:"):
    return sqlite3.connect(db_path)


def get_mysql_schema(connection, db_name: str) -> str:
    query = """
        SELECT table_name AS table_name, column_name AS column_name,
               data_type AS data_type, is_nullable AS is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
    """
    cursor = connection.cursor()
    cursor.execute(query, (db_name,))
    rows = cursor.fetchall()

    schema = ""
    current_table = None
    for row in rows:
        table_name = row["table_name"]
        if current_table != table_name:
            schema += f"\n\nTABLE: {table_name}\n"
            current_table = table_name
        schema += (
            f"   {row['column_name']} ({row['data_type']}) "
            f"NULLABLE={row['is_nullable']}\n"
        )
    return schema.strip()


def get_mysql_relationships(connection, db_name: str) -> str:
    query = """
        SELECT
            table_name AS child_table,
            column_name AS child_column,
            referenced_table_name AS parent_table,
            referenced_column_name AS parent_column
        FROM information_schema.key_column_usage
        WHERE table_schema = %s
          AND referenced_table_name IS NOT NULL
        ORDER BY table_name, ordinal_position
    """
    cursor = connection.cursor()
    cursor.execute(query, (db_name,))
    rows = cursor.fetchall()
    relationships = []
    for row in rows:
        relationships.append(
            f"{row['child_table']}.{row['child_column']} -> "
            f"{row['parent_table']}.{row['parent_column']}"
        )
    return "\n".join(relationships) if relationships else "No explicit foreign-key relationships detected."


def get_sqlite_schema(connection) -> str:
    cursor = connection.cursor()
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    schema = ""
    for (table_name,) in tables:
        schema += f"\n\nTABLE: {table_name}\n"
        columns = cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        for c in columns:
            _, name, dtype, notnull, _, _ = c
            schema += f"   {name} ({dtype or 'TEXT'}) NULLABLE={not notnull}\n"
    return schema.strip() or "No tables detected in the active uploaded dataset."


def get_sqlite_relationships(connection) -> str:
    cursor = connection.cursor()
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    relationships = []
    for (table_name,) in tables:
        columns = cursor.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
        for fk in columns:
            _, _, table, from_col, to_col, _, _, _ = fk
            relationships.append(f"{table_name}.{from_col} -> {table}.{to_col}")
    return "\n".join(relationships) if relationships else "No explicit foreign-key relationships detected."


def build_context(connection, source_type: str = "mysql", db_name: str = "crm_ai") -> str:
    if source_type == "mysql":
        schema = get_mysql_schema(connection, db_name)
        relationships = get_mysql_relationships(connection, db_name)
    else:
        schema = get_sqlite_schema(connection)
        relationships = get_sqlite_relationships(connection)

    return (
        "DATABASE SCHEMA\n"
        f"{schema}\n\n"
        "FOREIGN KEY RELATIONSHIPS\n"
        f"{relationships}\n"
    )


def validate_sql(sql: str) -> str:
    if not sql or not sql.strip():
        raise ValueError("No SQL found in the generated query.")
    if "/*!" in sql:
        raise ValueError("MySQL executable comments are not allowed in chatbot queries.")

    statements = sqlparse.split(sql)
    if len(statements) != 1:
        raise ValueError("Only a single SQL statement is allowed.")

    normalized = statements[0].strip()
    if not normalized:
        raise ValueError("No SQL found in the generated query.")

    parsed = sqlparse.parse(normalized)[0]
    statement_type = parsed.get_type().upper()
    if statement_type != "SELECT":
        raise ValueError("Only SELECT statements are allowed in the CRM chatbot.")

    forbidden = set(FORBIDDEN_SQL_KEYWORDS) | {
        "INTO",
        "OUTFILE",
        "DUMPFILE",
        "PROCEDURE",
    }
    for token in parsed.flatten():
        if token.ttype in sql_tokens.Comment:
            continue
        if token.ttype in sql_tokens.Keyword:
            keyword = token.value.upper()
            words = set(re.findall(r"[A-Z_]+", keyword))
            blocked = words & forbidden
            if blocked:
                raise ValueError(f"Unsafe SQL keyword detected: {sorted(blocked)[0]}")

    if re.search(r"\bFOR\s+UPDATE\b|\bLOCK\s+IN\s+SHARE\s+MODE\b", sql, re.IGNORECASE):
        raise ValueError("Locking clauses are not allowed in read-only chatbot queries.")

    if normalized.rstrip().endswith(";"):
        normalized = normalized.rstrip()[:-1].strip()

    return normalized


def execute_select(connection, sql: str, source_type: str = "mysql") -> pd.DataFrame:
    cleaned_sql = validate_sql(sql)
    if source_type == "mysql":
        cursor = connection.cursor(pymysql.cursors.DictCursor)
    else:
        cursor = connection.cursor()

    cursor.execute(cleaned_sql)
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame()
    if source_type == "mysql":
        return pd.DataFrame(rows)
    columns = [column[0] for column in cursor.description]
    return pd.DataFrame(rows, columns=columns)


def dataset_summary(df: pd.DataFrame) -> str:
    return f"Rows: {len(df)} | Columns: {len(df.columns)} | Columns: {', '.join(df.columns.astype(str).tolist())}"


def load_uploaded_dataframe(file_obj) -> pd.DataFrame:
    name = file_obj.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file_obj)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_obj)
    raise ValueError("Unsupported file type. Please upload a CSV or Excel file.")


def import_sql_dump_to_mysql(connection, sql_dump_text: str) -> List[str]:
    """Import a checked schema/data dump into the already-selected isolated database."""
    statements = [statement.strip() for statement in sqlparse.split(sql_dump_text) if statement.strip()]
    if not statements:
        raise ValueError("The uploaded SQL file contains no SQL statements.")

    allowed_starts = ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX", "INSERT", "ALTER TABLE")
    ignorable_starts = ("CREATE DATABASE", "USE", "SET", "LOCK TABLES", "UNLOCK TABLES")
    cursor = connection.cursor()
    executed = 0
    for statement in statements:
        cleaned = sqlparse.format(statement, strip_comments=True).strip().rstrip(";").strip()
        if not cleaned:
            continue
        upper = cleaned.upper()
        if upper.startswith(ignorable_starts):
            continue
        if upper.startswith("DROP TABLE IF EXISTS"):
            # The destination is a new isolated database; the dump's reset preamble is unnecessary.
            continue
        if not upper.startswith(allowed_starts):
            raise ValueError(
                "SQL import stopped: only CREATE TABLE/INDEX, INSERT, ALTER TABLE, "
                "and standard database/foreign-key setup statements are supported."
            )
        if re.search(
            r"\b(?:LOAD_FILE|SLEEP|BENCHMARK|OUTFILE|DUMPFILE|PROCEDURE|FUNCTION|TRIGGER|EVENT)\b",
            cleaned,
            re.IGNORECASE,
        ):
            raise ValueError("SQL import contains a disallowed file, routine, or execution operation.")
        executable_text = "".join(
            token.value
            for token in sqlparse.parse(cleaned)[0].flatten()
            if token.ttype not in sql_tokens.Literal.String
            and token.ttype not in sql_tokens.Comment
        )
        if re.search(
            r"(?:`[^`]+`|[A-Za-z0-9_]+)\s*\.\s*(?:`[^`]+`|[A-Za-z0-9_]+)",
            executable_text,
        ):
            raise ValueError("Qualified cross-database table names are not allowed in SQL imports.")
        cursor.execute(cleaned)
        executed += 1

    if not executed:
        raise ValueError("The SQL file did not contain any supported table or data statements.")
    cursor.execute("SHOW TABLES")
    return [next(iter(row.values())) for row in cursor.fetchall()]


def make_import_database_name(filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", filename.rsplit(".", 1)[0]).strip("_").lower()
    base = (base or "dataset")[:32]
    return f"crm_import_{base}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def create_uploaded_dataset(name: str, dataframe: pd.DataFrame) -> Dict[str, Any]:
    sqlite_conn = sqlite3.connect(":memory:")
    dataframe.to_sql(name, sqlite_conn, index=False, if_exists="replace")
    return {
        "name": name,
        "kind": "sqlite",
        "connection": sqlite_conn,
        "df": dataframe,
    }


def list_tables_from_connection(connection, source_type: str) -> List[str]:
    if source_type == "mysql":
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES")
        return [row[0] for row in cursor.fetchall()]
    cursor = connection.cursor()
    return [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def get_column_overview(connection, source_type: str) -> Dict[str, List[str]]:
    if source_type == "mysql":
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        overview = {}
        for table in tables:
            cursor.execute(f"SHOW COLUMNS FROM `{table}`")
            overview[table] = [row[1] for row in cursor.fetchall()]
        return overview

    cursor = connection.cursor()
    overview = {}
    tables = [
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    for table in tables:
        cols = cursor.execute(f'PRAGMA table_info("{table}")').fetchall()
        overview[table] = [col[1] for col in cols]
    return overview
