"""
Conecta Saúde · camada de acesso ao Autonomous Database.

Duas decisões críticas moram aqui:

1. POOL DE CONEXÃO com @st.cache_resource
   O Always Free aceita no máximo 20 sessões simultâneas. O Streamlit
   reexecuta o script inteiro a cada interação — cada clique de filtro,
   cada troca de página. Sem pool, cada rerun abriria conexão nova e o
   banco cairia justamente durante a apresentação.

2. CACHE DE CONSULTA com @st.cache_data
   Os dados são batch e não mudam entre execuções. O TTL de uma hora
   existe apenas para o caso de a Gold ser recarregada durante a sessão.

Toda agregação acontece em SQL. O app recebe dados prontos e desenha —
é isso que mantém o consumo de memória compatível com o plano gratuito
do Streamlit Community Cloud.
"""

from __future__ import annotations

import oracledb
import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_pool() -> oracledb.ConnectionPool:
    return oracledb.create_pool(
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASS"],
        dsn=st.secrets["DB_DSN"],
        min=1,
        max=4,          # bem abaixo do limite de 20 do Always Free
        increment=1,
        timeout=60,
        getmode=oracledb.POOL_GETMODE_WAIT,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Executa consulta e devolve DataFrame com colunas em minúsculas."""
    with get_pool().acquire() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, params or {})
            colunas = [c[0].lower() for c in cursor.description]
            dados = cursor.fetchall()
    return pd.DataFrame(dados, columns=colunas)


def executar_sem_cache(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Versão sem cache, para consultas geradas dinamicamente pelo Select AI."""
    with get_pool().acquire() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, params or {})
            colunas = [c[0].lower() for c in cursor.description]
            dados = cursor.fetchall()
    return pd.DataFrame(dados, columns=colunas)


def testar_conexao() -> tuple[bool, str]:
    try:
        df = query("SELECT 1 AS ok FROM dual")
        return (not df.empty), "Conectado"
    except Exception as erro:
        return False, str(erro)


# ---------------------------------------------------------------------
# Auxiliar de filtro
# ---------------------------------------------------------------------

def _filtrar(sql: str, params: dict, regiao=None, uf=None, porte=None,
             alias: str = "") -> tuple[str, dict]:
    """Acrescenta as cláusulas de recorte territorial à consulta."""
    p = f"{alias}." if alias else ""
    if regiao:
        sql += f" AND {p}regiao = :regiao"
        params["regiao"] = regiao
    if uf:
        sql += f" AND {p}uf = :uf"
        params["uf"] = uf
    if porte:
        sql += f" AND {p}porte_municipio = :porte"
        params["porte"] = porte
    return sql, params


# ---------------------------------------------------------------------
# Listas para os filtros
# ---------------------------------------------------------------------

@st.cache_data(ttl=3600)
def listar_competencias() -> list[str]:
    return query("SELECT competencia FROM silver_tempo ORDER BY competencia")["competencia"].tolist()


@st.cache_data(ttl=3600)
def listar_regioes() -> list[str]:
    return query(
        "SELECT DISTINCT regiao FROM silver_municipio WHERE regiao IS NOT NULL ORDER BY regiao"
    )["regiao"].tolist()


@st.cache_data(ttl=3600)
def listar_ufs(regiao: str | None = None) -> list[str]:
    sql = "SELECT DISTINCT uf FROM silver_municipio WHERE uf IS NOT NULL"
    params: dict = {}
    if regiao:
        sql += " AND regiao = :regiao"
        params["regiao"] = regiao
    return query(sql + " ORDER BY uf", params)["uf"].tolist()


# =====================================================================
# PÁGINA 1 · Visão geral da rede
# =====================================================================

