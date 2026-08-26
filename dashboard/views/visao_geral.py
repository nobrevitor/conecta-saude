"""
Página 1 · Visão geral da rede

Panorama da rede hospitalar: volume, capacidade instalada e distribuição
territorial. Responde "como está a rede" antes de "onde está o problema",
que é assunto da página de capacidade.

As visualizações estão marcadas como PLACEHOLDER: a estrutura, as
consultas e o fluxo de dados estão prontos; falta escolher a forma
gráfica de cada bloco.
"""

import streamlit as st

import db
import ui

ui.cabecalho(
    "Visão geral da rede",
    "Panorama da rede hospitalar · dados públicos do SUS (DATASUS)",
)

filtros = ui.barra_filtros(mostrar_porte=False)

# ---------------------------------------------------------------------
# Cartões de indicador
# ---------------------------------------------------------------------

atual = db.indicadores_gerais(filtros.competencia, filtros.regiao_sql, filtros.uf_sql)
anterior = db.variacao_anterior(filtros.competencia, filtros.regiao_sql, filtros.uf_sql)


def delta(campo: str, casas: int = 1) -> str | None:
    """Variação percentual contra a competência anterior."""
    if anterior.empty or atual.empty:
        return None
    antes, agora = anterior.get(campo), atual.get(campo)
    if not antes or not agora:
        return None
    return f"{(agora - antes) / antes * 100:+.{casas}f}% vs mês anterior"


if atual.empty:
    ui.bloco_vazio()
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Internações", ui.num(atual["internacoes"]), delta("internacoes"))
c2.metric("Leitos SUS", ui.num(atual["leitos_sus"]), delta("leitos_sus"))
c3.metric("Permanência média", f"{ui.num(atual['permanencia_media'], 1)} dias",
          delta("permanencia_media"))
c4.metric("Ocupação estimada", ui.pct(atual["ocupacao_estimada"]),
          delta("ocupacao_estimada"))
c5.metric("Municípios sem leito SUS", ui.num(atual["municipios_sem_leito"]),
          f"{atual['municipios_sem_leito'] / atual['municipios'] * 100:.0f}% do recorte",
          delta_color="inverse")

ui.aviso_metodologico(
    "Ocupação estimada = dias de permanência dividido por leitos vezes 30. "
    "É aproximação: o SIH registra dias de permanência, não a data exata "
    "de ocupação do leito."
)

st.write("")

# ---------------------------------------------------------------------
# Distribuição territorial
# ---------------------------------------------------------------------

esquerda, centro, direita = st.columns([1, 1.2, 1])

with esquerda:
    bloco = ui.painel("Internações por região")
    dados_regiao = db.internacoes_por_regiao(filtros.competencia)
    if dados_regiao.empty:
        bloco.info("Sem dados.")
    else:
        # PLACEHOLDER · barras horizontais ordenadas por volume
        bloco.dataframe(dados_regiao, use_container_width=True, hide_index=True)

with centro:
    bloco = ui.painel("Distribuição por UF")
    dados_uf = db.internacoes_por_uf(filtros.competencia, filtros.regiao_sql)
    if dados_uf.empty:
        bloco.info("Sem dados.")
    else:
        # PLACEHOLDER · mapa coroplético do Brasil por UF.
        # Requer GeoJSON das unidades federativas; a chave de junção é a
        # sigla, já presente em dados_uf["uf"].
        bloco.dataframe(
            dados_uf[["uf", "internacoes", "leitos_sus", "leitos_por_10mil_hab"]],
            use_container_width=True, hide_index=True,
        )

with direita:
    bloco = ui.painel("Leitos por tipo de gestão")
    gestao = db.leitos_por_tipo_gestao(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql
    )
    if gestao.empty:
        bloco.info("Sem dados.")
    else:
        # PLACEHOLDER · barras horizontais com percentual do total
        bloco.dataframe(gestao, use_container_width=True, hide_index=True)

st.write("")

# ---------------------------------------------------------------------
# Série temporal e ranking
# ---------------------------------------------------------------------

coluna_serie, coluna_ranking = st.columns([1.4, 1])

with coluna_serie:
    bloco = ui.painel(
        "Evolução mensal das internações",
        "Doze competências de 2024",
    )
    serie = db.evolucao_mensal(filtros.regiao_sql, filtros.uf_sql)
    if serie.empty:
        bloco.info("Sem dados.")
    else:
        serie["rotulo"] = serie["competencia"].str[4:] + "/" + serie["competencia"].str[:4]
        # PLACEHOLDER · linha com marcadores; avaliar segunda série de
        # permanência média em eixo secundário
        bloco.line_chart(serie.set_index("rotulo")["internacoes"], height=260)

with coluna_ranking:
    bloco = ui.painel("Top UFs por internações")
    if not dados_uf.empty:
        topo = dados_uf.head(10).copy()
        total = topo["internacoes"].sum()
        topo["pct_do_total"] = (topo["internacoes"] / total * 100).round(1)
        # PLACEHOLDER · tabela com barra de progresso na coluna percentual
        bloco.dataframe(
            topo[["uf", "internacoes", "pct_do_total"]],
            use_container_width=True, hide_index=True,
        )

ui.rodape()
