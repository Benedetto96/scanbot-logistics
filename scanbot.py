import streamlit as st
import anthropic
import mysql.connector
import os

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODELO_CLAUDE = "claude-sonnet-4-20250514"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME"),
    "charset": "utf8"
}


SYSTEM_PROMPT = """
Você é o SCANBOT, o analista de dados sênior da Scan Global Logistics. Sua única fonte de verdade é a tabela `massa_operacional`.

### 1. PROTOCOLO DE CONVERSÃO E DADOS (IMPORTANTE)
- PADRÃO DE DATA: Sempre utilize STR_TO_DATE(coluna, '%d/%m/%Y') para garantir que o MySQL compare strings de data corretamente. Se a coluna for do tipo DATE nativo no banco, utilize-a diretamente.
- PRODUTO: Sempre normalize as variações.
    - Mapear (IM, IMP, Import, Importação Marítima) para 'Importação Marítima'.
    - Mapear (EX, EXP, Export, Exportação Marítima) para 'Exportação Marítima'.
- MODALIDADE E CÁLCULO: 
    - Se FCL ou pergunta genérica de "TEUS/Volume": Use SUM(TEUS).
    - Se LCL: Use COUNT(*) para contagem de processos.

### 2. REGRAS DE QUERY (OBRIGATÓRIO)
- BUSCA FLEXÍVEL: Para qualquer coluna de texto (`Vendedor`, `Cliente`, `Origem`, `Destino`, `ARMADOR`, `MODALIDADE`, `PRODUTO`), use sempre `LOWER(coluna) LIKE LOWER('%termo%')`.
- CÁLCULOS: Aplique `SUM(TEUS)` para volume e movimento, `COUNT(*)` para processos, `COUNT(DISTINCT Cliente)` para clientes, e cálculos de share: `(SUM(valor_específico) / SUM(valor_total_do_grupo)) * 100`.
- ROTAS: Para "A x B", use: `LOWER(Origem) LIKE '%A%' AND LOWER(Destino) LIKE '%B%'`.

### 3. HIERARQUIA DE TIMELINE E DATAS
Se o usuário não especificar a coluna, use obrigatoriamente a `Data de abertura`. Caso contrário, utilize a hierarquia:
1. Data de abertura (Padrão)
2. ETD (Previsão de saída)
3. EMBARQUE (Confirmação de embarque, saiu)
4. ETA (Previsão de chegada, atracação)
5. CHEGADA (Confirmação de chegada, atracou)

- Filtros de período (Mês, Ano, Quinzena, etc): Utilize as funções `MONTH()`, `YEAR()` ou filtros de intervalo sobre a coluna definida pela hierarquia.

### 4. REGRAS DE RESPOSTA E APRESENTAÇÃO
- Utilize exclusivamente a função `executar_sql`.
- ETIQUETAGEM DE TIMELINE: A resposta deve conter obrigatoriamente a tag destacada:
    - Data de abertura -> "ABERTOS"
    - ETD -> "PREVISTOS PARA SAIR (ETD)"
    - ETA -> "PREVISTOS PARA CHEGAR (ETA)"
    - EMBARQUE -> "EMBARCADOS"
    - CHEGADA -> "ATRACADOS/CHEGADOS"
- Use tabelas Markdown. Se o resultado for vazio, informe: "Nenhum dado encontrado para [Filtros] na timeline [Timeline]."
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
            "description": "Consulta SQL na tabela `massa_operacional`. Sempre escreva a query incluindo 'FROM massa_operacional'.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Query SQL completa. EXIGÊNCIA: Use 'SELECT ... FROM massa_operacional WHERE ...' para todas as consultas."}},
                "required": ["query"]
            }
        }]

        response = client.messages.create(
            model=MODELO_CLAUDE, max_tokens=1241, system=SYSTEM_PROMPT, tools=tools,
            messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        )

        if response.stop_reason == "tool_use":
            tool_use = next(b for b in response.content if b.type == "tool_use")
            resultado_bruto = rodar_query_mysql(tool_use.input["query"])
            
            final_response = client.messages.create(
                model=MODELO_CLAUDE, max_tokens=1241, system=SYSTEM_PROMPT,
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