"""
Consulta em linguagem natural sobre a camada Gold.

TRÊS MODOS, em ordem de preferência

  1. SELECT_AI   o Autonomous Database traduz a pergunta em SQL usando
                 DBMS_CLOUD_AI. Exige perfil configurado e provedor de
                 LLM contratado. É o modo que sustenta o argumento
                 "solução Oracle de ponta a ponta" diante da banca.

  2. GEMINI      o Streamlit chama a API do Google diretamente, monta o
                 esquema, recebe o SQL e executa via oracledb. Funciona
                 com a camada gratuita do Gemini, sem configuração no
                 banco e sem ACL de rede.

  3. CATALOGO    consultas pré-escritas, sem LLM nenhum. Rede de
                 segurança: garante que a página funcione na
                 apresentação mesmo com provedor fora do ar.

A página detecta o que está disponível e escolhe. Os três modos
produzem o mesmo objeto Resposta, então a interface não muda.

SEGURANÇA
Em todos os modos, o SQL passa por _somente_leitura antes de ser
executado, e o app conecta com usuário que só tem SELECT na Gold. São
duas barreiras independentes: uma no aplicativo, outra no banco.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd
import requests
import streamlit as st

import db

PERFIL_SELECT_AI = "CONECTA_AI"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELO_PADRAO = "gemini-2.0-flash"


@dataclass
class Resposta:
    pergunta: str
    narrativa: str = ""
    sql: str = ""
    dados: pd.DataFrame = field(default_factory=pd.DataFrame)
    origem: str = "catalogo"          # select_ai | gemini | catalogo
    erro: str | None = None


# =====================================================================
# Detecção do modo disponível
# =====================================================================

@st.cache_data(ttl=600)
def modo_disponivel() -> tuple[str, str]:
    """Devolve (modo, mensagem). Nunca levanta exceção."""
    try:
        perfil = db.executar_sem_cache(
            "SELECT profile_name FROM user_cloud_ai_profiles WHERE profile_name = :p",
            {"p": PERFIL_SELECT_AI},
        )
        if not perfil.empty:
            return "select_ai", "Select AI ativo no Autonomous Database."
    except Exception:
        pass  # pacote ausente ou sem privilégio: segue para o próximo modo

    if st.secrets.get("GEMINI_API_KEY"):
        return "gemini", "Consulta em linguagem natural via Gemini."

    return "catalogo", "Nenhum provedor configurado — usando catálogo de consultas."


# =====================================================================
# Esquema apresentado ao modelo
# =====================================================================

@st.cache_data(ttl=3600)
def esquema_gold() -> str:
    """
    Monta a descrição das tabelas Gold para o prompt.

    Ler do dicionário do banco em vez de escrever à mão garante que o
    modelo veja o esquema real. Os comentários criados no 03_gold.sql
    entram junto — são o que mais melhora a qualidade do SQL gerado.
    """
    colunas = db.query(
        """
        SELECT c.table_name, c.column_name, c.data_type, cc.comments
          FROM user_tab_columns c
          LEFT JOIN user_col_comments cc
                 ON cc.table_name = c.table_name
                AND cc.column_name = c.column_name
         WHERE c.table_name LIKE 'GOLD%'
         ORDER BY c.table_name, c.column_id
        """
    )
    if colunas.empty:
        return ""

    tabelas = db.query(
        """
        SELECT table_name, comments
          FROM user_tab_comments
         WHERE table_name LIKE 'GOLD%' AND comments IS NOT NULL
        """
    )
    descricao = dict(zip(tabelas["table_name"], tabelas["comments"])) if not tabelas.empty else {}

    linhas = []
    for tabela, grupo in colunas.groupby("table_name", sort=False):
        if tabela in descricao:
            linhas.append(f"\n-- {descricao[tabela]}")
        campos = []
        for _, c in grupo.iterrows():
            texto = f"{c['column_name']} {c['data_type']}"
            if c["comments"]:
                texto += f" /* {c['comments']} */"
            campos.append(texto)
        linhas.append(f"{tabela}({', '.join(campos)})")
    return "\n".join(linhas)


INSTRUCOES = """Você traduz perguntas em português para SQL do Oracle Database.

REGRAS OBRIGATÓRIAS
- Responda APENAS com o SQL, sem explicação, sem markdown, sem ponto e vírgula final.
- Use exclusivamente sintaxe Oracle. Para limitar linhas use FETCH FIRST n ROWS ONLY, nunca LIMIT.
- Gere apenas SELECT. Nunca INSERT, UPDATE, DELETE, DROP, ALTER, CREATE ou MERGE.
- Use somente as tabelas listadas no esquema abaixo.
- A coluna competencia é texto no formato AAAAMM, por exemplo '202412'.
- Quando a pergunta não indicar período, use a competência de referência informada.
- Limite o resultado a no máximo 50 linhas.
- Nomes de municípios e estados estão em português, com acentuação.

