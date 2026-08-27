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
# Auxiliares de filtro
# ---------------------------------------------------------------------
#
# COMPETÊNCIA = None SIGNIFICA "TODAS", E O RECORTE VIRA MÉDIA MENSAL
#
# Somar doze meses e apresentar o total responderia outra pergunta. Pior:
# leito não é grandeza que soma entre meses — os 62 mil leitos de SP em
# janeiro são os mesmos de fevereiro, e somá-los daria 750 mil. A média
# mensal é o único agregado que preserva o significado das duas famílias
# de medida ao mesmo tempo.
#
# As RAZÕES não precisam de tratamento, e vale entender por quê: todas
# aqui são escritas como SUM(a) / SUM(b). Ao abrir o filtro para o ano,
# numerador e denominador passam a somar doze meses cada, o fator doze
# aparece dos dois lados e se cancela. O resultado já é a média ponderada
# do período — que é mais correta que a média das médias mensais, porque
# pesa cada mês pelo próprio volume.
#
# Contagens de ENTIDADE são o caso que engana: COUNT(*) sobre doze meses
# conta município-mês, não município. Essas viram COUNT(DISTINCT chave)
# ou média mensal, conforme a pergunta que o número responde.


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


def _competencia(sql: str, params: dict, competencia: str | None,
                 alias: str = "") -> tuple[str, dict]:
    """Filtra um mês, ou nenhum filtro quando competencia é None."""
    if competencia:
        p = f"{alias}." if alias else ""
        sql += f" AND {p}competencia = :comp"
        params["comp"] = competencia
    return sql, params


def _por_mes(expressao: str, competencia: str | None) -> str:
    """
    Média mensal quando o recorte é o ano inteiro, valor cru quando é um
    mês só. O divisor sai dos próprios dados, e não de uma constante 12,
    para acompanhar o recorte: se um filtro deixar oito meses, divide por
    oito.
    """
    if competencia:
        return expressao
    return f"({expressao}) / NULLIF(COUNT(DISTINCT competencia), 0)"


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
def indicadores_gerais(competencia: str | None, regiao=None, uf=None) -> pd.Series:
    """
    Cartões do topo. Agrega direto do fato para respeitar o recorte.

    Com competencia=None os volumes viram média mensal; as razões já saem
    certas sem tratamento, porque numerador e denominador somam o mesmo
    número de meses. `municipios` passa a contar município distinto, e
    não município-mês.
    """
    sql = f"""
        SELECT
          {_por_mes("SUM(internacoes)", competencia)}                    AS internacoes,
          {_por_mes("SUM(leitos_sus)", competencia)}                     AS leitos_sus,
          {_por_mes("SUM(obitos)", competencia)}                         AS obitos,
          {_por_mes("SUM(valor_total)", competencia)}                    AS valor_total,
          {_por_mes("SUM(populacao)", competencia)}                      AS populacao,
          COUNT(DISTINCT cod_municipio)                                 AS municipios,
          {_por_mes("SUM(sem_leito_sus)", competencia)}                  AS municipios_sem_leito,
          {_por_mes("SUM(sem_producao_hospitalar)", competencia)}        AS municipios_sem_producao,
          ROUND(SUM(dias_permanencia) / NULLIF(SUM(internacoes), 0), 1) AS permanencia_media,
          ROUND(SUM(obitos) * 100 / NULLIF(SUM(internacoes), 0), 2)     AS taxa_mortalidade,
          ROUND(SUM(leitos_sus) * 10000 / NULLIF(SUM(populacao), 0), 2) AS leitos_por_10mil,
          -- Ocupação estimada: dias de permanência sobre dias-leito do mês.
          -- É aproximação; o SIH não informa data exata de ocupação.
          ROUND(SUM(dias_permanencia) * 100
                / NULLIF(SUM(leitos_sus) * 30, 0), 1)                   AS ocupacao_estimada
        FROM gold_fato_municipio
        WHERE 1 = 1
    """
    sql, params = _competencia(sql, {}, competencia)
    sql, params = _filtrar(sql, params, regiao, uf)
    df = query(sql, params)
    return df.iloc[0] if not df.empty else pd.Series(dtype="object")


