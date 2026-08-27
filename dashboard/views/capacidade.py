"""
Página 2 · Indicadores de capacidade

Onde a rede aperta. Confronta capacidade instalada com demanda, ordena
municípios pelo ICPA e expõe os vazios assistenciais.

É a página que sustenta a tese do projeto, e por isso concentra os
indicadores proprietários.

Arranjo em grade: fita de indicadores, linha de três cartões com o
diagnóstico, uma faixa larga com o ranking e outra linha de três com os
recortes. Onde antes havia gráfico e tabela empilhados, agora há abas
dentro do mesmo cartão — o que a cor diz, o número também diz, sem custar
altura à grade.
"""

import pandas as pd
import streamlit as st

import db
import ui

filtros = ui.painel_filtros(mostrar_porte=True)

ui.cabecalho(
    "Indicadores de capacidade",
    "Capacidade assistencial e risco operacional · dados públicos do SUS",
    filtros,
)

atual = db.indicadores_gerais(filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql)

if atual.empty:
    ui.bloco_vazio()
    st.stop()

# ---------------------------------------------------------------------
# Fita de indicadores
# ---------------------------------------------------------------------

faixas = db.distribuicao_faixas(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
)

criticos = 0
if not faixas.empty:
    linha = faixas.query("faixa_pressao in ['Crítica', 'Alta']")
    criticos = int(linha["municipios"].sum()) if not linha.empty else 0

total_classificados = int(faixas["municipios"].sum()) if not faixas.empty else 0

ui.fita_indicadores([
    {"label": "Capacidade instalada",
     "value": f"{ui.num(atual['leitos_sus'])} leitos",
     "help": "Leitos do CNES disponíveis ao SUS no recorte."},
    {"label": "Demanda no período",
     "value": f"{ui.num(atual['internacoes'])} internações",
     "help": "Internações pagas na competência selecionada."},
    {"label": "Ocupação estimada", "value": ui.pct(atual["ocupacao_estimada"]),
     "help": "Dias de permanência sobre leitos vezes 30. É aproximação: o "
             "SIH registra dias de permanência, não a data exata de ocupação "
             "do leito."},
    {"label": "Em pressão alta ou crítica", "value": ui.num(criticos),
     "delta": f"{criticos / total_classificados * 100:.0f}% dos classificados"
              if total_classificados else None,
     "delta_color": "inverse",
     "help": "Municípios nas duas faixas mais altas do ICPA. Municípios sem "
             "leito SUS ou sem produção hospitalar ficam fora do índice: "
             "ausência de serviço não é pressão baixa."},
    {"label": "Leitos por 10 mil hab.",
     "value": ui.num(atual["leitos_por_10mil"], 2),
     "help": "Capacidade instalada relativa à população do recorte."},
])

# ---------------------------------------------------------------------
# Linha 1 · diagnóstico
# ---------------------------------------------------------------------

col_capacidade, col_matriz, col_leitura = st.columns([1.2, 1.2, 1], gap="small")
altura_grafico = ui.altura_util(ui.ALTURA_CARTAO)

with col_capacidade:
    bloco = ui.painel("Capacidade e demanda", "Leitos SUS contra internações",
                      chave="capdem", altura=ui.ALTURA_CARTAO)
    capacidade = db.capacidade_x_demanda(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql
    )
    if capacidade.empty:
        bloco.info("Sem dados.")
    else:
        capacidade = capacidade.assign(
            rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_giro=lambda d: d["internacoes_por_leito"].map(
                lambda v: f"{ui.num(v, 1)} por leito"),
        )
        # As duas medidas dividem o eixo: a barra larga é a demanda e a
        # fina, por cima, a capacidade que a absorveu. Nesta agregação os
        # leitos ficam em torno de um terço das internações, então a
        # sobreposição compara comprimentos sem esconder a série menor.
        bloco.altair_chart(
            ui.barras_sobrepostas(
                capacidade, "dimensao",
                [("leitos_sus", "Leitos SUS", "rot_leitos"),
                 ("internacoes", "Internações", "rot_internacoes")],
                passo=38, dicas_extra=[("rot_giro", "Giro")],
            ),
            width="stretch", theme=None,
        )

