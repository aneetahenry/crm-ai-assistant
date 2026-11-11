# CRM AI Assistant

Streamlit chatbot for querying a MySQL CRM database or uploaded CSV/Excel files.
Gemini generates read-only SQL, and Plotly visualizes suitable query results.

## Requirements

- Windows 10/11
- Python 3.10 or later (64-bit recommended)
- MySQL Server reachable from this computer for MySQL databases and SQL dumps
- A Google Gemini API key for natural-language SQL generation

CSV and Excel analysis does not need MySQL. Without a Gemini API key, the UI
starts but AI-powered chat requests cannot be generated.

## 1. Open a terminal in the project directory

Open PowerShell and run:

```powershell
Set-Location "D:\QUEST TRAINING\GEN AI\crm"
```

## 2. Create and activate a virtual environment

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, allow it for the current terminal only, then
activate the environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. Install Python dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Configure secrets and the database

The project `.env` file is loaded from the `crm` folder. Keep it private and
never commit or share its contents. It must define:

```dotenv
GEMINI_API_KEY=your_real_gemini_api_key
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=crm_ai
```

Use the port and user configured in your MySQL installation; they may differ
from the example. The current `.env` is configured and the database connection
was verified in this environment.

If `.env` does not exist, copy the example and edit it:

```powershell
Copy-Item .env.example .env
notepad .env
```

Do not paste your API key or database password into chat, screenshots, logs, or
source files.

### Prepare the CRM database (optional)

The CRM seed data and notebooks are intentionally excluded from this public
repository because they contain contact information. To initialize a database,
use your own trusted SQL schema or dump with MySQL Workbench or another trusted
MySQL client, after checking that its `CREATE DATABASE` and `CREATE TABLE`
statements will not conflict with existing data. The app can create the
configured database from the sidebar after confirmation, but database creation
alone does not populate tables.

## 5. Start the application

With the virtual environment activated and the current directory set to the
`crm` folder:

```powershell
python -m streamlit run app.py
```

Open the **Local URL** printed in the terminal (normally
`http://localhost:8501`). Keep that terminal open while using the app. Stop the
server with `Ctrl+C`.

## 6. Check MySQL in the app

The sidebar shows whether the configured MySQL server is connected. Use
**Configure / test MySQL connection** and **Test Connection** to retry or enter
connection details. Password input is masked and the password is not kept in
Streamlit session state.

- If the server is reachable but the configured database is absent, the app
  offers a separately confirmed **Create configured database** action.
- If login fails, verify the host, port, username, password, and MySQL user
  privileges.
- If the server cannot be reached, ensure MySQL is running and the port is
  correct.
- SQL dumps require MySQL. They are imported only after confirmation and into a
  newly created `crm_import_*` database, not into the configured CRM database.

## 7. Analyze uploaded CSV or Excel files

1. In the sidebar, upload a `.csv`, `.xlsx`, or `.xls` file.
2. The app previews the data and reports its row/column counts.
3. Choose that upload under **Active Data Source**.
4. Ask a question in the chat input.

These datasets are kept in the current Streamlit session using in-memory
SQLite, so no MySQL connection is required. They are removed when the session
ends or when you remove the active dataset.

## 8. Import and query an SQL dump

1. Connect to MySQL with an account allowed to create databases and tables.
2. Upload the `.sql` file in the sidebar and review its filename and size.
3. Confirm that it will be imported into a new isolated database.
4. Choose **Import SQL dump**.
5. After import, select the imported database in **Active Data Source** and ask
   questions in chat.

The import flow supports common table/index creation, inserts, and table
alterations, and skips standard `CREATE DATABASE`, `USE`, and table-reset
preambles. Unsupported or dangerous statements stop the import. Because SQL
files can contain arbitrary code and schema changes, only import dumps from a
trusted source.

## 9. Troubleshooting

### “MySQL not connected”

Check the sidebar’s detailed message, verify `.env` key names and MySQL
availability, and use **Test Connection**. A configured database may not yet
exist; if so, create it from the explicit confirmation control or initialize
the CRM schema with the trusted SQL setup file.

### “Gemini client is not configured”

Set a valid `GEMINI_API_KEY` in `.env`, save the file, and restart Streamlit.

### Port already in use

Start Streamlit on another port:

```powershell
python -m streamlit run app.py --server.port 8502
```

### Verify the environment

```powershell
python -m pip show streamlit pymysql google-genai
python -m unittest discover -s tests -v
```

## Features

- MySQL CRM and isolated imported SQL databases
- CSV and Excel analysis independent of MySQL
- Dynamic schema and relationship context
- Gemini-generated, read-only SQL with validation
- Conversational results, tables, and interactive Plotly visualizations
