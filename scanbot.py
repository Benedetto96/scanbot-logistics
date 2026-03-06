import streamlit as st
import anthropic
import mysql.connector
import os

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODELO_CLAUDE = "claude-sonnet-4-20250514"

# Configurações do seu MySQL na Aiven (Nuvem)
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME"),
    "charset": "utf8"
}

SYSTEM_PROMPT = """
Você é o SCANBOT, analista de dados sênior da Scan Global Logistics. Sua única fonte é a tabela `massa_operacional`.

REGRAS DE QUERY (OBRIGATÓRIO):
1. **LÓGICA DE BUSCA E FUNÇÕES MATEMÁTICAS GLOBAIS**:
   - **Busca Flexível**: Para QUALQUER coluna de texto (`Vendedor`, `Cliente`, `Origem`, `Destino`, `ARMADOR`, `MODALIDADE`, `PRODUTO`), use sempre `LOWER(coluna) LIKE LOWER('%termo%')`.
   - **Matemática**: Use `SUM(TEUS)`, `COUNT(*)`, `AVG(...)`, `MAX(...)`, `MIN(...)`.
   - **Porcentagem (Share)**: `(SUM(valor_específico) / SUM(valor_total_do_grupo)) * 100`.

2. **LÓGICA DE CLIENTES, VENDEDORES E ENTIDADES**:
   - Quantos clientes: `COUNT(DISTINCT Cliente)`. Nomes de empresas = `Cliente`, nomes de pessoas = `Vendedor`.

3. **LÓGICA DE ROTAS E PORTOS**:
   - Rota "A x B": `LOWER(Origem) LIKE '%A%' AND LOWER(Destino) LIKE '%B%'`.

4. **MEDIDA DE VALOR E SINÔNIMOS**:
   - TEUS/Volume -> `SUM(TEUS)`. Processos/Embarques -> `COUNT(*)`.

5. **REGRA DE MODALIDADE E TEUS**:
   - TEUS sem especificar? Filtre `MODALIDADE = 'FCL'`. LCL? Filtre `MODALIDADE = 'LCL'`.

6. **LÓGICA DE DATAS**:
   - Use `STR_TO_DATE(coluna, '%d/%m/%Y')`. Padrão: `Data de abertura`.
   - **Timelines**: "ABERTOS" (Data de abertura), "PREVISTOS PARA SAIR (ETD)" (ETD), "PREVISTOS PARA CHEGAR (ETA)" (ETA), "EMBARCADOS" (EMBARQUE), "ATRACADOS/CHEGADOS" (CHEGADA).

REGRAS DE RESPOSTA:
- Use a função `executar_sql`.
- ENFATIZE a timeline utilizada conforme nomes acima (ex: "400 TEUS 'ABERTOS'").
- Use tabelas Markdown e formate porcentagens/números.
"""

client = anthropic.Anthropic(api_key=API_KEY)

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def rodar_query_mysql(query):
    # Proteção contra comandos destrutivos
    proibidos = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER"]
    if any(palavra in query.upper() for palavra in proibidos):
        return "Erro: A consulta contém comandos não autorizados de modificação de dados."
    
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return str(rows)
    except Exception as e:
        return f"Erro ao acessar MySQL: {str(e)}"

def obter_texto_da_resposta(content_blocks):
    return "".join([b.text for b in content_blocks if hasattr(b, 'text')])

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="SCANBOT - LATAM", layout="wide")

st.markdown("""<style>
    .custom-title { color: #D11242 !important; font-weight: bold !important; }
    div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) { background-color: #D11242 !important; border-radius: 10px; }
    div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) p { color: white !important; }
</style>""", unsafe_allow_html=True)

st.markdown('<h1 class="custom-title"> SCAN IA - Commercial Performance </h1>', unsafe_allow_html=True)

if "messages" not in st.session_state: st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if prompt := st.chat_input("Ex: Qual o volume total de TEUS por Vendedor?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        tools = [{
            "name": "executar_sql",
            "description": "Exclusivo para consultas SQL na tabela `massa_operacional`. Use SOMENTE para dados, métricas ou filtros. NÃO use para conversas casuais.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "SQL SELECT query"}},
                "required": ["query"]
            }
        }]

        response = client.messages.create(
            model=MODELO_CLAUDE, max_tokens=1024, system=SYSTEM_PROMPT, tools=tools,
            messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        )

        if response.stop_reason == "tool_use":
            tool_use = next(b for b in response.content if b.type == "tool_use")
            resultado_bruto = rodar_query_mysql(tool_use.input["query"])
            
            final_response = client.messages.create(
                model=MODELO_CLAUDE, max_tokens=1024, system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": resultado_bruto}]}
                ],
            )
            resposta_final = obter_texto_da_resposta(final_response.content)
        else:
            resposta_final = obter_texto_da_resposta(response.content)

        st.markdown(resposta_final)
        st.session_state.messages.append({"role": "assistant", "content": resposta_final})