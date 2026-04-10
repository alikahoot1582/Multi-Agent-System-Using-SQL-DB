import os 
import json
import sqlite3 
import tempfile
from pathlib import Path
import streamlit as st
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage,HumanMessage
try:
    import tabulate  # noqa: F401  # imported for pandas markdown support
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

DEFAULT_MODEL = "llama-3.3-70b-versatile"

MAX_ROWS = 20

@st.cache_resource

def get_llm(groq_api_key: str | None):

    key = groq_api_key or os.getenv("GROQ_API_KEY")

    if not key:
        raise ValueError("Groq API key not provided. Set in sidebar or env GROQ_API_KEY")
    
    return ChatGroq(
        model=DEFAULT_MODEL,
        temperature=0,
        streaming=False,
        api_key=key
    )

# DB HELPER

def save_uploded_db(uploaded_file) -> str:
    """Save uploaded .db file to temp path and return the path."""
    uploaded_file.seek(0)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp.write(uploaded_file.read())
        tmp.flush()
        temp_path = tmp.name
    return temp_path 


def get_db_path(uploaded_file) -> str | None:
    if uploaded_file is not None:
        return save_uploded_db(uploaded_file)
    default_db = Path(__file__).parent / "student.db"
    if default_db.exists():
        return str(default_db)
    return None

def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_schema(conn: sqlite3.Connection) -> dict:
    """Return schema info: {table_name:[col1, col2,...],...}"""
    schema = {}
    cur = conn.cursor()
    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%';" 
    ).fetchall()
    for (table_name,) in tables:
        cols = cur.execute(f"PRAGMA table_info({table_name});").fetchall()
        col_names = [c[1] for c in cols]
        schema[table_name] = col_names
    return schema

def schema_to_text(schema: dict) -> str:
    lines = []

    for table, cols in schema.items():
        preview = ", ".join(cols[:10])
        extra = " ..." if len(cols) > 10 else ""
        lines.append(f"- {table}({preview}{extra})")
    return "\n".join(lines)


# Agent Logic

#This function talks to the LLM and asks it to generate a safe SQL query in JSON format. 
def ask_llm_for_sql(llm: ChatGroq, question: str, schema_text: str) -> dict:
    """
    Ask the LLM to propose a safe Select query.

    Returns dict:
    {
        "sql" : "...",
        "thinking" : "...",
        "followups": ["...","..."]
    }
    """
    # we create a systemMessage to tell the LLM its role, rules and the schema it must follow.

    system = SystemMessage(
        content = (
            "You are 'DataGenie', a helpful SQL expert for  SQLite database.\n"
            "You Must use only the tables and columns listed in SCHEMA below.\n"
            "Write ONLY safe SELECT queries (no INSERT/UPDATE/DELETE, no PRAGMA, no DROP, etc.).\n"
            "If the question is vague, make a reasonble assumption and mention it in 'thinking'.\n"
            "ALWAYS add a LIMIT clause (e.g., LIMIT 20) if user does not specify one.\n"
            "Return your answer as strict JSON with keys: sql, thinking, followups.\n"
            "followups = a short list of 2 extra questions the user might like.\n"
            f"SCHEMA:\n{schema_text}"
        )
    )
    user = HumanMessage(
        content = (
            f"User question: {question}\n\n"
            "Reply ONLY in JSON like this:\n"
            '{"sql":"...","thinkig":"...", "followups":["...","...]}'
        )
    )
    resp = llm.invoke([system, user])
    text = resp.content.strip()

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        json_text = text[start:end]
        data = json.loads(json_text)
    except Exception:
        data = {
            "sql" : "SELECT 'Sorry, I could not generate SQL' AS error",
            "thinking": "I failed to follow my own JSON format.",
            "followups" : [
                "Try asking a simpler question",
                "Ask me what tables exist and what they contain."
            ]
        }

    return data

def run_sql(conn: sqlite3.Connection, sql:str) -> pd.DataFrame | str:

    sql_clean = sql.strip().rstrip(";")

    if not sql_clean.lower().startswith("select"):
        return "Blocked: Only SELECT queries aare allowed"
    
    if "limit" not in sql_clean.lower():
        sql_to_run = f"{sql_clean} LIMIT {MAX_ROWS}"
    else:
        sql_to_run = sql_clean
    
    try:
        df = pd.read_sql_query(sql_to_run, conn)
        return df 
    except Exception as e:
        return f"SQL Error: {e}"

