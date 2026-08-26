"""
Página 2 · Indicadores de capacidade

Onde a rede aperta. Confronta capacidade instalada com demanda, ordena
municípios pelo ICPA e expõe os vazios assistenciais.

É a página que sustenta a tese do projeto, e por isso concentra os
indicadores proprietários. As visualizações estão como PLACEHOLDER: a
estrutura, as consultas e o fluxo estão prontos.
"""

import streamlit as st

import db
import ui

ui.cabecalho(
    "Indicadores de capacidade",
    "Capacidade assistencial e risco operacional · dados públicos do SUS",
)

filtros = ui.barra_filtros(mostrar_porte=True)

atual = db.indicadores_gerais(filtros.competencia, filtros.regiao_sql, filtros.uf_sql)

if atual.empty:
    ui.bloco_vazio()
    st.stop()

# ---------------------------------------------------------------------
# Cartões
# ---------------------------------------------------------------------

faixas = db.distribuicao_faixas(
    filtros.competencia, filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
)

criticos = 0
if not faixas.empty:
    linha = faixas.query("faixa_pressao in ['Crítica', 'Alta']")
    criticos = int(linha["municipios"].sum()) if not linha.empty else 0

total_classificados = int(faixas["municipios"].sum()) if not faixas.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Capacidade instalada", f"{ui.num(atual['leitos_sus'])} leitos")
c2.metric("Demanda no período", f"{ui.num(atual['internacoes'])} internações")
c3.metric("Ocupação estimada", ui.pct(atual["ocupacao_estimada"]))
c4.metric(
    "Municípios em pressão alta ou crítica",
    ui.num(criticos),
    f"{criticos / total_classificados * 100:.0f}% dos classificados"
    if total_classificados else None,
    delta_color="inverse",
)
c5.metric("Leitos por 10 mil habitantes", ui.num(atual["leitos_por_10mil"], 2))

ui.aviso_metodologico(
    "Municípios sem leito SUS ou sem produção hospitalar ficam fora do ICPA: "
    "ausência de serviço não é pressão baixa. Eles aparecem na seção de "
    "vazios assistenciais, mais abaixo."
)

st.write("")

# ---------------------------------------------------------------------
# Capacidade contra demanda, e matriz de pressão
# ---------------------------------------------------------------------

coluna_a, coluna_b, coluna_c = st.columns([1.2, 1.2, 1])

with coluna_a:
    bloco = ui.painel(
        "Capacidade instalada e demanda",
        "Leitos SUS contra internações realizadas",
    )
    capacidade = db.capacidade_x_demanda(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql
    )
    if capacidade.empty:
        bloco.info("Sem dados.")
    else:
        # PLACEHOLDER · barras agrupadas, leitos e internações lado a lado,
        # com a taxa de utilização como rótulo
        bloco.dataframe(capacidade, use_container_width=True, hide_index=True)

with coluna_b:
    bloco = ui.painel(
        "Matriz de pressão por região",
        "Municípios em cada faixa do ICPA",
    )
    matriz = db.matriz_pressao(filtros.competencia)
    if matriz.empty:
        bloco.info("Sem dados.")
    else:
        # PLACEHOLDER · mapa de calor região por faixa, escala do verde ao
        # vermelho, com a contagem de municípios em cada célula
        tabela = matriz.pivot(
            index="regiao", columns="faixa_pressao", values="municipios"
        ).fillna(0).astype(int)
        bloco.dataframe(tabela, use_container_width=True)

    # NOTA DE ESCOPO
    # A tela de referência usa região por especialidade de leito. Isso
    # exigiria TP_LEITO preservado na Silver, e a extração atual agrega
    # essa coluna antes de gravar. Enquanto ela não existir, a matriz usa
    # a faixa do ICPA, que é a dimensão disponível.

with coluna_c:
    bloco = ui.painel("Leitura dos números")
    if not faixas.empty:
        for _, linha in faixas.sort_values("municipios", ascending=False).iterrows():
            bloco.markdown(
                f"**{linha['faixa_pressao']}** · {ui.num(linha['municipios'])} municípios  \n"
                f":grey[{ui.num(linha['internacoes'])} internações]"
            )
    # PLACEHOLDER · substituir por insights automáticos derivados dos
    # dados, no formato da tela de referência

st.write("")

# ---------------------------------------------------------------------
# Ranking de sobrecarga
# ---------------------------------------------------------------------

bloco = ui.painel(
    "Ranking de sobrecarga",
    "Municípios ordenados pelo Índice Composto de Pressão Assistencial",
)

with bloco:
    ranking = db.ranking_sobrecarga(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql,
        filtros.porte_sql, limite=30,
    )
    if ranking.empty:
        ui.bloco_vazio()
    else:
        # PLACEHOLDER · barras horizontais coloridas por faixa de pressão
        st.dataframe(
            ranking[[
                "ranking_nacional", "municipio", "uf", "populacao",
                "internacoes", "leitos_sus", "internacoes_por_leito",
                "permanencia_media", "icpa", "faixa_pressao",
            ]],
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "ICPA = 0,35 × demanda relativa + 0,40 × uso da capacidade + "
            "0,25 × tempo de ocupação. Cada componente é normalizado dentro "
            "da competência, com teto no percentil 95."
        )

st.write("")

# ---------------------------------------------------------------------
# Vazios assistenciais e hospitais críticos
# ---------------------------------------------------------------------

coluna_vazios, coluna_hospitais = st.columns(2)

with coluna_vazios:
    bloco = ui.painel(
        "Vazios assistenciais",
        "Municípios sem nenhum leito SUS e com mais de 10 mil habitantes",
    )
    vazios = db.vazios_assistenciais(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql
    )
    if vazios.empty:
        bloco.info("Nenhum município nesta condição no recorte.")
    else:
        # PLACEHOLDER · tabela com destaque para taxa de evasão elevada
        bloco.dataframe(vazios, use_container_width=True, hide_index=True)

with coluna_hospitais:
    bloco = ui.painel(
        "Estabelecimentos sob maior pressão",
        "Internações por leito, entre hospitais com 50 ou mais internações",
    )
    hospitais = db.hospitais_criticos(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql
    )
    if hospitais.empty:
        bloco.info("Sem hospitais que atendam aos critérios.")
    else:
        # PLACEHOLDER · dispersão de leitos por internações por leito,
        # tamanho pelo volume e cor pela permanência média
        bloco.dataframe(
            hospitais[[
                "cnes", "municipio", "uf", "internacoes", "leitos_sus",
                "internacoes_por_leito", "permanencia_media",
                "ocupacao_estimada_pct",
            ]],
            use_container_width=True, hide_index=True,
        )

st.write("")

# ---------------------------------------------------------------------
# Evasão
# ---------------------------------------------------------------------

bloco = ui.painel(
    "Deslocamento de pacientes",
    "Internações de moradores que ocorreram fora do município de residência",
)

with bloco:
    dados_evasao = db.evasao(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql, minimo=100
    )
    if dados_evasao.empty:
        ui.bloco_vazio()
    else:
        # PLACEHOLDER · barras horizontais, ou mapa de fluxo origem-destino
        st.dataframe(
            dados_evasao[[
                "municipio", "uf", "populacao", "internacoes_residentes",
                "internacoes_fora", "taxa_evasao", "municipio_destino",
            ]],
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Considera apenas municípios com pelo menos 100 internações de "
            "residentes no período, para evitar distorção por volume baixo."
        )

ui.rodape()
