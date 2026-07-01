"""
Agente IA Alesso - Interfaz Web (Streamlit)
Conexión: Azure AD MFA | Modelo: claude-haiku-4-5
"""

import streamlit as st
import pyodbc
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────
SERVER   = "dbsrvgold01.database.windows.net"
DATABASE = "db-sqldex01"
USER     = "looker_reader"
PASSWORD = os.getenv("DB_PASSWORD")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

SCHEMA_DESC = """
Tabla: [db-sqldex01].alesso.t_ComportamientoInventario_sql
Columnas:
  - FECHA_DE_HOY    (datetime) : Fecha del registro
  - CLASIFICACIÓN   (varchar)  : Clasificación del artículo
  - UN              (varchar)  : Unidad de negocio
  - SUC             (varchar)  : Sucursal
  - ARTICULO        (varchar)  : Código del artículo
  - DESCRIPCION     (varchar)  : Descripción del artículo
  - MARCA           (varchar)  : Marca del artículo
  - FAMILIA         (varchar)  : Familia del artículo
  - LINEA           (varchar)  : Línea del artículo
  - UNIDADES        (numeric)  : Unidades en inventario
  - CLASIFICACION   (varchar)  : Clasificación adicional
  - COSTO_UNITARIO  (numeric)  : Costo unitario del artículo
  - COSTO_TOTAL     (numeric)  : Costo total del inventario
  - CLASE           (varchar)  : Clase del artículo
  - COMPROMETIDO    (numeric)  : Unidades comprometidas
  - DISPONIBLE      (numeric)  : Unidades disponibles
  - CLIENTE         (varchar)  : Cliente asociado
"""

SYSTEM_PROMPT = f"""Eres un asistente de análisis de inventario para la empresa Alesso.
Tienes acceso a una tabla de comportamiento de inventario en Azure SQL.

{SCHEMA_DESC}

Cuando el usuario haga una pregunta, sigue ESTRICTAMENTE este proceso:
1. Genera una consulta SQL válida para Azure SQL (T-SQL).
2. Responde SOLO con el SQL entre etiquetas <sql> y </sql>. NADA más. Sin explicación, sin preguntas, sin comentarios.
3. El sistema ejecutará el SQL automáticamente y te dará los resultados.
4. Con los resultados, redacta una respuesta clara en español.

IMPORTANTE: En tu primera respuesta a cualquier pregunta, devuelve ÚNICAMENTE <sql>...</sql>. No escribas nada fuera de esas etiquetas.

Reglas SQL:
- Usa siempre el nombre completo: [db-sqldex01].alesso.t_ComportamientoInventario_sql
- Para fechas usa: CAST(FECHA_DE_HOY AS DATE)
- Limita resultados con TOP 100 cuando no se especifique límite
- No uses funciones que no existen en T-SQL
"""

# ── Conexión a Fabric DW ──────────────────────────────────────────────────────
@st.cache_resource
def conectar():
    conn_str = (
        "Driver={ODBC Driver 17 for SQL Server};"
        f"Server={SERVER},1433;"
        f"Database={DATABASE};"
        f"UID={USER};"
        f"PWD={PASSWORD};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )
    return pyodbc.connect(conn_str)

def ejecutar_sql(conn, sql: str):
    cursor = conn.cursor()
    cursor.execute(sql)
    cols = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return "Sin resultados."
    lines = [" | ".join(cols)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
    return "\n".join(lines)

def extraer_sql(texto: str):
    if "<sql>" in texto and "</sql>" in texto:
        return texto.split("<sql>")[1].split("</sql>")[0].strip()
    return None

def procesar_pregunta(pregunta: str, conn, cliente):
    st.session_state.historial.append({"role": "user", "content": pregunta})

    # Paso 1: Claude genera SQL
    resp1 = cliente.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=st.session_state.historial,
    )
    msg_sql = resp1.content[0].text
    sql = extraer_sql(msg_sql)

    if not sql:
        st.session_state.historial.append({"role": "assistant", "content": msg_sql})
        return msg_sql, None

    # Paso 2: Ejecutar SQL
    try:
        resultados = ejecutar_sql(conn, sql)
    except Exception as e:
        resultados = f"Error al ejecutar SQL: {e}"

    # Paso 3: Claude redacta respuesta
    st.session_state.historial.append({"role": "assistant", "content": msg_sql})
    st.session_state.historial.append({
        "role": "user",
        "content": f"Resultados de la consulta:\n{resultados}\n\nRedacta una respuesta clara en español para el usuario."
    })

    resp2 = cliente.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=st.session_state.historial,
    )
    respuesta_final = resp2.content[0].text

    st.session_state.historial.pop()
    st.session_state.historial.append({"role": "assistant", "content": respuesta_final})

    return respuesta_final, sql

# ── Interfaz Streamlit ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente Alesso",
    page_icon="📊",
    layout="centered"
)

st.title("📊 Agente de Ventas Alesso")
st.caption("Consulta datos de predicción de ventas en lenguaje natural")

# Inicializar estado
if "historial" not in st.session_state:
    st.session_state.historial = []
if "mensajes_chat" not in st.session_state:
    st.session_state.mensajes_chat = []
if "conn" not in st.session_state:
    st.session_state.conn = None

# Conexión
if st.session_state.conn is None:
    with st.spinner("Conectando a Microsoft Fabric (se abrirá el navegador para MFA)..."):
        try:
            st.session_state.conn = conectar()
            st.success("Conectado a Microsoft Fabric")
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            st.stop()

cliente = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Mostrar historial de chat
for msg in st.session_state.mensajes_chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sql" in msg and msg["sql"]:
            with st.expander("Ver SQL generado"):
                st.code(msg["sql"], language="sql")

# Input del usuario
if pregunta := st.chat_input("Escribe tu pregunta sobre ventas..."):
    # Mostrar mensaje del usuario
    with st.chat_message("user"):
        st.markdown(pregunta)
    st.session_state.mensajes_chat.append({"role": "user", "content": pregunta, "sql": None})

    # Procesar y mostrar respuesta
    with st.chat_message("assistant"):
        with st.spinner("Consultando datos..."):
            respuesta, sql = procesar_pregunta(pregunta, st.session_state.conn, cliente)
        st.markdown(respuesta)
        if sql:
            with st.expander("Ver SQL generado"):
                st.code(sql, language="sql")

    st.session_state.mensajes_chat.append({"role": "assistant", "content": respuesta, "sql": sql})

# Botón para limpiar conversación
if st.session_state.mensajes_chat:
    if st.button("🗑️ Limpiar conversación"):
        st.session_state.historial = []
        st.session_state.mensajes_chat = []
        st.rerun()