with col_matriz:
    bloco = ui.painel("Matriz de pressão", "Municípios por região e faixa do ICPA",
                      chave="matriz", altura=ui.ALTURA_CARTAO)
    matriz = db.matriz_pressao(filtros.competencia_sql)
    if matriz.empty:
        bloco.info("Sem dados.")
    else:
        # A grade é preenchida antes de desenhar: célula ausente no banco
        # significa nenhum município naquela combinação, e zero é um dado,
        # não um buraco.
        grade = (
            matriz.pivot(index="regiao", columns="faixa_pressao", values="municipios")
            .reindex(columns=ui.FAIXAS_ORDEM)
            .fillna(0).astype(int)
            .stack().rename("municipios").reset_index()
        )
        grade = grade.assign(rotulo=lambda d: d["municipios"].map(ui.num))
        bloco.altair_chart(
            ui.mapa_calor(
                grade, "regiao", "faixa_pressao", "municipios", "rotulo",
                ordem_coluna=ui.FAIXAS_ORDEM, titulo_valor="Municípios",
            ),
            width="stretch", theme=None,
        )

    # NOTA DE ESCOPO
    # A tela de referência usa região por especialidade de leito. Isso
    # exigiria TP_LEITO preservado na Silver, e a extração atual agrega
    # essa coluna antes de gravar. Enquanto ela não existir, a matriz usa
    # a faixa do ICPA, que é a dimensão disponível.

with col_leitura:
    bloco = ui.painel("Leitura dos números", chave="leitura",
                      altura=ui.ALTURA_CARTAO)

    def leitura(faixas: pd.DataFrame, matriz: pd.DataFrame) -> list[str]:
        """
        Frases derivadas do recorte em tela.

        Cada uma sai de uma conta sobre os mesmos dados dos gráficos ao
        lado — nada aqui é texto fixo, e nada depende de LLM. Se o filtro
        muda, a leitura muda junto.
        """
        notas: list[str] = []
        if faixas.empty:
            return notas

        total = int(faixas["municipios"].sum())
        criticas = faixas.query("faixa_pressao in ['Crítica', 'Alta']")
        if total and not criticas.empty:
            quantos = int(criticas["municipios"].sum())
            internacoes = int(criticas["internacoes"].sum())
            total_internacoes = int(faixas["internacoes"].sum())
            parcela = internacoes / total_internacoes * 100 if total_internacoes else 0
            notas.append(
                f"**{ui.num(quantos)}** municípios "
                f"({quantos / total * 100:.0f}% dos classificados) estão em "
                f"pressão alta ou crítica, e respondem por "
                f"**{ui.pct(parcela, 0)}** das internações."
            )

        if not matriz.empty:
            criticas_regiao = (
                matriz.query("faixa_pressao in ['Crítica', 'Alta']")
                .groupby("regiao")["municipios"].sum().sort_values(ascending=False)
            )
            if not criticas_regiao.empty:
                notas.append(
                    f"Concentração maior no **{criticas_regiao.index[0]}**, com "
                    f"**{ui.num(int(criticas_regiao.iloc[0]))}** municípios "
                    "nessas duas faixas."
                )

        maior = faixas.sort_values("municipios", ascending=False).iloc[0]
        notas.append(
            f"Faixa mais numerosa: **{maior['faixa_pressao']}**, com "
            f"{ui.num(maior['municipios'])} municípios e "
            f"{ui.num(maior['internacoes'])} internações."
        )
        return notas

    with bloco:
        for nota in leitura(faixas, matriz):
            st.markdown(f":material/arrow_right: {nota}")
        if not faixas.empty:
            st.divider()
            for _, linha in faixas.sort_values(
                "municipios", ascending=False
            ).iterrows():
                st.markdown(
                    f"**{linha['faixa_pressao']}** · "
                    f"{ui.num(linha['municipios'])} municípios  \n"
                    f":grey[{ui.num(linha['internacoes'])} internações]"
                )

# ---------------------------------------------------------------------
# Linha 2 · ranking de sobrecarga
# ---------------------------------------------------------------------

bloco = ui.painel(
    "Ranking de sobrecarga",
    "Municípios ordenados pelo Índice Composto de Pressão Assistencial",
    chave="ranking", altura=ui.ALTURA_CARTAO_ALTO,
)

