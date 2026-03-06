import streamlit as st
import anthropic
import mysql.connector
import ssl
import os  # Adicione esta importação

# --- FUNÇÃO PARA PEGAR SEGREDOS EM QUALQUER LUGAR ---
def get_secret(key):
    """Busca a chave no st.secrets (local/Streamlit Cloud) ou no ambiente (Render)"""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError, RuntimeError):
        return os.environ.get(key)

# --- CONFIGURAÇÕES DE ACESSO ---
API_KEY = get_secret("ANTHROPIC_API_KEY")
MODELO_CLAUDE = "claude-sonnet-4-20250514"

# Configurações do seu MySQL na Aiven (Nuvem)
DB_CONFIG = {
    "host": get_secret("DB_HOST"),
    "port": int(get_secret("DB_PORT") or 25086),
    "user": get_secret("DB_USER"),
    "password": get_secret("DB_PASSWORD"),
    "database": get_secret("DB_NAME"), # Adicione esta linha
    "charset": "utf8"
}
# System Prompt com todas as suas regras de negócio integradas
SYSTEM_PROMPT = """
Você é o SCANBOT, analista de dados sênior da Scan Global Logistics. Sua única fonte é a tabela `massa_operacional`.

REGRAS DE QUERY (OBRIGATÓRIO):

1. **LÓGICA DE BUSCA E FUNÇÕES MATEMÁTICAS GLOBAIS**:
   - **Busca Flexível**: Para QUALQUER coluna de texto (`Vendedor`, `Cliente`, `Origem`, `Destino`, `ARMADOR`, `MODALIDADE`, `PRODUTO`), use sempre `LOWER(coluna) LIKE LOWER('%termo%')`. Isso cobre abreviações e nomes parciais.
   - **Matemática para Tudo**: Aplique cálculos matemáticos sempre que solicitado para qualquer métrica:
     - `SUM(TEUS)` para volume total.
     - `COUNT(*)` para contagem de processos ou clientes.
     - `AVG(...)` para médias (ex: média de TEUS por cliente ou por rota).
     - `MAX(...)` / `MIN(...)` para identificar maiores e menores performances, volumes ou datas.
     - **Porcentagem (Share)**: Para calcular a representatividade de QUALQUER entidade sobre outra, use a lógica: `(SUM(valor_específico) / SUM(valor_total_do_grupo)) * 100`.

2. **LÓGICA DE CLIENTES, VENDEDORES E ENTIDADES**:
   - Se perguntarem "Quantos clientes", use `COUNT(DISTINCT Cliente)`.
   - Entenda que nomes de empresas = `Cliente` e nomes de pessoas = `Vendedor`.

3. **LÓGICA DE ROTAS E PORTOS**:
   - **Origem (POL)**: Porto de Origem, POL, Porto de saída.
   - **Destino (POD)**: Porto de Destino, POD, Porto final.
   - **Rota "A x B"**: Filtre `LOWER(Origem) LIKE '%A%' AND LOWER(Destino) LIKE '%B%'`.

4. **MEDIDA DE VALOR E SINÔNIMOS**:
   - "TEUS" ou "Volume" -> `SUM(TEUS)`.
   - "Processos" ou "Embarques" -> `COUNT(*)`.
   - Vendedor = Comercial, Vendas | ARMADOR = Navio, Linha, Provedor.

5. **REGRA DE MODALIDADE E TEUS**:
   - Perguntou "TEUS" sem especificar? Filtre `MODALIDADE = 'FCL'`.
   - Perguntou "LCL"? Use `COUNT(*)` e filtre `MODALIDADE = 'LCL'`.

6. **LÓGICA DE DATAS (STR_TO_DATE)**:
   - Use: `STR_TO_DATE(coluna, '%d/%m/%Y')`.
   - **PADRÃO**: Se o usuário não especificar qual timeline quer, use sempre a coluna `Data de abertura`.
   - **ETD**: Use para "previsão de sair".
   - **ETA**: Use para "previsão de chegada".
   - **EMBARQUE**: Use para "embarcado" ou "saiu".
   - **CHEGADA**: Use para "atracado" ou "chegou".
   - Ano Base Padrão: `2026`. Suporte a Quinzenas, Semanas e Trimestres.

REGRAS DE RESPOSTA:
- Use a função `executar_sql` para cada pergunta.
- **ÊNFASE NA TIMELINE (OBRIGATÓRIO)**: Ao responder, você deve sempre enfatizar qual timeline de data foi utilizada na consulta, escrevendo-a em caixa alta e entre aspas. 
  - Se usou `Data de abertura`, chame de **"ABERTOS"**.
  - Se usou `ETD`, chame de **"PREVISTOS PARA SAIR (ETD)"**.
  - Se usou `ETA`, chame de **"PREVISTOS PARA CHEGAR (ETA)"**.
  - Se usou `EMBARQUE`, chame de **"EMBARCADOS"**.
  - Se usou `CHEGADA`, chame de **"ATRACADOS/CHEGADOS"**.
  - Exemplo: "No mês de janeiro temos 400 TEUS **'ABERTOS'**."
- Use tabelas Markdown para exibir listas ou comparações.
- Formate porcentagens com `%` e médias/somas de forma legível.
- Se o banco retornar vazio, informe que não encontrou registros para os filtros.
"""

client = anthropic.Anthropic(api_key=API_KEY)

# --- FUNÇÃO DE CONEXÃO COM O BANCO ---
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

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="SCANBOT - LATAM", layout="wide")

# CSS Reforçado para forçar a cor do título e das bolhas de texto
st.markdown("""
    <style>
    /* Força a cor no h1 do Streamlit */
    div[data-testid="stHeader"] + div blockquote h1, 
    .main h1, 
    .custom-title {
        color: #D11242 !important;
        font-weight: bold !important;
    }
    
    /* Fundo da pergunta do usuário e texto branco */
    div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) {
        background-color: #D11242 !important;
        border-radius: 10px;
    }
    
    /* Garante que o texto dentro do balão do usuário seja branco */
    div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) p {
        color: white !important;
    }
    </style>
    """, unsafe_allow_html=True)

# Título usando a classe customizada
st.markdown('<h1 class="custom-title"> SCAN IA - Commercial Performance </h1>', unsafe_allow_html=True)

# Inicializar histórico de conversa
if "messages" not in st.session_state:
    st.session_state.messages = []

# Exibir histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada do usuário
if prompt := st.chat_input("Ex: Pesquise o volume de FCL e LCL pela nossas linhas temporais = Abetura, Confirmação e Previsão Embarque e Chegada"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # Definição da Tool
        tools = [{
            "name": "executar_sql",
            "description": "Consulta o banco MySQL blulogistics na tabela massa_operacional",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A query SQL formatada conforme as regras do sistema."}
                },
                "required": ["query"]
            }
        }]

        # 1. Envio para o Claude
        response = client.messages.create(
            model=MODELO_CLAUDE,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        )

        # 2. Verificar Tool Use
        if response.stop_reason == "tool_use":
            tool_use = next(b for b in response.content if b.type == "tool_use")
            query_gerada = tool_use.input["query"]
            
            resultado_bruto = rodar_query_mysql(query_gerada)
            
            # 3. Formatar resposta final
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
        st.session_state.messages.append({"role": "assistant", "content": resposta_final})