ESQUEMA DISPONÍVEL
{esquema}

COMPETÊNCIA DE REFERÊNCIA: {competencia}
"""


# =====================================================================
# Modo 1 · Select AI
# =====================================================================

def _select_ai(prompt: str, acao: str) -> str:
    df = db.executar_sem_cache(
        """
        SELECT DBMS_CLOUD_AI.GENERATE(
                 prompt => :prompt, profile_name => :perfil, action => :acao
               ) AS resposta
          FROM dual
        """,
        {"prompt": prompt, "perfil": PERFIL_SELECT_AI, "acao": acao},
    )
    return "" if df.empty else str(df.iloc[0, 0])


def perguntar_select_ai(pergunta: str) -> Resposta:
    resposta = Resposta(pergunta=pergunta, origem="select_ai")
    try:
        resposta.sql = _limpar_sql(_select_ai(pergunta, "showsql"))
        if not _somente_leitura(resposta.sql):
            resposta.erro = "A consulta gerada não é somente leitura e foi bloqueada."
            return resposta
        resposta.dados = db.executar_sem_cache(resposta.sql)
        resposta.narrativa = _select_ai(pergunta, "narrate")
    except Exception as erro:
        resposta.erro = str(erro)
    return resposta


# =====================================================================
# Modo 2 · Gemini chamado pelo Streamlit
# =====================================================================

def _chamar_gemini(prompt: str, instrucao_sistema: str | None = None) -> str:
    """
    Chamada REST direta, sem SDK.

    O SDK do Google muda de nome e de assinatura com frequência; a API
    HTTP é estável. Isso evita que uma atualização de pacote quebre o
    app na véspera da entrega.
    """
    chave = st.secrets["GEMINI_API_KEY"]
    modelo = st.secrets.get("GEMINI_MODEL", MODELO_PADRAO)

    corpo: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }
    if instrucao_sistema:
        corpo["systemInstruction"] = {"parts": [{"text": instrucao_sistema}]}

    resposta = requests.post(
        GEMINI_URL.format(modelo=modelo),
        params={"key": chave},
        json=corpo,
        timeout=60,
    )

    if resposta.status_code != 200:
        raise RuntimeError(f"Gemini respondeu {resposta.status_code}: {resposta.text[:300]}")

    dados = resposta.json()
    try:
        return dados["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Resposta inesperada do Gemini: {json.dumps(dados)[:300]}")


def perguntar_gemini(pergunta: str, competencia: str) -> Resposta:
    resposta = Resposta(pergunta=pergunta, origem="gemini")
    try:
        instrucao = INSTRUCOES.format(esquema=esquema_gold(), competencia=competencia)
        resposta.sql = _limpar_sql(_chamar_gemini(pergunta, instrucao))

        if not _somente_leitura(resposta.sql):
            resposta.erro = "A consulta gerada não é somente leitura e foi bloqueada."
            return resposta

        resposta.dados = db.executar_sem_cache(resposta.sql)

        # Segunda chamada: narra o resultado já obtido, sem reconsultar.
        amostra = resposta.dados.head(20).to_markdown(index=False)
        resposta.narrativa = _chamar_gemini(
            f"Pergunta: {pergunta}\n\nResultado da consulta:\n{amostra}\n\n"
            "Escreva 2 ou 3 frases em português explicando o que esses números "
            "mostram. Não invente dados que não estejam na tabela. Não repita a "
            "tabela inteira."
        )
    except Exception as erro:
        resposta.erro = str(erro)
    return resposta


# =====================================================================
# Validação do SQL
# =====================================================================

def _limpar_sql(texto: str) -> str:
    """Remove cercas de markdown e ponto e vírgula final."""
    texto = re.sub(r"^```(?:sql)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE | re.MULTILINE)
    return texto.strip().rstrip(";").strip()


PROIBIDOS = ("insert", "update", "delete", "drop", "alter", "create",
             "truncate", "grant", "revoke", "merge", "execute", "begin")


def _somente_leitura(sql: str) -> bool:
    """
    Barreira do aplicativo. O banco já recusaria escrita, porque o
    usuário só tem SELECT — mas bloquear antes evita mensagem de erro
    feia na tela durante a demonstração.
    """
    if not sql:
        return False
    normalizado = " " + re.sub(r"\s+", " ", sql.lower()) + " "
    if not normalizado.lstrip().startswith(("select", "with")):
        return False
    if ";" in sql:               # impede múltiplos comandos encadeados
        return False
    return not any(f" {palavra} " in normalizado for palavra in PROIBIDOS)


# =====================================================================
# Modo 3 · Catálogo
# =====================================================================

CATALOGO: dict[str, dict] = {
    "Quais municípios estão sob maior pressão assistencial?": {
        "sql": """
            SELECT municipio, uf, populacao, internacoes, leitos_sus,
                   internacoes_por_leito, permanencia_media, icpa, faixa_pressao
              FROM gold_icpa_classificado
             WHERE competencia = :comp
             ORDER BY icpa DESC
             FETCH FIRST 15 ROWS ONLY
        """,
        "narrativa": (
            "O ranking usa o ICPA, que combina demanda relativa à população, "
            "uso da capacidade instalada e tempo médio de ocupação do leito. "
            "Municípios pequenos tendem a ocupar o topo porque a pressão é "
            "medida contra a própria estrutura, não em volume absoluto."
        ),
    },
    "Quais estados têm mais municípios sem leito SUS?": {
        "sql": """
            SELECT uf, estado, regiao, municipios, municipios_sem_leito,
                   pct_municipios_sem_leito, leitos_por_10mil_hab
              FROM gold_ranking_uf
             WHERE competencia = :comp
             ORDER BY pct_municipios_sem_leito DESC
             FETCH FIRST 15 ROWS ONLY
        """,
        "narrativa": (
            "Município sem nenhum leito SUS cadastrado é a medida mais direta "
            "de vazio assistencial que os dados públicos permitem construir. "
            "Toda a demanda desses municípios é atendida fora."
        ),
    },
    "De quais municípios os pacientes mais precisam sair para internar?": {
        "sql": """
            SELECT municipio, uf, populacao, internacoes_residentes,
                   internacoes_fora, taxa_evasao, municipio_destino
              FROM gold_evasao
             WHERE competencia = :comp
               AND internacoes_residentes >= 100
             ORDER BY taxa_evasao DESC
             FETCH FIRST 15 ROWS ONLY
        """,
        "narrativa": (
            "A evasão compara o município de residência com o de atendimento. "
            "Considera apenas municípios com pelo menos 100 internações no "
            "período, para evitar distorção causada por volume baixo."
        ),
    },
    "Quais hospitais têm mais internações por leito?": {
        "sql": """
            SELECT cnes, tipo_unidade, municipio, uf, internacoes, leitos_sus,
                   internacoes_por_leito, permanencia_media, ocupacao_estimada_pct
              FROM gold_hospital
             WHERE competencia = :comp
               AND leitos_sus > 0
               AND internacoes >= 50
             ORDER BY internacoes_por_leito DESC
             FETCH FIRST 15 ROWS ONLY
        """,
        "narrativa": (
            "Internações por leito mede giro. A ocupação estimada é "
            "aproximação: o SIH registra dias de permanência, não a data "
            "exata de ocupação do leito."
        ),
    },
    "Como as internações evoluíram ao longo de 2024?": {
        "sql": """
            SELECT competencia, total_internacoes, total_obitos,
                   permanencia_media, taxa_mortalidade
              FROM gold_painel_resumo
             ORDER BY competencia
        """,
        "narrativa": (
            "Série das doze competências de 2024. Variações mensais refletem "
            "tanto sazonalidade assistencial quanto o ritmo de processamento "
            "das AIH pelo Ministério da Saúde."
        ),
    },
    "Quais procedimentos concentram mais internações?": {
        "sql": """
            SELECT procedimento, grupo, complexidade, internacoes,
                   permanencia_media, valor_medio, taxa_mortalidade
              FROM gold_procedimento
             WHERE competencia = :comp
             ORDER BY internacoes DESC
             FETCH FIRST 15 ROWS ONLY
        """,
        "narrativa": (
            "Procedimentos traduzidos pelo SIGTAP. Parto e tratamento clínico "
            "costumam liderar em volume; a coluna de complexidade separa média "
            "de alta complexidade."
        ),
    },
}


def perguntar_catalogo(pergunta: str, competencia: str) -> Resposta:
    entrada = CATALOGO[pergunta]
    resposta = Resposta(pergunta=pergunta, origem="catalogo",
                        narrativa=entrada["narrativa"], sql=entrada["sql"].strip())
    try:
        params = {"comp": competencia} if ":comp" in resposta.sql else {}
        resposta.dados = db.executar_sem_cache(resposta.sql, params)
    except Exception as erro:
        resposta.erro = str(erro)
    return resposta


# =====================================================================
# Ponto de entrada único
# =====================================================================

def perguntar(pergunta: str, competencia: str, modo: str) -> Resposta:
    """Roteia para o modo ativo. A página não precisa saber qual é."""
    if pergunta in CATALOGO:
        return perguntar_catalogo(pergunta, competencia)
    if modo == "select_ai":
        return perguntar_select_ai(pergunta)
    if modo == "gemini":
        return perguntar_gemini(pergunta, competencia)
    return perguntar_catalogo(list(CATALOGO)[0], competencia)
