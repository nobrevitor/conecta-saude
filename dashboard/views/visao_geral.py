"""
Página 1 · Visão geral da rede

Panorama da rede hospitalar: volume, capacidade instalada e distribuição
territorial. Responde "como está a rede" antes de "onde está o problema",
que é assunto da página de capacidade.

Arranjo em grade: fita de indicadores, uma linha de três cartões com o
recorte territorial e uma linha de dois com a série no tempo. As alturas
saem das constantes de ui para as linhas ficarem alinhadas.
"""

import streamlit as st

import db
import ui

filtros = ui.painel_filtros(mostrar_porte=False)

ui.cabecalho(
    "Visão geral da rede",
    "Panorama da rede hospitalar · dados públicos do SUS (DATASUS)",
    filtros,
)

# ---------------------------------------------------------------------
# Fita de indicadores
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
    return f"{(agora - antes) / antes * 100:+.{casas}f}%"


if atual.empty:
    ui.bloco_vazio()
    st.stop()

ui.fita_indicadores([
    {"label": "Internações", "value": ui.num(atual["internacoes"]),
     "delta": delta("internacoes"),
     "help": "Autorizações de internação hospitalar pagas na competência. "
             "Variação contra a competência anterior."},
    {"label": "Leitos SUS", "value": ui.num(atual["leitos_sus"]),
     "delta": delta("leitos_sus"),
     "help": "Leitos do CNES disponíveis ao SUS no recorte."},
    {"label": "Permanência média",
     "value": f"{ui.num(atual['permanencia_media'], 1)} dias",
     "delta": delta("permanencia_media"),
     "help": "Dias de permanência divididos pelas internações."},
    {"label": "Ocupação estimada", "value": ui.pct(atual["ocupacao_estimada"]),
     "delta": delta("ocupacao_estimada"),
     "help": "Dias de permanência sobre leitos vezes 30. É aproximação: o "
             "SIH registra dias de permanência, não a data exata de ocupação "
             "do leito."},
    {"label": "Municípios sem leito SUS",
     "value": ui.num(atual["municipios_sem_leito"]),
     "delta": f"{atual['municipios_sem_leito'] / atual['municipios'] * 100:.0f}%"
              " do recorte",
     "delta_color": "inverse",
     "help": "Municípios sem nenhum leito SUS cadastrado no CNES."},
])

# ---------------------------------------------------------------------
# Linha 1 · recorte territorial
# ---------------------------------------------------------------------

mapa_col, regiao_col, gestao_col = st.columns([1.25, 1, 1], gap="small")
altura_grafico = ui.altura_util(ui.ALTURA_CARTAO)

with mapa_col:
    bloco = ui.painel(
        "Ocupação por UF", "Demanda contra os leitos de cada estado",
        chave="mapa_uf", altura=ui.ALTURA_CARTAO,
    )
    dados_uf = db.internacoes_por_uf(filtros.competencia, filtros.regiao_sql)
    if dados_uf.empty:
        bloco.info("Sem dados.")
    else:
        mapa = dados_uf.assign(
            rot_por_10mil=lambda d: d["leitos_por_10mil_hab"].map(
                lambda v: ui.num(v, 2)),
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
        )
        altura_mapa = altura_grafico - 58
        deck, legenda = ui.mapa_uf(
            mapa, "ocupacao_estimada",
            [("rot_por_10mil", "Leitos por 10 mil hab."),
             ("rot_internacoes", "Internações"),
             ("rot_leitos", "Leitos SUS")],
            titulo_legenda="Ocupação estimada dos leitos", altura=altura_mapa,
        )
        with bloco:
            st.pydeck_chart(deck, width="stretch", height=altura_mapa)
            st.markdown(legenda, unsafe_allow_html=True)

with regiao_col:
    bloco = ui.painel("Internações por região", chave="reg",
                      altura=ui.ALTURA_CARTAO)
    dados_regiao = db.internacoes_por_regiao(filtros.competencia)
    if dados_regiao.empty:
        bloco.info("Sem dados.")
    else:
        dados_regiao = dados_regiao.assign(
            rotulo=lambda d: d["internacoes"].map(ui.num),
            leitos=lambda d: d["leitos_sus"].map(ui.num),
        )
        bloco.altair_chart(
            ui.barras_horizontais(
                dados_regiao, "regiao", "internacoes", "rotulo",
                titulo_valor="Internações", passo=42,
                dicas=[ui.alt.Tooltip("regiao:N", title=""),
                       ui.alt.Tooltip("rotulo:N", title="Internações"),
                       ui.alt.Tooltip("leitos:N", title="Leitos SUS")],
            ),
            width="stretch", theme=None,
        )