@st.cache_data(ttl=3600)
def indicadores_gerais(competencia: str, regiao=None, uf=None) -> pd.Series:
    """Cartões do topo. Agrega direto do fato para respeitar o recorte."""
    sql = """
        SELECT
          SUM(internacoes)                                              AS internacoes,
          SUM(leitos_sus)                                               AS leitos_sus,
          SUM(obitos)                                                   AS obitos,
          SUM(valor_total)                                              AS valor_total,
          SUM(populacao)                                                AS populacao,
          COUNT(*)                                                      AS municipios,
          SUM(sem_leito_sus)                                            AS municipios_sem_leito,
          SUM(sem_producao_hospitalar)                                  AS municipios_sem_producao,
          ROUND(SUM(dias_permanencia) / NULLIF(SUM(internacoes), 0), 1) AS permanencia_media,
          ROUND(SUM(obitos) * 100 / NULLIF(SUM(internacoes), 0), 2)     AS taxa_mortalidade,
          ROUND(SUM(leitos_sus) * 10000 / NULLIF(SUM(populacao), 0), 2) AS leitos_por_10mil,
          -- Ocupação estimada: dias de permanência sobre dias-leito do mês.
          -- É aproximação; o SIH não informa data exata de ocupação.
          ROUND(SUM(dias_permanencia) * 100
                / NULLIF(SUM(leitos_sus) * 30, 0), 1)                   AS ocupacao_estimada
        FROM gold_fato_municipio
        WHERE competencia = :comp
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao, uf)
    df = query(sql, params)
    return df.iloc[0] if not df.empty else pd.Series(dtype="object")


@st.cache_data(ttl=3600)
def variacao_anterior(competencia: str, regiao=None, uf=None) -> pd.Series:
    """Mesmos indicadores na competência anterior, para o delta dos cartões."""
    anteriores = [c for c in listar_competencias() if c < competencia]
    if not anteriores:
        return pd.Series(dtype="object")
    return indicadores_gerais(anteriores[-1], regiao, uf)


@st.cache_data(ttl=3600)
def internacoes_por_regiao(competencia: str) -> pd.DataFrame:
    return query(
        """
        SELECT regiao, SUM(internacoes) AS internacoes, SUM(leitos_sus) AS leitos_sus
          FROM gold_fato_municipio
         WHERE competencia = :comp AND regiao IS NOT NULL
         GROUP BY regiao
         ORDER BY internacoes DESC
        """,
        {"comp": competencia},
    )


@st.cache_data(ttl=3600)
def internacoes_por_uf(competencia: str, regiao=None) -> pd.DataFrame:
    sql = """
        SELECT uf, estado, regiao, internacoes, leitos_sus, populacao,
               municipios, municipios_sem_leito, pct_municipios_sem_leito,
               permanencia_media, leitos_por_10mil_hab
          FROM gold_ranking_uf
         WHERE competencia = :comp
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao)
    return query(sql + " ORDER BY internacoes DESC", params)


@st.cache_data(ttl=3600)
def evolucao_mensal(regiao=None, uf=None) -> pd.DataFrame:
    sql = """
        SELECT competencia,
               SUM(internacoes)                                              AS internacoes,
               SUM(obitos)                                                   AS obitos,
               SUM(leitos_sus)                                               AS leitos_sus,
               ROUND(SUM(dias_permanencia) / NULLIF(SUM(internacoes), 0), 2) AS permanencia_media,
               ROUND(SUM(obitos) * 100 / NULLIF(SUM(internacoes), 0), 2)     AS taxa_mortalidade
          FROM gold_fato_municipio
         WHERE 1 = 1
    """
    sql, params = _filtrar(sql, {}, regiao, uf)
    return query(sql + " GROUP BY competencia ORDER BY competencia", params)


@st.cache_data(ttl=3600)
def leitos_por_tipo_gestao(competencia: str, regiao=None, uf=None) -> pd.DataFrame:
    """Distribuição dos leitos por natureza da gestão do estabelecimento."""
    sql = """
        SELECT tipo_gestao, SUM(leitos_sus) AS leitos_sus,
               COUNT(DISTINCT cnes) AS estabelecimentos
          FROM gold_hospital
         WHERE competencia = :comp AND leitos_sus > 0
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao, uf)
    return query(sql + " GROUP BY tipo_gestao ORDER BY leitos_sus DESC", params)


# =====================================================================
# PÁGINA 2 · Indicadores de capacidade
# =====================================================================

@st.cache_data(ttl=3600)
def capacidade_x_demanda(competencia: str, regiao=None, uf=None) -> pd.DataFrame:
    """Capacidade instalada contra demanda, por região ou por UF."""
    dimensao = "uf" if (regiao or uf) else "regiao"
    sql = f"""
        SELECT {dimensao} AS dimensao,
               SUM(leitos_sus)                                          AS leitos_sus,
               SUM(internacoes)                                         AS internacoes,
               SUM(dias_permanencia)                                    AS dias_permanencia,
               ROUND(SUM(internacoes) / NULLIF(SUM(leitos_sus), 0), 2)  AS internacoes_por_leito,
               ROUND(SUM(dias_permanencia) * 100
                     / NULLIF(SUM(leitos_sus) * 30, 0), 1)              AS ocupacao_estimada
          FROM gold_fato_municipio
         WHERE competencia = :comp AND {dimensao} IS NOT NULL
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao, uf)
    return query(sql + f" GROUP BY {dimensao} ORDER BY leitos_sus DESC", params)


@st.cache_data(ttl=3600)
def matriz_pressao(competencia: str) -> pd.DataFrame:
    """
    Matriz região x faixa de pressão: quantos municípios em cada célula.

    NOTA DE ESCOPO: a tela de referência usa região x especialidade de
    leito. Isso exigiria TP_LEITO preservado na Silver, o que a extração
    atual agrega antes de gravar. Enquanto essa coluna não existir, a
    matriz usa a faixa do ICPA, que é a dimensão disponível.
    """
    return query(
        """
        SELECT regiao, faixa_pressao,
               COUNT(*)         AS municipios,
               ROUND(AVG(icpa), 1) AS icpa_medio
          FROM gold_icpa_classificado
         WHERE competencia = :comp AND regiao IS NOT NULL
         GROUP BY regiao, faixa_pressao
        """,
        {"comp": competencia},
    )


