import json
import re
from typing import Any, Optional

from google import genai


def get_genai_client(api_key: str):
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def classify_intent(user_query: str, client: Optional[Any]) -> str:
    if client is None:
        return "QUERY"

    prompt = f"""
    Decide whether the user wants to query, analyze, or manage CRM data.
    Return JSON only with keys: intent, reason.
    Allowed values for intent: QUERY or NO.

    Examples:
    - 'Show all customers from Kerala' => QUERY
    - 'Add one row' => NO
    - 'Give me monthly sales trends' => QUERY

    USER QUESTION: {user_query}
    """
    response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)
    text = response.text.strip()
    try:
        data = json.loads(text)
        return str(data.get("intent", "QUERY")).upper()
    except Exception:
        if "NO" in text.upper():
            return "NO"
        return "QUERY"


def generate_sql(user_question: str, schema_context: str, client: Optional[Any], source_type: str = "mysql") -> str:
    if client is None:
        raise ValueError("Gemini client is not configured. Add GEMINI_API_KEY to your .env file.")

    prompt = f"""
    You are an expert {source_type.upper()} SQL developer for a CRM system.
    DATABASE SCHEMA:
    {schema_context}

    RULES:
    1. Return ONLY executable SQL.
    2. No markdown fencing, no comments, no extra prose.
    3. Use joins when needed.
    4. Restrict to SELECT statements only.
    5. Never generate DELETE, UPDATE, INSERT, DROP, ALTER, TRUNCATE, or CREATE statements.
    6. If the request cannot be answered safely, return a SELECT query that returns an empty result with a clear business-friendly explanation.

    USER QUESTION:
    {user_question}
    """
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    sql = response.text.strip()
    if "```" in sql:
        sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    return sql


def generate_business_answer(df, user_question: str) -> str:
    if df is None or df.empty:
        return "I couldn't find matching data for that question, so I returned an empty result set."
    if len(df) == 1:
        return f"I found 1 relevant result for your question."
    return f"I found {len(df)} matching records for your question."
