import unittest
from io import BytesIO
from unittest.mock import Mock

import pandas as pd

from crm_app.database import (
    build_context,
    create_uploaded_dataset,
    execute_select,
    get_mysql_relationships,
    import_sql_dump_to_mysql,
    load_uploaded_dataframe,
    mysql_database_exists,
    validate_sql,
)
from crm_app.visuals import auto_visualize


class NamedBytesIO(BytesIO):
    def __init__(self, content, name):
        super().__init__(content)
        self.name = name


class DatabaseWorkflowTests(unittest.TestCase):
    def test_select_validation_allows_queries_and_rejects_writes(self):
        self.assertEqual(validate_sql("SELECT name FROM customers;"), "SELECT name FROM customers")
        for unsafe in (
            "DELETE FROM customers",
            "WITH rows AS (SELECT 1) DELETE FROM customers",
            "SELECT 1; DROP TABLE customers",
            "SELECT name INTO OUTFILE 'export.txt' FROM customers",
            "SELECT 1 /*!50000 INTO OUTFILE '/tmp/result' */",
        ):
            with self.subTest(sql=unsafe), self.assertRaises(ValueError):
                validate_sql(unsafe)

    def test_csv_and_excel_can_be_loaded_without_mysql(self):
        csv_file = NamedBytesIO(b"city,sales\nKochi,10\nPune,20\n", "sales.csv")
        csv_frame = load_uploaded_dataframe(csv_file)
        self.assertEqual(csv_frame.shape, (2, 2))

        excel_buffer = BytesIO()
        pd.DataFrame({"city": ["Kochi"], "sales": [10]}).to_excel(
            excel_buffer, index=False
        )
        excel_file = NamedBytesIO(excel_buffer.getvalue(), "sales.xlsx")
        excel_frame = load_uploaded_dataframe(excel_file)
        self.assertEqual(excel_frame.shape, (1, 2))

    def test_uploaded_data_can_be_queried_and_visualized(self):
        frame = pd.DataFrame({"city": ["Kochi", "Pune"], "sales": [10, 20]})
        dataset = create_uploaded_dataset("sales_data", frame)
        try:
            context = build_context(dataset["connection"], "sqlite", "sales_data")
            self.assertIn("TABLE: sales_data", context)
            result = execute_select(
                dataset["connection"],
                "SELECT city, sales FROM sales_data ORDER BY sales",
                "sqlite",
            )
            self.assertEqual(len(result), 2)
            self.assertIsNotNone(auto_visualize(result, "sales by city"))
        finally:
            dataset["connection"].close()

    def test_database_existence_and_safe_dump_allowlist(self):
        connection = Mock()
        cursor = Mock()
        cursor.fetchall.side_effect = [
            [{"Database": "crm_ai"}, {"Database": "crm_import"}],
            [{"Tables_in_crm_import": "customers"}],
        ]
        connection.cursor.return_value = cursor
        self.assertTrue(mysql_database_exists(connection, "crm_import"))

        tables = import_sql_dump_to_mysql(
            connection,
            "CREATE DATABASE source_db; USE source_db; "
            "DROP TABLE IF EXISTS customers; "
            "CREATE TABLE customers (customer_id INT); "
            "INSERT INTO customers VALUES (1);",
        )
        self.assertEqual(tables, ["customers"])
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any(query.startswith("CREATE TABLE") for query in executed))
        self.assertTrue(any(query.startswith("INSERT") for query in executed))
        self.assertFalse(any(query.startswith("DROP") for query in executed))

        with self.assertRaises(ValueError):
            import_sql_dump_to_mysql(connection, "DROP DATABASE crm_ai;")
        with self.assertRaises(ValueError):
            import_sql_dump_to_mysql(
                connection,
                "CREATE TABLE leaked AS SELECT LOAD_FILE('/etc/passwd')",
            )

    def test_mysql_relationship_query_uses_portable_key_column_usage(self):
        connection = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = [
            {
                "child_table": "orders",
                "child_column": "customer_id",
                "parent_table": "customers",
                "parent_column": "customer_id",
            }
        ]
        connection.cursor.return_value = cursor

        relationships = get_mysql_relationships(connection, "crm_import_test")

        self.assertIn("orders.customer_id -> customers.customer_id", relationships)
        query = cursor.execute.call_args.args[0]
        self.assertIn("information_schema.key_column_usage", query)
        self.assertNotIn("constraint_column_usage", query)
        self.assertEqual(cursor.execute.call_args.args[1], ("crm_import_test",))

    def test_dump_import_allows_email_literals_and_blocks_qualified_table_names(self):
        connection = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = [{"Tables_in_crm_import": "customers"}]
        connection.cursor.return_value = cursor

        sql_dump = """
            CREATE TABLE customers (customer_id INT, email VARCHAR(100));
            INSERT INTO customers VALUES (1, 'person@example.com');
        """
        tables = import_sql_dump_to_mysql(connection, sql_dump)
        self.assertEqual(tables, ["customers"])
        self.assertEqual(cursor.execute.call_count, 3)

        with self.assertRaisesRegex(ValueError, "Qualified cross-database"):
            import_sql_dump_to_mysql(
                connection,
                "INSERT INTO other_db.customers VALUES (1, 'person@example.com');",
            )


if __name__ == "__main__":
    unittest.main()