@st.cache_data(ttl=3600)
def ranking_sobrecarga(competencia: str, regiao=None, uf=None,
                       porte=None, limite: int = 30) -> pd.DataFrame:
    sql = """
        SELECT ranking_nacional, ranking_uf, cod_municipio, municipio, uf, regiao,
               populacao, internacoes, leitos_sus,
               internacoes_por_leito, permanencia_media,
               internacoes_por_10mil_hab, leitos_por_10mil_hab,
               taxa_mortalidade, componente_demanda, componente_uso,
               componente_permanencia, icpa, faixa_pressao, porte_municipio
          FROM gold_icpa_classificado
         WHERE competencia = :comp
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao, uf, porte)
    params["limite"] = limite
    return query(sql + " ORDER BY icpa DESC FETCH FIRST :limite ROWS ONLY", params)


@st.cache_data(ttl=3600)
def distribuicao_faixas(competencia: str, regiao=None, uf=None, porte=None) -> pd.DataFrame:
    sql = """
        SELECT faixa_pressao, COUNT(*) AS municipios,
               SUM(internacoes) AS internacoes, SUM(populacao) AS populacao
          FROM gold_icpa_classificado
         WHERE competencia = :comp
    """
    sql, params = _filtrar(sql, {"comp": competencia}, regiao, uf, porte)
    return query(sql + " GROUP BY faixa_pressao", params)


@st.cache_data(ttl=3600)
def hospitais_criticos(competencia: str, regiao=None, uf=None,
                       minimo_internacoes: int = 50, limite: int = 30) -> pd.DataFrame:
    sql = """
        SELECT cnes, tipo_unidade, tipo_gestao, municipio, uf, regiao,
               internacoes, leitos_sus, internacoes_por_leito,
               permanencia_media, taxa_mortalidade, ocupacao_estimada_pct
          FROM gold_hospital
         WHERE competencia = :comp
           AND leitos_sus > 0
           AND internacoes >= :minimo
    """
    sql, params = _filtrar(sql, {"comp": competencia, "minimo": minimo_internacoes}, regiao, uf)
    params["limite"] = limite
    return query(sql + " ORDER BY internacoes_por_leito DESC FETCH FIRST :limite ROWS ONLY", params)


@st.cache_data(ttl=3600)
def vazios_assistenciais(competencia: str, regiao=None, uf=None,
                         populacao_minima: int = 10000, limite: int = 40) -> pd.DataFrame:
    """Municípios sem nenhum leito SUS, com a evasão correspondente."""
    sql = """
        SELECT f.municipio, f.uf, f.regiao, f.populacao,
               f.internacoes_residentes,
               e.taxa_evasao, e.municipio_destino, e.uf_destino
          FROM gold_fato_municipio f
          LEFT JOIN gold_evasao e
                 ON e.cod_municipio = f.cod_municipio
                AND e.competencia   = f.competencia
         WHERE f.competencia = :comp
           AND f.sem_leito_sus = 1
           AND f.populacao >= :popmin
    """
    sql, params = _filtrar(
        sql, {"comp": competencia, "popmin": populacao_minima}, regiao, uf, alias="f"
    )
    params["limite"] = limite
    return query(sql + " ORDER BY f.populacao DESC FETCH FIRST :limite ROWS ONLY", params)


@st.cache_data(ttl=3600)
def evasao(competencia: str, regiao=None, uf=None,
           minimo: int = 100, limite: int = 30) -> pd.DataFrame:
    sql = """
        SELECT municipio, uf, regiao, populacao, internacoes_residentes,
               internacoes_fora, taxa_evasao, valor_fora,
               municipio_destino, uf_destino, internacoes_destino
          FROM gold_evasao
         WHERE competencia = :comp
           AND internacoes_residentes >= :minimo
    """
    sql, params = _filtrar(sql, {"comp": competencia, "minimo": minimo}, regiao, uf)
    params["limite"] = limite
    return query(sql + " ORDER BY taxa_evasao DESC FETCH FIRST :limite ROWS ONLY", params)


@st.cache_data(ttl=3600)
def procedimentos(competencia: str, limite: int = 20) -> pd.DataFrame:
    return query(
        """
        SELECT procedimento, grupo, complexidade, internacoes,
               permanencia_media, valor_medio, taxa_mortalidade
          FROM gold_procedimento
         WHERE competencia = :comp
         ORDER BY internacoes DESC
         FETCH FIRST :limite ROWS ONLY
        """,
        {"comp": competencia, "limite": limite},
    )
