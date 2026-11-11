import hashlib
import re
from io import BytesIO

import pandas as pd
import streamlit as st

from crm_app.ai import classify_intent, generate_business_answer, generate_sql, get_genai_client
from crm_app.config import get_settings
from crm_app.database import (
    build_context,
    create_mysql_database,
    create_uploaded_dataset,
    execute_select,
    get_mysql_connection,
    import_sql_dump_to_mysql,
    make_import_database_name,
    mysql_error_message,
    verify_mysql_connection,
)
from crm_app.visuals import auto_visualize

st.set_page_config(page_title="CRM AI Assistant", page_icon="📊", layout="wide")

settings = get_settings()
client = get_genai_client(settings["GEMINI_API_KEY"])


def initialize_state():
    defaults = {
        "messages": [],
        "chat_history": [],
        "uploaded_datasets": {},
        "imported_databases": {},
        "active_source": None,
        "mysql_connection": None,
        "mysql_connection_error": "",
        "mysql_configured": False,
        "mysql_databases": [],
        "mysql_env_attempted": False,
        "mysql_public_settings": None,
        "database_schema": "",
        "generated_sql": None,
        "query_results": None,
        "processed_uploads": set(),
        "pending_sql_dump": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def refresh_mysql_databases(connection):
    cursor = connection.cursor()
    cursor.execute("SHOW DATABASES")
    st.session_state.mysql_databases = [
        next(iter(row.values())) for row in cursor.fetchall()
    ]


def try_mysql_connection(mysql_settings):
    connection = get_mysql_connection(mysql_settings)
    verify_mysql_connection(connection)
    st.session_state.mysql_connection = connection
    st.session_state.mysql_connection_error = ""
    st.session_state.mysql_configured = True
    st.session_state.mysql_public_settings = {
        key: mysql_settings[key]
        for key in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DATABASE")
    }
    refresh_mysql_databases(connection)


def initialize_mysql_from_env():
    if st.session_state.mysql_env_attempted:
        return
    st.session_state.mysql_env_attempted = True
    if not settings["MYSQL_CONFIGURED"]:
        st.session_state.mysql_connection_error = (
            "MySQL is not configured in .env. Set MYSQL_HOST, MYSQL_USER, and "
            "MYSQL_DATABASE, or enter connection details below."
        )
        return
    try:
        try_mysql_connection(settings)
    except Exception as exc:
        st.session_state.mysql_connection_error = mysql_error_message(exc)


def close_connection(connection):
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


initialize_state()
initialize_mysql_from_env()
if st.session_state.mysql_public_settings:
    settings.update(st.session_state.mysql_public_settings)


def current_mysql_connection():
    connection = st.session_state.mysql_connection
    if connection is None:
        return None
    try:
        verify_mysql_connection(connection)
        return connection
    except Exception:
        close_connection(connection)
        st.session_state.mysql_connection = None
        st.session_state.mysql_configured = False
        st.session_state.mysql_connection_error = (
            "The saved MySQL connection expired. Test the connection again."
        )
        return None


mysql_conn = current_mysql_connection()


def get_sources():
    sources = []
    if mysql_conn is not None:
        for db_name in st.session_state.mysql_databases:
            if db_name == settings["MYSQL_DATABASE"]:
                sources.append(
                    {
                        "key": f"mysql::{db_name}",
                        "label": f"CRM MySQL: {db_name}",
                        "kind": "mysql",
                        "database": db_name,
                    }
                )
        for db_name, metadata in st.session_state.imported_databases.items():
            if db_name in st.session_state.mysql_databases:
                sources.append(
                    {
                        "key": f"mysql::{db_name}",
                        "label": f"Imported SQL: {metadata['filename']} ({db_name})",
                        "kind": "mysql",
                        "database": db_name,
                    }
                )
        known_imports = set(st.session_state.imported_databases)
        for db_name in st.session_state.mysql_databases:
            if db_name.startswith("crm_import_") and db_name not in known_imports:
                sources.append(
                    {
                        "key": f"mysql::{db_name}",
                        "label": f"Imported SQL: {db_name}",
                        "kind": "mysql",
                        "database": db_name,
                    }
                )
    for key, record in st.session_state.uploaded_datasets.items():
        sources.append(
            {
                "key": f"uploaded::{key}",
                "label": f"{record['file_type']}: {record['filename']}",
                "kind": "sqlite",
                "database": record["table_name"],
                "connection": record["connection"],
            }
        )
    return sources


sources = get_sources()
source_by_key = {source["key"]: source for source in sources}
if st.session_state.active_source not in source_by_key:
    st.session_state.active_source = sources[0]["key"] if sources else None

st.title("CRM AI Assistant")
st.caption(
    "Ask questions about your CRM data and instantly get answers, insights and interactive visualizations."
)

with st.sidebar:
    st.title("CRM AI Assistant")

    st.subheader("MySQL Connection")
    if mysql_conn is not None:
        st.success("Connected to MySQL server")
        db_exists = settings["MYSQL_DATABASE"] in st.session_state.mysql_databases
        if db_exists:
            st.caption(f"Configured database: {settings['MYSQL_DATABASE']} (available)")
        else:
            st.warning(
                f"Server connected, but database '{settings['MYSQL_DATABASE']}' does not exist."
            )
    else:
        st.error("MySQL not connected")
        if st.session_state.mysql_connection_error:
            st.caption(st.session_state.mysql_connection_error)

    with st.expander("Configure / test MySQL connection", expanded=mysql_conn is None):
        with st.form("mysql_connection_form"):
            mysql_host = st.text_input("Host", value=settings["MYSQL_HOST"])
            mysql_port = st.number_input(
                "Port", min_value=1, max_value=65535, value=settings["MYSQL_PORT"], step=1
            )
            mysql_user = st.text_input("Username", value=settings["MYSQL_USER"])
            mysql_password = st.text_input(
                "Password", value=settings["MYSQL_PASSWORD"], type="password"
            )
            mysql_database = st.text_input(
                "CRM database name", value=settings["MYSQL_DATABASE"]
            )
            connect_clicked = st.form_submit_button("Test Connection")
        if connect_clicked:
            candidate_settings = {
                "MYSQL_HOST": mysql_host.strip(),
                "MYSQL_PORT": int(mysql_port),
                "MYSQL_USER": mysql_user.strip(),
                "MYSQL_PASSWORD": mysql_password,
                "MYSQL_DATABASE": mysql_database.strip(),
            }
            if not candidate_settings["MYSQL_HOST"] or not candidate_settings["MYSQL_USER"]:
                st.error("Host and username are required.")
            else:
                try:
                    old_connection = st.session_state.mysql_connection
                    try_mysql_connection(candidate_settings)
                    if old_connection is not st.session_state.mysql_connection:
                        close_connection(old_connection)
                    settings.update(
                        {
                            key: candidate_settings[key]
                            for key in (
                                "MYSQL_HOST",
                                "MYSQL_PORT",
                                "MYSQL_USER",
                                "MYSQL_DATABASE",
                            )
                        }
                    )
                    settings["MYSQL_CONFIGURED"] = True
                    st.success("MySQL server connection verified.")
                    st.rerun()
                except Exception as exc:
                    st.session_state.mysql_connection_error = mysql_error_message(exc)
                    st.error(st.session_state.mysql_connection_error)

    if mysql_conn is not None and settings["MYSQL_DATABASE"] not in st.session_state.mysql_databases:
        with st.form("create_crm_database_form"):
            confirm_create_crm = st.checkbox(
                f"I confirm creating the database '{settings['MYSQL_DATABASE']}'."
            )
            create_crm_clicked = st.form_submit_button("Create configured database")
        if create_crm_clicked:
            if not confirm_create_crm:
                st.error("Confirm database creation before proceeding.")
            else:
                try:
                    create_mysql_database(mysql_conn, settings["MYSQL_DATABASE"])
                    refresh_mysql_databases(mysql_conn)
                    st.success(f"Database '{settings['MYSQL_DATABASE']}' created.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not create database: {exc}")

    st.subheader("Active Data Source")
    sources = get_sources()
    source_by_key = {source["key"]: source for source in sources}
    if sources:
        labels = {source["label"]: source["key"] for source in sources}
        current_label = next(
            (
                source["label"]
                for source in sources
                if source["key"] == st.session_state.active_source
            ),
            sources[0]["label"],
        )
        selected_label = st.selectbox(
            "Choose a database or uploaded dataset",
            list(labels),
            index=list(labels).index(current_label),
        )
        st.session_state.active_source = labels[selected_label]
        st.info(f"Using: {selected_label}")
    else:
        st.info("Upload CSV/Excel now, or connect to MySQL to use a database.")

    st.subheader("Upload Data")
    uploaded_files = st.file_uploader(
        "Upload CSV, Excel, or SQL dump",
        type=["csv", "xlsx", "xls", "sql"],
        accept_multiple_files=True,
    )
    if uploaded_files:
        for uploaded in uploaded_files:
            content = uploaded.getvalue()
            upload_id = hashlib.sha256(content).hexdigest()
            if upload_id in st.session_state.processed_uploads:
                continue
            extension = uploaded.name.rsplit(".", 1)[-1].lower()
            try:
                if extension in {"csv", "xlsx", "xls"}:
                    if extension == "csv":
                        dataframe = pd.read_csv(BytesIO(content))
                    else:
                        dataframe = pd.read_excel(BytesIO(content))
                    key = upload_id[:16]
                    table_name = re.sub(
                        r"[^A-Za-z0-9_]", "_", uploaded.name.rsplit(".", 1)[0]
                    ).strip("_")
                    table_name = (table_name or "uploaded_data")[:60]
                    dataset = create_uploaded_dataset(table_name, dataframe)
                    dataset.update(
                        {
                            "filename": uploaded.name,
                            "file_type": "CSV" if extension == "csv" else "Excel",
                            "upload_id": upload_id,
                        }
                    )
                    st.session_state.uploaded_datasets[key] = dataset
                    st.session_state.active_source = f"uploaded::{key}"
                    st.session_state.processed_uploads.add(upload_id)
                    st.success(
                        f"Loaded {uploaded.name}: {len(dataframe)} rows × {len(dataframe.columns)} columns."
                    )
                elif extension == "sql":
                    st.session_state.pending_sql_dump = {
                        "filename": uploaded.name,
                        "content": content,
                        "upload_id": upload_id,
                    }
                    st.session_state.processed_uploads.add(upload_id)
            except Exception as exc:
                st.error(f"Could not read {uploaded.name}: {exc}")
                st.session_state.processed_uploads.add(upload_id)

    sources = get_sources()
    source_by_key = {source["key"]: source for source in sources}
    if st.session_state.active_source not in source_by_key:
        st.session_state.active_source = sources[0]["key"] if sources else None

    pending_dump = st.session_state.pending_sql_dump
    if pending_dump:
        st.markdown("**SQL dump preview**")
        st.write(f"File: `{pending_dump['filename']}`")
        st.write(f"Size: {len(pending_dump['content']):,} bytes")
        if mysql_conn is None:
            st.warning(
                "SQL dumps require a reachable MySQL server. Configure and test a connection above. "
                "CSV and Excel uploads can be analyzed without MySQL."
            )
        else:
            with st.form("sql_import_form"):
                confirmed_import = st.checkbox(
                    "I confirm importing this dump into a new, isolated database. "
                    "The configured CRM database will not be overwritten."
                )
                import_clicked = st.form_submit_button("Import SQL dump")
            if import_clicked:
                if not confirmed_import:
                    st.error("Confirm the isolated import before continuing.")
                else:
                    import_db = make_import_database_name(pending_dump["filename"])
                    try:
                        create_mysql_database(mysql_conn, import_db)
                        mysql_conn.select_db(import_db)
                        statements_tables = import_sql_dump_to_mysql(
                            mysql_conn,
                            pending_dump["content"].decode("utf-8-sig"),
                        )
                        st.session_state.imported_databases[import_db] = {
                            "filename": pending_dump["filename"],
                            "tables": statements_tables,
                        }
                        refresh_mysql_databases(mysql_conn)
                        st.session_state.active_source = f"mysql::{import_db}"
                        st.session_state.pending_sql_dump = None
                        st.session_state.database_schema = build_context(
                            mysql_conn, "mysql", import_db
                        )
                        st.success(
                            f"Imported into isolated database '{import_db}'. "
                            f"Tables: {', '.join(statements_tables)}"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(
                            f"SQL import failed in isolated database '{import_db}': {exc}. "
                            "The CRM database was not changed; the new import database may be incomplete."
                        )

    st.subheader("Dataset Preview")
    active_key = st.session_state.active_source or ""
    if active_key.startswith("uploaded::"):
        dataset_key = active_key.split("::", 1)[1]
        dataset = st.session_state.uploaded_datasets.get(dataset_key)
        if dataset:
            df = dataset["df"]
            st.caption(
                f"{dataset['filename']} · {len(df)} rows · {len(df.columns)} columns"
            )
            st.caption("Columns: " + ", ".join(map(str, df.columns)))
            st.dataframe(df.head(10), use_container_width=True)
            if st.button("Remove active dataset"):
                close_connection(dataset["connection"])
                del st.session_state.uploaded_datasets[dataset_key]
                st.session_state.active_source = None
                st.rerun()

    st.subheader("Database Overview")
    active_source = source_by_key.get(st.session_state.active_source)
    if active_source and active_source["kind"] == "mysql" and mysql_conn:
        try:
            mysql_conn.select_db(active_source["database"])
            st.session_state.database_schema = build_context(
                mysql_conn, "mysql", active_source["database"]
            )
            st.code(st.session_state.database_schema[:5000], language="text")
        except Exception as exc:
            st.error(f"Could not refresh the database schema: {exc}")
    elif active_source and active_source["kind"] == "sqlite":
        st.session_state.database_schema = build_context(
            active_source["connection"], "sqlite", active_source["database"]
        )
        st.code(st.session_state.database_schema[:5000], language="text")

    st.subheader("Chat History")
    for history_item in reversed(st.session_state.chat_history[-10:]):
        st.caption(history_item["question"])
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.session_state.chat_history = []
        st.session_state.generated_sql = None
        st.session_state.query_results = None
        st.rerun()

if not sources:
    st.info(
        "Upload a CSV or Excel file to start analyzing data immediately. "
        "A MySQL server is only required for CRM databases and SQL dumps."
    )

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("table") is not None:
            st.dataframe(message["table"], use_container_width=True)
        if message.get("chart") is not None:
            st.plotly_chart(message["chart"], use_container_width=True)
        if message.get("sql"):
            with st.expander("View Generated SQL"):
                st.code(message["sql"], language="sql")

user_input = st.chat_input(
    "Ask a question about your selected data source", disabled=not bool(sources)
)
if user_input:
    source = source_by_key.get(st.session_state.active_source)
    if source is None:
        st.error("Select an active data source before asking a question.")
        st.stop()
    if source["kind"] == "mysql":
        connection = current_mysql_connection()
        if connection is None:
            st.error("The MySQL connection is no longer available. Reconnect and try again.")
            st.stop()
        connection.select_db(source["database"])
    else:
        connection = source["connection"]

    source_type = source["kind"]
    schema_context = build_context(connection, source_type, source["database"])
    st.session_state.database_schema = schema_context
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            intent = classify_intent(user_input, client)
            if intent == "NO":
                answer = (
                    "I can help analyze CRM data using read-only queries. Ask about "
                    "customers, orders, products, sales, leads, or your uploaded dataset."
                )
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            else:
                generated_sql = generate_sql(
                    user_input, schema_context, client, source_type=source_type
                )
                st.session_state.generated_sql = generated_sql
                st.session_state.chat_history.append(
                    {"question": user_input, "sql": generated_sql, "source": source["label"]}
                )
                with st.expander("View Generated SQL"):
                    st.code(generated_sql, language="sql")

                result_df = execute_select(connection, generated_sql, source_type=source_type)
                st.session_state.query_results = result_df
                answer = generate_business_answer(result_df, user_input)
                st.markdown(answer)
                if not result_df.empty:
                    st.dataframe(result_df.head(50), use_container_width=True)
                    chart = auto_visualize(result_df, user_input)
                    if chart is not None:
                        st.plotly_chart(chart, use_container_width=True)
                else:
                    chart = None
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "table": result_df.head(50) if not result_df.empty else result_df,
                        "chart": chart,
                        "sql": generated_sql,
                    }
                )
        except Exception as exc:
            error_message = f"I couldn't answer that request safely: {exc}"
            st.error(error_message)
            st.session_state.messages.append(
                {"role": "assistant", "content": error_message}
            )