with bloco:
    ranking = db.ranking_sobrecarga(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql,
        filtros.porte_sql, limite=30,
    )
    if ranking.empty:
        ui.bloco_vazio()
    else:
        ranking = ranking.assign(
            rotulo_municipio=lambda d: d["municipio"] + " · " + d["uf"],
            rot_icpa=lambda d: d["icpa"].map(lambda v: ui.num(v, 1)),
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
        )
        altura_ranking = ui.altura_util(ui.ALTURA_CARTAO_ALTO) - 40
        aba_grafico, aba_tabela = st.tabs(["Quinze primeiros", "Tabela completa"])

        with aba_grafico:
            st.altair_chart(
                ui.barras_horizontais(
                    ranking.head(15), "rotulo_municipio", "icpa", "rot_icpa",
                    titulo_valor="ICPA", cor_por="faixa_pressao", passo=20,
                    dicas=[ui.alt.Tooltip("rotulo_municipio:N", title=""),
                           ui.alt.Tooltip("faixa_pressao:N", title="Faixa"),
                           ui.alt.Tooltip("rot_icpa:N", title="ICPA"),
                           ui.alt.Tooltip("rot_internacoes:N", title="Internações"),
                           ui.alt.Tooltip("rot_leitos:N", title="Leitos SUS")],
                ),
                width="stretch", theme=None,
            )

        with aba_tabela:
            st.dataframe(
                ranking[[
                    "ranking_nacional", "municipio", "uf", "populacao",
                    "internacoes", "leitos_sus", "internacoes_por_leito",
                    "permanencia_media", "icpa", "faixa_pressao",
                ]],
                width="stretch", hide_index=True, height=altura_ranking,
                column_config={
                    "ranking_nacional": st.column_config.NumberColumn(
                        "#", width="small"),
                    "municipio": st.column_config.TextColumn("Município"),
                    "uf": st.column_config.TextColumn("UF", width="small"),
                    "populacao": st.column_config.NumberColumn(
                        "População", format="localized"),
                    "internacoes": st.column_config.NumberColumn(
                        "Internações", format="localized"),
                    "leitos_sus": st.column_config.NumberColumn(
                        "Leitos SUS", format="localized"),
                    "internacoes_por_leito": st.column_config.NumberColumn(
                        "Int./leito", format="%.2f"),
                    "permanencia_media": st.column_config.NumberColumn(
                        "Permanência", format="%.1f dias"),
                    "icpa": st.column_config.ProgressColumn(
                        "ICPA", format="%.1f", min_value=0,
                        max_value=float(ranking["icpa"].max()),
                        color=ui.COR_PRINCIPAL),
                    "faixa_pressao": st.column_config.TextColumn("Faixa"),
                },
            )

# ---------------------------------------------------------------------
# Linha 3 · vazios, hospitais e deslocamento
# ---------------------------------------------------------------------

col_vazios, col_hospitais, col_evasao = st.columns(3, gap="small")
altura_tabela = ui.altura_util(ui.ALTURA_CARTAO)

with col_vazios:
    bloco = ui.painel("Vazios assistenciais",
                      "Sem leito SUS e acima de 10 mil habitantes",
                      chave="vazios", altura=ui.ALTURA_CARTAO)
    vazios = db.vazios_assistenciais(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql
    )
    if vazios.empty:
        bloco.info("Nenhum município nesta condição no recorte.")
    else:
        # A evasão é a coluna que interessa aqui, então o ordenamento passa
        # a ser por ela — a população continua como leitura de porte.
        vazios = vazios.sort_values("taxa_evasao", ascending=False,
                                    na_position="last")
        bloco.dataframe(
            vazios[["municipio", "uf", "populacao", "taxa_evasao",
                    "municipio_destino"]],
            width="stretch", hide_index=True, height=altura_tabela,
            column_config={
                "municipio": st.column_config.TextColumn("Município"),
                "uf": st.column_config.TextColumn("UF", width="small"),
                "populacao": st.column_config.NumberColumn(
                    "População", format="localized"),
                "taxa_evasao": st.column_config.ProgressColumn(
                    "Evasão", format="%.1f%%", min_value=0, max_value=100,
                    color=ui.CORES_FAIXA["Crítica"],
                    help="Parte das internações de residentes que ocorreu "
                         "fora do município."),
                "municipio_destino": st.column_config.TextColumn("Destino"),
            },
        )