def build_final_answer(llm: ChatGroq, question: str, sql: str, result) -> str:

    if isinstance(result, pd.DataFrame):
        if result.empty:
            result_text = "The query returned 0 rows."
        else:
            preview = result.head(min(5,len(result)))
            result_text = "Here is a preview of the result (up to 5 rows):\n"
            if HAS_TABULATE:
                result_text += preview.to_markdown(index=False)
            else:
                result_text += preview.to_string(index=False)
    else:
        result_text = str(result)

    system = SystemMessage(
        content = (
            "You are 'DataGenie', an AI tutor.\n"
            "Explin what the SQL result means in simple,, encouraging language.\n"
            "If there was an error, explain it gently and hint how to fix the query.\n"
            "End with one short playful line (e.g. about being a data genie)."
        )
    )
    user = HumanMessage(
        content = f"User question: {question}\n SQL used:\n{sql}\n\n Result summary:\n{result_text}"
    )

    resp = llm.invoke([system, user])

    return resp.content.strip()


## Streamlit app

def main():

    st.set_page_config(
        page_title= "DataGenie",
        page_icon="🧞‍♂️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("🧞‍♂️ DataGenie: Talk to your SQL Database")

    st.markdown(
        """
        - Upload a `.db` file (or keep a `student.db` next to the script).
        - Ask questions in **English or Roman Urdu**.
        - See the **exact SQL query**, **results**, and **smart follow-up suggestions**.
        - Watch how the *DataGenie* thinks about your question. 💫
        """
    )

    with st.sidebar:
        st.header("Step 1: Database")
        uploaded = st.file_uploader("Upload SQLite .db", type = ["db","sqlite"])

        st.caption("If you don't upload, I'll look for `student.db` in this folder.")

        st.header("Step 2: Groq API Key")

        key_input = st.text_input(
            "GROQ_API_KEY",
            type="password",
            help = "Get it from console.groq.com -> API Keys",
        )

        if key_input:
            os.environ["GROQ_API_KEY"] = key_input

        st.markdown("----")
        st.write("For client to see the SQL, see the results and see the 'Genie Brain'.💡")

    db_path = get_db_path(uploaded)

    if not db_path:
        st.warning("No database available. Please upload a `.db` file or add `student.db` next to this script.")
        return
    
    try:
        conn = connect_db(db_path)
    except Exception as e:
        st.error(f"Could not open database: {e}")
        return 
    
    schema = get_schema(conn)

    if not schema:
        st.error("No user tables found in this database.")
        return
    
    st.subheader(" 📚 Detected Tables and Columns")

    st.code(schema_to_text(schema))

    try:
        llm = get_llm(os.getenv("GROQ_API_KEY"))
    except Exception as e:
        st.error(str(e))
        return 
    
    if "history" not in st.session_state:
        st.session_state["history"] = []

    for turn in st.session_state["history"]:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
    
    user_q = st.chat_input("Ask DataGenie about your data...")

    if user_q: 
        with st.chat_message("user"):

            st.markdown(user_q)

        st.session_state["history"].append({"role":"user","content":user_q})

        with st.chat_message("assistant"):
            
            st.markdown("😬 **DataGenie is reading your schema and cooking up SQL...** ")

            schema_text = schema_to_text(schema)

            plan = ask_llm_for_sql(llm, user_q, schema_text)

            sql = plan.get("sql","")

            thinking = plan.get("thinking","")

            followups = plan.get("followups",[])[:3]


            if thinking:
                st.markdown(f"🧠 **Agents thought bubble:** {thinking}")

            if sql:
                st.markdown("**Generated SQL:**")
                st.markdown(f"```sql\n{sql}\n```")
            else:
                st.warning("No SQL was generated")

            result = run_sql(conn, sql) if sql else "No SQL to run."

            if isinstance(result, pd.DataFrame):

                if result.empty:
                    st.info("Query ran successfully but returned **0 rows** . ")
                else:
                    st.dataframe(result, use_container_width=True)
            else:
                if result.startswith("SQL Error") or result.startswith("Blocked"):
                    st.error(result)
                else:
                    st.write(result)
            
            final_answer = build_final_answer(llm, user_q, sql, result)

            st.markdown("----")

            st.markdown(final_answer)

            if followups:
                st.markdown("**Do you also want to know:**")

                cols = st.columns(len(followups))

                for i, fq in enumerate(followups):

                    if cols[i].button(f"{fq}"):
                        st.session_state["history"].append({"role":"user","content":fq})
                        st.experimantal_rerun()
        
        st.session_state["history"].append(
            {"role":"assistant","content": final_answer}
        )


if __name__ == "__main__":
    main()
