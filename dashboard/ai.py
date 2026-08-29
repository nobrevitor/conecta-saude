"""
Consulta em linguagem natural sobre a camada Gold, via Select AI.

A tradução de pergunta em SQL acontece DENTRO do Autonomous Database,
pelo DBMS_CLOUD_AI. O Streamlit não vê o modelo nem a chave de API: ele
manda a pergunta, recebe SQL, confere e executa. É o que sustenta o
argumento de solução Oracle de ponta a ponta.

O QUE ESTE MÓDULO ENTREGA

Uma Resposta reúne as quatro coisas que a página mostra:

    sql        o SQL que o modelo escreveu, para auditoria
    dados      o resultado estruturado, já executado
    narrativa  a leitura em texto corrido, gerada pelo modelo
    erro       o motivo, quando alguma das etapas falha

A leitura quantitativa — quem lidera, quanto o topo concentra, qual a
amplitude — não sai daqui: é calculada sobre as linhas devolvidas, em
ui.leitura_do_resultado. Separar as duas deixa claro para o leitor o que
é redação de modelo e o que é conta sobre o dado.

DUAS BARREIRAS ANTES DE EXECUTAR

O SQL passa por _somente_leitura, e o usuário da aplicação só tem SELECT
na Gold. São independentes de propósito: a do aplicativo evita mensagem
de erro feia na tela, a do banco é a que de fato protege.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

import db

PERFIL = "CONECTA_AI"

# Só para semear a interface. São strings, não consultas: o SQL de todas
# elas é escrito pelo Select AI na hora, como o de qualquer pergunta
# digitada. Guardar SQL pronto aqui criaria um segundo caminho de
# execução para manter em pé sem necessidade.
PERGUNTAS_EXEMPLO = (
    "Quais municípios estão sob maior pressão assistencial?",
    "Quais estados têm mais municípios sem leito SUS?",
    "De quais municípios os pacientes mais precisam sair para internar?",
    "Quais hospitais têm mais internações por leito?",
    "Quais procedimentos concentram mais internações?",
    "Como as internações evoluíram ao longo de 2024?",
)


@dataclass
class Resposta:
    pergunta: str
    sql: str = ""
    dados: pd.DataFrame = field(default_factory=pd.DataFrame)
    narrativa: str = ""
    erro: str | None = None

    @property
    def tem_dados(self) -> bool:
        return not self.dados.empty


# ---------------------------------------------------------------------
# Disponibilidade
# ---------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def disponivel() -> tuple[bool, str]:
    """
    O perfil existe e está habilitado? Nunca levanta exceção.

    Um painel que quebra na abertura porque o provedor de LLM caiu é pior
    do que um que avisa. A página usa este retorno para decidir se abre o
    campo de pergunta ou uma mensagem de indisponibilidade.
    """
    try:
        perfil = db.executar_sem_cache(
            "SELECT status FROM user_cloud_ai_profiles WHERE profile_name = :p",
            {"p": PERFIL},
        )
    except Exception as erro:
        return False, f"Não foi possível consultar o perfil de AI: {erro}"

    if perfil.empty:
        return False, (
            f"O perfil {PERFIL} não existe neste banco. "
        )
    if str(perfil.iloc[0, 0]).upper() != "ENABLED":
        return False, f"O perfil {PERFIL} existe, mas está {perfil.iloc[0, 0]}."
    return True, "Select AI ativo no Autonomous Database."


# ---------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------

# O modelo recebe o esquema e os comentários da Gold pelo próprio
# DBMS_CLOUD_AI. O que ele não tem como saber é o que só existe na tela:
# qual competência está no filtro.
#
# A regra de JOIN vem repetida aqui de propósito, embora também esteja
# nos comentários das tabelas. Sem ela o modelo escrevia
#
#     FROM gold_fato_municipio m JOIN gold_icpa i
#       ON m.cod_municipio = i.cod_municipio
#
# que cruza cada município-mês com as outras onze competências: 439 mil
# linhas onde deveriam sair 3 mil. Não dá erro nem volta vazio — devolve
# resposta errada com aparência de certa, e por isso vale a redundância.
CONTEXTO = "\n".join([
    "Contexto obrigatorio para gerar o SQL:",
    "- Use a competencia '{competencia}' no filtro, no formato AAAAMM, "
    "salvo se a pergunta citar outro periodo explicitamente.",
    "- O grao das tabelas Gold e (municipio, competencia). Todo JOIN entre "
    "elas precisa casar cod_municipio E competencia; juntar so por "
    "cod_municipio multiplica as linhas pelas doze competencias.",
    "- Compare valores de texto com o literal exato gravado na coluna, "
    "com acento e caixa como descritos no comentario da coluna.",
    "- Limite rankings com FETCH FIRST 15 ROWS ONLY quando a pergunta nao "
    "disser quantas linhas quer.",
    "",
    "Pergunta: {pergunta}",
])


def _gerar(prompt: str, acao: str) -> str:
    """Uma chamada ao DBMS_CLOUD_AI. `acao` é showsql ou narrate."""
    df = db.executar_sem_cache(
        """
        SELECT DBMS_CLOUD_AI.GENERATE(
                 prompt => :prompt, profile_name => :perfil, action => :acao
               ) AS resposta
          FROM dual
        """,
        {"prompt": prompt, "perfil": PERFIL, "acao": acao},
    )
    return "" if df.empty else str(df.iloc[0, 0])


# ---------------------------------------------------------------------
# Barreira de leitura
# ---------------------------------------------------------------------

PROIBIDOS = ("insert", "update", "delete", "drop", "alter", "create",
             "truncate", "grant", "revoke", "merge", "execute", "begin")


def _limpar_sql(texto: str) -> str:
    """Remove cercas de markdown e ponto e vírgula final."""
    texto = re.sub(r"^```(?:sql)?\s*|\s*```$", "", texto.strip(),
                   flags=re.IGNORECASE | re.MULTILINE)
    return texto.strip().rstrip(";").strip()


def _somente_leitura(sql: str) -> bool:
    """Aceita apenas um SELECT ou WITH, sem comandos encadeados."""
    if not sql:
        return False
    normalizado = " " + re.sub(r"\s+", " ", sql.lower()) + " "
    if not normalizado.lstrip().startswith(("select", "with")):
        return False
    if ";" in sql:
        return False
    return not any(f" {palavra} " in normalizado for palavra in PROIBIDOS)


# ---------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def perguntar(pergunta: str, competencia: str) -> Resposta:
    """
    Pergunta em português, resposta com SQL, dados e narrativa.

    A narrativa só é pedida quando a consulta devolveu linhas. Ela é uma
    segunda ida ao modelo, e narrar um resultado vazio custa a mesma
    espera para dizer que não há nada a dizer.

    O cache existe porque cada chamada aqui são DUAS idas ao modelo, e a
    mesma pergunta na mesma competência devolve a mesma coisa. Meia hora
    de TTL cobre a sessão de quem repete uma pergunta pelos botões de
    exemplo sem congelar o resultado para sempre.
    """
    resposta = Resposta(pergunta=pergunta.strip())
    if not resposta.pergunta:
        resposta.erro = "Digite uma pergunta."
        return resposta

    prompt = CONTEXTO.format(competencia=competencia, pergunta=resposta.pergunta)

    try:
        resposta.sql = _limpar_sql(_gerar(prompt, "showsql"))
    except Exception as erro:
        resposta.erro = f"O Select AI não conseguiu gerar o SQL: {erro}"
        return resposta

    if not resposta.sql:
        resposta.erro = "O Select AI não devolveu nenhum SQL para esta pergunta."
        return resposta

    if not _somente_leitura(resposta.sql):
        resposta.erro = "A consulta gerada não é somente leitura e foi bloqueada."
        return resposta

    try:
        resposta.dados = db.executar_sem_cache(resposta.sql)
    except Exception as erro:
        resposta.erro = f"O SQL gerado não pôde ser executado: {erro}"
        return resposta

    if resposta.tem_dados:
        try:
            resposta.narrativa = _gerar(prompt, "narrate").strip()
        except Exception:
            # A narrativa é complemento: perdê-la não invalida a resposta,
            # que já tem SQL, dados e a leitura calculada sobre as linhas.
            resposta.narrativa = ""

    return resposta