with col_hospitais:
    bloco = ui.painel("Estabelecimentos sob pressão",
                      "Hospitais com 50 ou mais internações",
                      chave="hospitais", altura=ui.ALTURA_CARTAO)
    hospitais = db.hospitais_criticos(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql
    )
    if hospitais.empty:
        bloco.info("Sem hospitais que atendam aos critérios.")
    else:
        hospitais = hospitais.assign(
            rotulo_hospital=lambda d: d["municipio"] + " · " + d["uf"],
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
            rot_por_leito=lambda d: d["internacoes_por_leito"].map(
                lambda v: ui.num(v, 2)),
            rot_permanencia=lambda d: d["permanencia_media"].map(
                lambda v: f"{ui.num(v, 1)} dias"),
        )
        with bloco:
            aba_grafico, aba_tabela = st.tabs(["Dispersão", "Tabela"])
            with aba_grafico:
                st.altair_chart(
                    ui.dispersao(
                        hospitais, "leitos_sus", "internacoes_por_leito",
                        tamanho="internacoes", cor="permanencia_media",
                        titulo_x="Leitos SUS", titulo_y="Internações por leito",
                        titulo_cor="Permanência", altura=altura_tabela - 96,
                        dicas=[ui.alt.Tooltip("rotulo_hospital:N", title=""),
                               ui.alt.Tooltip("cnes:N", title="CNES"),
                               ui.alt.Tooltip("rot_leitos:N", title="Leitos SUS"),
                               ui.alt.Tooltip("rot_internacoes:N",
                                              title="Internações"),
                               ui.alt.Tooltip("rot_por_leito:N", title="Int./leito"),
                               ui.alt.Tooltip("rot_permanencia:N",
                                              title="Permanência")],
                    ),
                    width="stretch", theme=None,
                )
            with aba_tabela:
                st.dataframe(
                    hospitais[["cnes", "municipio", "uf", "internacoes",
                               "leitos_sus", "internacoes_por_leito"]],
                    width="stretch", hide_index=True, height=altura_tabela - 40,
                    column_config={
                        "cnes": st.column_config.TextColumn("CNES", width="small"),
                        "municipio": st.column_config.TextColumn("Município"),
                        "uf": st.column_config.TextColumn("UF", width="small"),
                        "internacoes": st.column_config.NumberColumn(
                            "Internações", format="localized"),
                        "leitos_sus": st.column_config.NumberColumn(
                            "Leitos", format="localized"),
                        "internacoes_por_leito": st.column_config.NumberColumn(
                            "Int./leito", format="%.2f"),
                    },
                )

with col_evasao:
    bloco = ui.painel("Deslocamento de pacientes",
                      "Internações fora do município de residência",
                      chave="evasao", altura=ui.ALTURA_CARTAO)
    dados_evasao = db.evasao(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql, minimo=100
    )
    if dados_evasao.empty:
        bloco.info("Sem dados.")
    else:
        dados_evasao = dados_evasao.assign(
            rotulo_origem=lambda d: d["municipio"] + " · " + d["uf"],
            rot_taxa=lambda d: d["taxa_evasao"].map(ui.pct),
            rot_fora=lambda d: d["internacoes_fora"].map(ui.num),
            rot_residentes=lambda d: d["internacoes_residentes"].map(ui.num),
            destino=lambda d: d["municipio_destino"].fillna("—")
                              + " · " + d["uf_destino"].fillna(""),
        )
        with bloco:
            aba_grafico, aba_tabela = st.tabs(["Doze maiores", "Tabela"])
            with aba_grafico:
                st.altair_chart(
                    ui.barras_horizontais(
                        dados_evasao.head(12), "rotulo_origem", "taxa_evasao",
                        "rot_taxa", titulo_valor="Taxa de evasão (%)", passo=19,
                        dicas=[ui.alt.Tooltip("rotulo_origem:N", title="Origem"),
                               ui.alt.Tooltip("rot_taxa:N", title="Taxa de evasão"),
                               ui.alt.Tooltip("rot_fora:N", title="Internações fora"),
                               ui.alt.Tooltip("rot_residentes:N",
                                              title="De residentes"),
                               ui.alt.Tooltip("destino:N", title="Destino")],
                    ),
                    width="stretch", theme=None,
                )
            with aba_tabela:
                st.dataframe(
                    dados_evasao[["municipio", "uf", "internacoes_residentes",
                                  "taxa_evasao", "municipio_destino"]],
                    width="stretch", hide_index=True, height=altura_tabela - 40,
                    column_config={
                        "municipio": st.column_config.TextColumn("Município"),
                        "uf": st.column_config.TextColumn("UF", width="small"),
                        "internacoes_residentes": st.column_config.NumberColumn(
                            "De residentes", format="localized"),
                        "taxa_evasao": st.column_config.ProgressColumn(
                            "Evasão", format="%.1f%%", min_value=0, max_value=100,
                            color=ui.CORES_FAIXA["Alta"]),
                        "municipio_destino": st.column_config.TextColumn("Destino"),
                    },
                )

ui.rodape([
    "**ICPA** = 0,35 × demanda relativa + 0,40 × uso da capacidade + 0,25 × "
    "tempo de ocupação. Cada componente é normalizado dentro da competência, "
    "com teto no percentil 95.",
    "Municípios **sem leito SUS ou sem produção hospitalar ficam fora do "
    "ICPA**: ausência de serviço não é pressão baixa. Eles aparecem em vazios "
    "assistenciais.",
    "A **matriz de pressão** usa a faixa do ICPA porque a especialidade de "
    "leito (TP_LEITO) é agregada na extração antes de chegar à Silver.",
    "**Deslocamento** considera apenas municípios com pelo menos 100 "
    "internações de residentes, para evitar distorção por volume baixo. Sem "
    "leito próprio a evasão tende a 100%: ela mede deslocamento, não a "
    "qualidade da rede de destino.",
])