@st.cache_data(ttl=3600)
def variacao_anterior(competencia: str | None, regiao=None, uf=None) -> pd.Series:
    """
    Mesmos indicadores na competência anterior, para o delta dos cartões.

    Sem competência escolhida não existe período anterior: o recorte já é
    o ano inteiro. Devolve vazio, e os cartões saem sem variação — o que
    é a leitura honesta, e não um delta contra um mês arbitrário.
    """
    if not competencia:
        return pd.Series(dtype="object")
    anteriores = [c for c in listar_competencias() if c < competencia]
    if not anteriores:
        return pd.Series(dtype="object")
    return indicadores_gerais(anteriores[-1], regiao, uf)


@st.cache_data(ttl=3600)
def internacoes_por_regiao(competencia: str | None) -> pd.DataFrame:
    sql = f"""
        SELECT regiao,
               {_por_mes("SUM(internacoes)", competencia)} AS internacoes,
               {_por_mes("SUM(leitos_sus)", competencia)}  AS leitos_sus
          FROM gold_fato_municipio
         WHERE regiao IS NOT NULL
    """
    sql, params = _competencia(sql, {}, competencia)
    return query(sql + " GROUP BY regiao ORDER BY internacoes DESC", params)


@st.cache_data(ttl=3600)
def internacoes_por_uf(competencia: str | None, regiao=None) -> pd.DataFrame:
    """
    Agregado por UF. Com competencia=None cada volume vira média mensal e
    as razões são RECALCULADAS a partir dos componentes somados — nunca
    pela média das razões mensais, que ignoraria o peso de cada mês.

    A permanência média é o caso que exige atenção: a Gold por UF guarda
    a média, não o total de dias. O total é reconstruído multiplicando-a
    pelas internações do mês, que é a definição dela.
    """
    sql = f"""
        SELECT uf, MAX(estado) AS estado, MAX(regiao) AS regiao,
               {_por_mes("SUM(internacoes)", competencia)}  AS internacoes,
               {_por_mes("SUM(leitos_sus)", competencia)}   AS leitos_sus,
               {_por_mes("SUM(populacao)", competencia)}    AS populacao,
               MAX(municipios)                             AS municipios,
               {_por_mes("SUM(municipios_sem_leito)", competencia)}
                                                           AS municipios_sem_leito,
               ROUND(SUM(municipios_sem_leito) * 100
                     / NULLIF(SUM(municipios), 0), 1)      AS pct_municipios_sem_leito,
               ROUND(SUM(internacoes * permanencia_media)
                     / NULLIF(SUM(internacoes), 0), 1)     AS permanencia_media,
               ROUND(SUM(leitos_sus) * 10000
                     / NULLIF(SUM(populacao), 0), 2)       AS leitos_por_10mil_hab,
               -- Demanda medida contra a capacidade instalada, e não em
               -- volume: dias-leito consumidos sobre dias-leito ofertados
               -- no mês. É o que permite comparar SP com RR na mesma
               -- escala. Mesma fórmula de indicadores_gerais, aqui
               -- reconstruída porque a Gold por UF guarda a permanência
               -- média em vez do total de dias.
               ROUND(SUM(internacoes * permanencia_media) * 100
                     / NULLIF(SUM(leitos_sus) * 30, 0), 1)     AS ocupacao_estimada
          FROM gold_ranking_uf
         WHERE uf IS NOT NULL
           -- A Gold traz uma linha de UF nula por competência, resíduo de
           -- código de município sem correspondência na tabela do IBGE.
           -- Numa visão por UF ela não é uma UF: entraria no mapa sem
           -- geometria e no ranking como se fosse um estado a mais.
    """
    sql, params = _competencia(sql, {}, competencia)
    sql, params = _filtrar(sql, params, regiao)
    return query(sql + " GROUP BY uf ORDER BY internacoes DESC", params)


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
def leitos_por_tipo_gestao(competencia: str | None, regiao=None,
                           uf=None) -> pd.DataFrame:
    """Distribuição dos leitos por natureza da gestão do estabelecimento."""
    sql = f"""
        SELECT tipo_gestao,
               {_por_mes("SUM(leitos_sus)", competencia)} AS leitos_sus,
               COUNT(DISTINCT cnes)                      AS estabelecimentos
          FROM gold_hospital
         WHERE leitos_sus > 0
    """
    sql, params = _competencia(sql, {}, competencia)
    sql, params = _filtrar(sql, params, regiao, uf)
    return query(sql + " GROUP BY tipo_gestao ORDER BY leitos_sus DESC", params)


# =====================================================================
# PÁGINA 2 · Indicadores de capacidade
# =====================================================================

