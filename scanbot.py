import streamlit as st
import anthropic
import mysql.connector
import ssl
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

# System Prompt com todas as suas regras de negócio integradas
SYSTEM_PROMPT = """
Você é o SCANBOT, analista de dados sênior da Scan Global Logistics. Sua única fonte é a tabela `massa_operacional`.

REGRAS DE QUERY (OBRIGATÓRIO):

1. **LÓGICA DE BUSCA E FUNÇÕES MATEMÁTICAS GLOBAIS**:
- **Busca Flexível**: Para QUALQUER coluna de texto (`Vendedor`, `Cliente`, `Origem`, `Destino`, `ARMADOR`, `MODALIDADE`, `PRODUTO`), use sempre `LOWER(coluna) LIKE LOWER('%termo%')`.
- **Matemática para Tudo**: Aplique cálculos matemáticos sempre que solicitado para qualquer métrica:
  - `SUM(TEUS)` para volume total.
  - `COUNT(*)` para contagem de processos ou clientes.
  - `AVG(...)` para médias.
  - `MAX(...)` / `MIN(...)` para maiores e menores performances.
  - **Porcentagem (Share)**: `(SUM(valor_específico) / SUM(valor_total_do_grupo)) * 100`.

2. **LÓGICA DE CLIENTES, VENDEDORES E ENTIDADES**:
- Se perguntarem "Quantos clientes", use `COUNT(DISTINCT Cliente)`.
- Nomes de empresas = `Cliente`.
- Nomes de pessoas = `Vendedor`.

3. **LÓGICA DE ROTAS E PORTOS**:
- **Origem (POL)**: Porto de Origem.
- **Destino (POD)**: Porto de Destino.
- **Rota "A x B"**:
  `LOWER(Origem) LIKE '%A%' AND LOWER(Destino) LIKE '%B%'`.

4. **MEDIDA DE VALOR E SINÔNIMOS**:
- "TEUS" ou "Volume" -> `SUM(TEUS)`
- "Processos" ou "Embarques" -> `COUNT(*)`
- Vendedor = Comercial, Vendas
- ARMADOR = Navio, Linha, Provedor

5. **REGRA DE MODALIDADE E TEUS**:
- Perguntou "TEUS" sem especificar → `MODALIDADE = 'FCL'`
- Perguntou "LCL" → `COUNT(*)` com `MODALIDADE = 'LCL'`

6. **LÓGICA DE DATAS (STR_TO_DATE)**:
- Use: `STR_TO_DATE(coluna, '%d/%m/%Y')`
- Se o usuário não especificar timeline, use `Data de abertura`

ETD → previsão de sair  
ETA → previsão de chegada  
EMBARQUE → embarcado  
CHEGADA → chegou  

Ano base padrão: 2026

REGRAS DE RESPOSTA:

- Use a função `executar_sql` para cada pergunta.

ÊNFASE NA TIMELINE:
Sempre enfatize a timeline usada:

Data de abertura → **"ABERTOS"**  
ETD → **"PREVISTOS PARA SAIR (ETD)"**  
ETA → **"PREVISTOS PARA CHEGAR (ETA)"**  
EMBARQUE → **"EMBARCADOS"**  
CHEGADA → **"ATRACADOS/CHEGADOS"**

Exemplo:
"No mês de janeiro temos 400 TEUS **'ABERTOS'**."

- Use tabelas Markdown para comparações
- Formate porcentagens com %
- Se o banco retornar vazio, informe que não encontrou registros.
"""

client = anthropic.Anthropic(api_key=API_KEY)

# -------------------------
# FUNÇÃO DE QUERY MYSQL
# -------------------------
def rodar_query_mysql(query):
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


# -------------------------
# INTERFACE STREAMLIT
# -------------------------
st.set_page_config(page_title="SCANBOT - LATAM", layout="wide")

# CSS customizado
st.markdown(
    """
<style>

div[data-testid="stHeader"] + div blockquote h1,
.main h1,
.custom-title {
    color: #D11242 !important;
    font-weight: bold !important;
}

div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) {
    background-color: #D11242 !important;
    border-radius: 10px;
}

div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) p {
    color: white !important;
}

</style>
""",
    unsafe_allow_html=True,
)

# Título
st.markdown(
    '<h1 class="custom-title"> SCAN IA - Commercial Performance </h1>',
    unsafe_allow_html=True,
)

# Histórico de conversa
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Input do usuário
if prompt := st.chat_input(
    "Ex: Pesquise o volume de FCL e LCL pelas nossas linhas temporais = Abertura, Confirmação e Previsão Embarque e Chegada"
):

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):

        tools = [
            {
                "name": "executar_sql",
                "description": "Consulta o banco MySQL blulogistics na tabela massa_operacional",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A query SQL formatada conforme as regras do sistema.",
                        }
                    },
                    "required": ["query"],
                },
            }
        ]

        # -------------------------
        # 1 - Chamada inicial Claude
        # -------------------------
        response = client.messages.create(
            model=MODELO_CLAUDE,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ],
        )

        # -------------------------
        # 2 - Verificar Tool Use
        # -------------------------
        if response.stop_reason == "tool_use":

            tool_use = next(b for b in response.content if b.type == "tool_use")

            query_gerada = tool_use.input["query"]

            resultado_bruto = rodar_query_mysql(query_gerada)

            # -------------------------
            # 3 - Resposta Final
            # -------------------------
            final_response = client.messages.create(
                model=MODELO_CLAUDE,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": resultado_bruto,
                            }
                        ],
                    },
                ],
            )

            resposta_final = final_response.content[0].text

        else:
            resposta_final = response.content[0].text

        st.markdown(resposta_final)

        st.session_state.messages.append(
            {"role": "assistant", "content": resposta_final}
        )