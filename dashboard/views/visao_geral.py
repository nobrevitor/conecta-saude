"""
Página 1 · Visão geral da rede

Panorama da rede hospitalar: volume, capacidade instalada e distribuição
territorial. Responde "como está a rede" antes de "onde está o problema",
que é assunto da página de capacidade.

Arranjo em grade: fita de indicadores, uma linha de três cartões com o
recorte territorial e uma linha de dois com a série no tempo. As alturas
saem das constantes de ui para as linhas ficarem alinhadas.
"""

import pandas as pd
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

atual = db.indicadores_gerais(filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql)
anterior = db.variacao_anterior(filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql)


def delta(campo: str, casas: int = 1) -> str | None:
    """Variação percentual contra a competência anterior."""
    return ui.variacao(atual, anterior, campo, casas)


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
altura_mapa = altura_grafico - 58

# O cartão do mapa muda de granularidade com o recorte. Sem UF escolhida
# ele é o país por estado; com uma UF, são os municípios daquele estado,
# enquadrados nele. A pergunta muda junto — de "qual estado aperta" para
# "onde, dentro dele" — e por isso a medida também muda: ocupação nos
# estados, ICPA nos municípios (ver ui.FAIXAS_ICPA).
dados_uf = db.internacoes_por_uf(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql
)
dados_municipio = (
    db.pressao_por_municipio(filtros.competencia_sql, filtros.uf_sql)
    if filtros.uf_sql else pd.DataFrame()
)

with mapa_col:
    if filtros.uf_sql:
        bloco = ui.painel(
            f"Pressão por município · {filtros.uf_sql}",
            "Índice Composto de Pressão Assistencial · volte pelo filtro de UF",
            chave="mapa_uf", altura=ui.ALTURA_CARTAO,
        )
    else:
        bloco = ui.painel(
            "Ocupação por UF",
            "Demanda contra os leitos · clique num estado para abrir os municípios",
            chave="mapa_uf", altura=ui.ALTURA_CARTAO,
        )

    dados_mapa = dados_municipio if filtros.uf_sql else dados_uf
    if dados_mapa.empty:
        bloco.info("Sem dados.")
    else:
        if filtros.uf_sql:
            mapa = dados_mapa.assign(
                rot_internacoes=lambda d: d["internacoes"].map(ui.num),
                rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
                rot_populacao=lambda d: d["populacao"].map(ui.num),
            )
            deck, legenda = ui.mapa_municipios(
                mapa, filtros.uf_sql, "icpa",
                [("rot_internacoes", "Internações"),
                 ("rot_leitos", "Leitos SUS"),
                 ("rot_populacao", "População")],
                titulo_legenda="Faixa de pressão (ICPA)", altura=altura_mapa,
            )
        else:
            mapa = dados_mapa.assign(
                rot_por_10mil=lambda d: d["leitos_por_10mil_hab"].map(
                    lambda v: ui.num(v, 2)),
                rot_internacoes=lambda d: d["internacoes"].map(ui.num),
                rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
            )
            deck, legenda = ui.mapa_uf(
                mapa, "ocupacao_estimada",
                [("rot_por_10mil", "Leitos por 10 mil hab."),
                 ("rot_internacoes", "Internações"),
                 ("rot_leitos", "Leitos SUS")],
                titulo_legenda="Ocupação estimada dos leitos", altura=altura_mapa,
                fora_do_recorte=filtros.recorte_territorial,
            )
        # Só o mapa do país responde ao clique. No mapa municipal não há
        # nível abaixo para abrir: o filtro não desce do município, e uma
        # seleção que não leva a lugar nenhum é promessa que a tela não
        # cumpre. A volta é pelo filtro de UF, como diz o subtítulo.
        selecao = None
        with bloco:
            if filtros.uf_sql:
                st.pydeck_chart(deck, width="stretch", height=altura_mapa)
            else:
                selecao = st.pydeck_chart(
                    deck, width="stretch", height=altura_mapa,
                    key=ui.chave_do_mapa(), selection_mode="single-object",
                    on_select="rerun",
                )
            st.markdown(legenda, unsafe_allow_html=True)
        # Só quando o mapa clicável esteve na tela: `selecao` é None no
        # ramo municipal, e tratar esse None apagaria a memória do último
        # clique sem que ninguém tivesse clicado em nada.
        #
        # Fica antes das consultas dos outros cartões porque o clique
        # recomeça o script — o que for lido daqui para baixo seria
        # trabalho jogado fora.
        if selecao is not None:
            ui.tratar_clique_no_mapa(selecao)