@st.cache_data(ttl=3600)
def capacidade_x_demanda(competencia: str | None, regiao=None,
                         uf=None) -> pd.DataFrame:
    """Capacidade instalada contra demanda, por região ou por UF."""
    dimensao = "uf" if (regiao or uf) else "regiao"
    sql = f"""
        SELECT {dimensao} AS dimensao,
               {_por_mes("SUM(leitos_sus)", competencia)}                AS leitos_sus,
               {_por_mes("SUM(internacoes)", competencia)}               AS internacoes,
               {_por_mes("SUM(dias_permanencia)", competencia)}          AS dias_permanencia,
               ROUND(SUM(internacoes) / NULLIF(SUM(leitos_sus), 0), 2)  AS internacoes_por_leito,
               ROUND(SUM(dias_permanencia) * 100
                     / NULLIF(SUM(leitos_sus) * 30, 0), 1)              AS ocupacao_estimada
          FROM gold_fato_municipio
         WHERE {dimensao} IS NOT NULL
    """
    sql, params = _competencia(sql, {}, competencia)
    sql, params = _filtrar(sql, params, regiao, uf)
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
    sql = f"""
        SELECT regiao, faixa_pressao,
               ROUND({_por_mes("COUNT(*)", competencia)}) AS municipios,
               ROUND(AVG(icpa), 1)                       AS icpa_medio
          FROM gold_icpa_classificado
         WHERE regiao IS NOT NULL
    """
    sql, params = _competencia(sql, {}, competencia)
    return query(sql + " GROUP BY regiao, faixa_pressao", params)


@st.cache_data(ttl=3600)
def ranking_sobrecarga(competencia: str | None, regiao=None, uf=None,
                       porte=None, limite: int = 30) -> pd.DataFrame:
    """
    Municípios ordenados pelo ICPA.

    Com o ano inteiro, o índice de cada município vira a média dos meses
    em que ele apareceu, e o ranking é RECALCULADO sobre essa média. Não
    dá para reaproveitar ranking_nacional da Gold: ele é a posição dentro
    de UMA competência, e a média de doze posições não é uma posição.

    A faixa também é recalculada, pelos mesmos cortes do 03_gold.sql —
    caso contrário um município com meses críticos e meses baixos herdaria
    a faixa de um mês qualquer.
    """
    if competencia:
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

    sql = """
        SELECT cod_municipio, MAX(municipio) AS municipio, MAX(uf) AS uf,
               MAX(regiao) AS regiao, MAX(porte_municipio) AS porte_municipio,
               ROUND(AVG(populacao))                        AS populacao,
               ROUND(AVG(internacoes))                      AS internacoes,
               ROUND(AVG(leitos_sus))                       AS leitos_sus,
               ROUND(SUM(internacoes) / NULLIF(SUM(leitos_sus), 0), 2)
                                                            AS internacoes_por_leito,
               ROUND(SUM(internacoes * permanencia_media)
                     / NULLIF(SUM(internacoes), 0), 1)      AS permanencia_media,
               ROUND(AVG(internacoes_por_10mil_hab), 1)     AS internacoes_por_10mil_hab,
               ROUND(SUM(leitos_sus) * 10000
                     / NULLIF(SUM(populacao), 0), 2)        AS leitos_por_10mil_hab,
               ROUND(SUM(obitos_estimados) * 100
                     / NULLIF(SUM(internacoes), 0), 2)      AS taxa_mortalidade,
               ROUND(AVG(componente_demanda), 4)            AS componente_demanda,
               ROUND(AVG(componente_uso), 4)                AS componente_uso,
               ROUND(AVG(componente_permanencia), 4)        AS componente_permanencia,
               ROUND(AVG(icpa), 2)                          AS icpa,
               COUNT(*)                                     AS meses
          FROM (
            SELECT c.*, c.internacoes * c.taxa_mortalidade / 100 AS obitos_estimados
              FROM gold_icpa_classificado c
             WHERE 1 = 1
    """
    sql, params = _filtrar(sql, {}, regiao, uf, porte, alias="c")
    sql += """
          )
         GROUP BY cod_municipio
    """
    params["limite"] = limite
    dados = query(
        sql + " ORDER BY icpa DESC FETCH FIRST :limite ROWS ONLY", params
    )
    if dados.empty:
        return dados

    dados = dados.copy()
    dados.insert(0, "ranking_nacional", range(1, len(dados) + 1))
    dados["ranking_uf"] = (
        dados.groupby("uf")["icpa"].rank(method="min", ascending=False).astype(int)
    )
    dados["faixa_pressao"] = pd.cut(
        dados["icpa"], bins=[-0.01, 20, 40, 60, 1000],
        labels=["Baixa", "Moderada", "Alta", "Crítica"],
    ).astype(str)
    return dados