with gestao_col:
    bloco = ui.painel("Leitos por tipo de gestão", chave="gestao",
                      altura=ui.ALTURA_CARTAO)
    gestao = db.leitos_por_tipo_gestao(
        filtros.competencia, filtros.regiao_sql, filtros.uf_sql
    )
    if gestao.empty:
        bloco.info("Sem dados.")
    else:
        total_leitos = gestao["leitos_sus"].sum()
        gestao = gestao.assign(
            pct=lambda d: d["leitos_sus"] / total_leitos * 100 if total_leitos else 0,
        ).assign(
            rotulo=lambda d: d.apply(
                lambda linha: f"{ui.num(linha['leitos_sus'])} · {ui.pct(linha['pct'])}",
                axis=1),
            estab=lambda d: d["estabelecimentos"].map(ui.num),
        )
        bloco.altair_chart(
            ui.barras_horizontais(
                gestao, "tipo_gestao", "leitos_sus", "rotulo",
                titulo_valor="Leitos SUS", passo=42,
                dicas=[ui.alt.Tooltip("tipo_gestao:N", title=""),
                       ui.alt.Tooltip("rotulo:N", title="Leitos SUS"),
                       ui.alt.Tooltip("estab:N", title="Estabelecimentos")],
            ),
            width="stretch", theme=None,
        )

# ---------------------------------------------------------------------
# Linha 2 · série no tempo e ranking
# ---------------------------------------------------------------------

serie_col, ranking_col = st.columns([1.6, 1], gap="small")

with serie_col:
    bloco = ui.painel("Evolução mensal", "Doze competências de 2024",
                      chave="serie", altura=ui.ALTURA_CARTAO_BAIXO)
    serie = db.evolucao_mensal(filtros.regiao_sql, filtros.uf_sql)
    if serie.empty:
        bloco.info("Sem dados.")
    else:
        serie = serie.assign(
            rotulo=lambda d: d["competencia"].str[4:] + "/" + d["competencia"].str[:4],
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_permanencia=lambda d: d["permanencia_media"].map(
                lambda v: f"{ui.num(v, 1)} dias"),
        )
        # Internações e permanência média vão em painéis empilhados, não
        # num segundo eixo y: as duas séries têm ordens de grandeza
        # distintas, e sobrepô-las num eixo comum alinharia as curvas num
        # ponto arbitrário, sugerindo uma correlação que o dado não afirma.
        bloco.altair_chart(
            ui.series_temporais(
                serie, "rotulo",
                [("internacoes", "Internações", "rot_internacoes"),
                 ("permanencia_media", "Permanência média (dias)",
                  "rot_permanencia")],
                altura=(ui.altura_util(ui.ALTURA_CARTAO_BAIXO) - 46) // 2,
            ),
            width="stretch", theme=None,
        )

with ranking_col:
    bloco = ui.painel("Top UFs por internações", chave="topo",
                      altura=ui.ALTURA_CARTAO_BAIXO)
    if not dados_uf.empty:
        topo = dados_uf.head(10).copy()
        total = topo["internacoes"].sum()
        topo["pct_do_total"] = (topo["internacoes"] / total * 100).round(1)
        bloco.dataframe(
            topo[["uf", "internacoes", "pct_do_total", "ocupacao_estimada"]],
            width="stretch", hide_index=True,
            height=ui.altura_util(ui.ALTURA_CARTAO_BAIXO),
            column_config={
                "uf": st.column_config.TextColumn("UF", width="small"),
                "internacoes": st.column_config.NumberColumn(
                    "Internações", format="localized"),
                "pct_do_total": st.column_config.ProgressColumn(
                    "% do top 10", format="%.1f%%", min_value=0,
                    max_value=float(topo["pct_do_total"].max()),
                    color=ui.COR_PRINCIPAL),
                # A medida que colore o mapa também em número: cor de status
                # não pode ser o único caminho até o valor.
                "ocupacao_estimada": st.column_config.NumberColumn(
                    "Ocupação", format="%.1f%%",
                    help="Dias-leito consumidos sobre os ofertados no mês."),
            },
        )

ui.rodape([
    "**Ocupação estimada** = dias de permanência ÷ (leitos × 30). É "
    "aproximação: o SIH registra dias de permanência, não a data exata de "
    "ocupação do leito.",
    "O **mapa** colore por ocupação, não por volume de internações — volume "
    "apenas repintaria o mapa da população. UF sem produção registrada sai "
    "em cinza, e não na cor de folga.",
    "**% do top 10** é calculado sobre as dez UFs listadas, não sobre o "
    "total do recorte.",
    "Contorno territorial pela malha de unidades federativas do IBGE.",
])