with regiao_col:
    bloco = ui.painel("Internações por região", chave="reg",
                      altura=ui.ALTURA_CARTAO)
    dados_regiao = db.internacoes_por_regiao(filtros.competencia_sql)
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
                titulo_valor="Internações",
                passo=ui.passo_barras(ui.ALTURA_CARTAO, len(dados_regiao)),
                espessura=38,
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
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql
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
                titulo_valor="Leitos SUS",
                passo=ui.passo_barras(ui.ALTURA_CARTAO, len(gestao)),
                espessura=38,
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
    # O ranking acompanha a granularidade do mapa ao lado. Com uma UF
    # escolhida, "top UFs" listaria uma linha só, a 100% de si mesma —
    # o que não é ranking nenhum.
    titulo_topo = ("Top municípios por internações" if filtros.uf_sql
                   else "Top UFs por internações")
    bloco = ui.painel(titulo_topo, chave="topo", altura=ui.ALTURA_CARTAO_BAIXO)

    if not dados_mapa.empty:
        topo = (
            dados_mapa.sort_values("internacoes", ascending=False)
            .head(10).copy()
        )
        total = topo["internacoes"].sum()
        topo["pct_do_total"] = (topo["internacoes"] / total * 100).round(1)
        # A medida que colore o mapa também em número: cor de status não
        # pode ser o único caminho até o valor.
        if filtros.uf_sql:
            colunas = ["municipio", "internacoes", "pct_do_total", "icpa"]
            config = {
                "municipio": st.column_config.TextColumn("Município"),
                "icpa": st.column_config.NumberColumn(
                    "ICPA", format="%.1f",
                    help="Índice Composto de Pressão Assistencial. Vazio nos "
                         "municípios fora do índice — sem leito SUS ou sem "
                         "produção hospitalar."),
            }
        else:
            colunas = ["uf", "internacoes", "pct_do_total", "ocupacao_estimada"]
            config = {
                "uf": st.column_config.TextColumn("UF", width="small"),
                "ocupacao_estimada": st.column_config.NumberColumn(
                    "Ocupação", format="%.1f%%",
                    help="Dias-leito consumidos sobre os ofertados no mês."),
            }
        bloco.dataframe(
            topo[colunas],
            width="stretch", hide_index=True,
            height=ui.altura_util(ui.ALTURA_CARTAO_BAIXO),
            column_config={
                "internacoes": st.column_config.NumberColumn(
                    "Internações", format="localized"),
                "pct_do_total": st.column_config.ProgressColumn(
                    "% do top 10", format="%.1f%%", min_value=0,
                    max_value=float(topo["pct_do_total"].max()),
                    color=ui.COR_PRINCIPAL),
                **config,
            },
        )

ui.rodape([
    "**Ocupação estimada** = dias de permanência ÷ (leitos × 30). É "
    "aproximação: o SIH registra dias de permanência, não a data exata de "
    "ocupação do leito.",
    "O **mapa por UF** colore por ocupação, não por volume de internações — "
    "volume apenas repintaria o mapa da população. UF sem produção registrada "
    "sai em cinza, e não na cor de folga.",
    "O **mapa e o ranking seguem o recorte**. Com uma região escolhida, as "
    "UFs de fora saem apagadas — o que é diferente de não ter produção "
    "registrada. Com uma UF escolhida, os dois descem para o município.",
    "No mapa municipal a medida é o **ICPA**, e não a ocupação: os cortes de "
    "ocupação foram calibrados para estados, e no município deixariam quase "
    "tudo na faixa de folga. Município **sem leito SUS ou sem produção** fica "
    "fora do índice e sai em cinza.",
    "**% do top 10** é calculado sobre as dez linhas listadas, não sobre o "
    "total do recorte.",
    "Contorno territorial pelas malhas de unidades federativas e de "
    "municípios do IBGE.",
])