@st.cache_data(ttl=3600)
def distribuicao_faixas(competencia: str | None, regiao=None, uf=None,
                        porte=None) -> pd.DataFrame:
    """
    Municípios por faixa do ICPA.

    Com o ano inteiro a contagem vira média mensal, e não COUNT(DISTINCT):
    um município muda de faixa ao longo do ano, então contá-lo uma vez por
    faixa somaria mais municípios do que existem.
    """
    sql = f"""
        SELECT faixa_pressao,
               ROUND({_por_mes("COUNT(*)", competencia)})        AS municipios,
               {_por_mes("SUM(internacoes)", competencia)}       AS internacoes,
               {_por_mes("SUM(populacao)", competencia)}         AS populacao
          FROM gold_icpa_classificado
         WHERE 1 = 1
    """
    sql, params = _competencia(sql, {}, competencia)
    sql, params = _filtrar(sql, params, regiao, uf, porte)
    return query(sql + " GROUP BY faixa_pressao", params)


@st.cache_data(ttl=3600)
def hospitais_criticos(competencia: str | None, regiao=None, uf=None,
                       minimo_internacoes: int = 50,
                       limite: int = 30) -> pd.DataFrame:
    """
    Estabelecimentos com maior giro de leito.

    Com o ano inteiro, o mínimo de internações passa a valer sobre a média
    mensal, e não sobre o total do ano — senão o filtro deixaria de excluir
    o volume baixo que ele existe para excluir.
    """
    if competencia:
        sql = """
            SELECT cnes, tipo_unidade, tipo_gestao, municipio, uf, regiao,
                   internacoes, leitos_sus, internacoes_por_leito,
                   permanencia_media, taxa_mortalidade, ocupacao_estimada_pct
              FROM gold_hospital
             WHERE competencia = :comp
               AND leitos_sus > 0
               AND internacoes >= :minimo
        """
        sql, params = _filtrar(
            sql, {"comp": competencia, "minimo": minimo_internacoes}, regiao, uf
        )
        params["limite"] = limite
        return query(
            sql + " ORDER BY internacoes_por_leito DESC FETCH FIRST :limite ROWS ONLY",
            params,
        )

    sql = """
        SELECT cnes, MAX(tipo_unidade) AS tipo_unidade,
               MAX(tipo_gestao) AS tipo_gestao, MAX(municipio) AS municipio,
               MAX(uf) AS uf, MAX(regiao) AS regiao,
               ROUND(SUM(internacoes) / COUNT(DISTINCT competencia))   AS internacoes,
               ROUND(SUM(leitos_sus) / COUNT(DISTINCT competencia))    AS leitos_sus,
               ROUND(SUM(internacoes) / NULLIF(SUM(leitos_sus), 0), 2) AS internacoes_por_leito,
               ROUND(SUM(dias_permanencia)
                     / NULLIF(SUM(internacoes), 0), 1)                 AS permanencia_media,
               ROUND(SUM(obitos) * 100
                     / NULLIF(SUM(internacoes), 0), 2)                 AS taxa_mortalidade,
               ROUND(SUM(dias_permanencia) * 100
                     / NULLIF(SUM(leitos_sus) * 30, 0), 1)             AS ocupacao_estimada_pct
          FROM gold_hospital
         WHERE leitos_sus > 0
    """
    sql, params = _filtrar(sql, {"minimo": minimo_internacoes}, regiao, uf)
    sql += """
         GROUP BY cnes
        HAVING SUM(internacoes) / COUNT(DISTINCT competencia) >= :minimo
    """
    params["limite"] = limite
    return query(
        sql + " ORDER BY internacoes_por_leito DESC FETCH FIRST :limite ROWS ONLY",
        params,
    )


@st.cache_data(ttl=3600)
def vazios_assistenciais(competencia: str | None, regiao=None, uf=None,
                         populacao_minima: int = 10000,
                         limite: int = 40) -> pd.DataFrame:
    """
    Municípios sem nenhum leito SUS, com a evasão correspondente.

    Repare que o JOIN casa cod_municipio E competencia: sem a segunda
    coluna cada município do fato cruzaria com os doze meses da evasão.
    No recorte de um mês só o erro passaria despercebido; com o ano
    inteiro ele multiplicaria as linhas por doze.

    Com o ano inteiro, entra quem ficou sem leito em ALGUM mês, e a
    coluna meses_sem_leito diz em quantos — perder essa distinção trataria
    igual o município que nunca teve leito e o que perdeu o único em
    dezembro.
    """
    if competencia:
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
            sql, {"comp": competencia, "popmin": populacao_minima}, regiao, uf,
            alias="f",
        )
        params["limite"] = limite
        return query(
            sql + " ORDER BY f.populacao DESC FETCH FIRST :limite ROWS ONLY", params
        )

    sql = """
        SELECT MAX(f.municipio) AS municipio, MAX(f.uf) AS uf,
               MAX(f.regiao) AS regiao,
               ROUND(AVG(f.populacao))                            AS populacao,
               ROUND(SUM(f.internacoes_residentes)
                     / COUNT(DISTINCT f.competencia))             AS internacoes_residentes,
               COUNT(*)                                           AS meses_sem_leito,
               ROUND(SUM(e.internacoes_fora) * 100
                     / NULLIF(SUM(e.internacoes_residentes), 0), 1) AS taxa_evasao,
               MAX(e.municipio_destino) KEEP (
                   DENSE_RANK LAST ORDER BY e.internacoes_destino) AS municipio_destino,
               MAX(e.uf_destino) KEEP (
                   DENSE_RANK LAST ORDER BY e.internacoes_destino) AS uf_destino
          FROM gold_fato_municipio f
          LEFT JOIN gold_evasao e
                 ON e.cod_municipio = f.cod_municipio
                AND e.competencia   = f.competencia
         WHERE f.sem_leito_sus = 1
           AND f.populacao >= :popmin
    """
    sql, params = _filtrar(sql, {"popmin": populacao_minima}, regiao, uf, alias="f")
    sql += " GROUP BY f.cod_municipio"
    params["limite"] = limite
    return query(
        sql + " ORDER BY populacao DESC FETCH FIRST :limite ROWS ONLY", params
    )


@st.cache_data(ttl=3600)
def evasao(competencia: str | None, regiao=None, uf=None,
           minimo: int = 100, limite: int = 30) -> pd.DataFrame:
    """
    Deslocamento de pacientes por município de origem.

    Com o ano inteiro a taxa é recalculada sobre os totais do periodo, e
    o destino principal passa a ser o que mais recebeu no acumulado — a
    moda dos doze meses, e não o destino de um mês qualquer.
    """
    if competencia:
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
        return query(
            sql + " ORDER BY taxa_evasao DESC FETCH FIRST :limite ROWS ONLY", params
        )

    sql = """
        SELECT cod_municipio, MAX(municipio) AS municipio, MAX(uf) AS uf,
               MAX(regiao) AS regiao,
               ROUND(AVG(populacao))                              AS populacao,
               ROUND(SUM(internacoes_residentes)
                     / COUNT(DISTINCT competencia))               AS internacoes_residentes,
               ROUND(SUM(internacoes_fora)
                     / COUNT(DISTINCT competencia))               AS internacoes_fora,
               ROUND(SUM(internacoes_fora) * 100
                     / NULLIF(SUM(internacoes_residentes), 0), 1) AS taxa_evasao,
               ROUND(SUM(valor_fora)
                     / COUNT(DISTINCT competencia), 2)            AS valor_fora,
               MAX(municipio_destino) KEEP (
                   DENSE_RANK LAST ORDER BY internacoes_destino)  AS municipio_destino,
               MAX(uf_destino) KEEP (
                   DENSE_RANK LAST ORDER BY internacoes_destino)  AS uf_destino,
               ROUND(SUM(internacoes_destino)
                     / COUNT(DISTINCT competencia))               AS internacoes_destino
          FROM gold_evasao
         WHERE 1 = 1
    """
    sql, params = _filtrar(sql, {"minimo": minimo}, regiao, uf)
    sql += """
         GROUP BY cod_municipio
        HAVING SUM(internacoes_residentes)
               / COUNT(DISTINCT competencia) >= :minimo
    """
    params["limite"] = limite
    return query(
        sql + " ORDER BY taxa_evasao DESC FETCH FIRST :limite ROWS ONLY", params
    )


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
