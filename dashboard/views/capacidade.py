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

# Todo indicador desta página respeita o porte, inclusive a fita do topo:
# um painel em que o filtro vale para metade dos números diz duas coisas
# diferentes ao mesmo tempo.
atual = db.indicadores_gerais(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
)
anterior = db.variacao_anterior(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
)


def delta(campo: str, casas: int = 1) -> str | None:
    """Variação percentual contra a competência anterior."""
    return ui.variacao(atual, anterior, campo, casas)


if atual.empty:
    ui.bloco_vazio()
    st.stop()

# ---------------------------------------------------------------------
# Fita de indicadores
# ---------------------------------------------------------------------

faixas = db.distribuicao_faixas(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
)

# As duas faixas de cima, o recorte delas e a ordenação por tamanho saem
# daqui uma vez só: a fita, a leitura ao lado e a lista embaixo do cartão
# pediam as mesmas três coisas, cada uma recalculando por conta própria.
# O .isin() troca três passagens do parser de expressão do pandas.query()
# por uma máscara direta.
FAIXAS_CRITICAS = ("Crítica", "Alta")

criticas = (faixas[faixas["faixa_pressao"].isin(FAIXAS_CRITICAS)]
            if not faixas.empty else faixas)
faixas_por_tamanho = (faixas.sort_values("municipios", ascending=False)
                      if not faixas.empty else faixas)

criticos = int(criticas["municipios"].sum()) if not criticas.empty else 0
total_classificados = int(faixas["municipios"].sum()) if not faixas.empty else 0

ui.fita_indicadores([
    {"label": "Capacidade instalada",
     "value": f"{ui.num(atual['leitos_sus'])} leitos",
     "delta": delta("leitos_sus"),
     "help": "Leitos do CNES disponíveis ao SUS no recorte. Variação contra "
             "a competência anterior."},
    {"label": "Demanda no período",
     "value": f"{ui.num(atual['internacoes'])} internações",
     "delta": delta("internacoes"),
     "help": "Internações pagas na competência selecionada. Variação contra "
             "a competência anterior."},
    {"label": "Ocupação estimada", "value": ui.pct(atual["ocupacao_estimada"]),
     "delta": delta("ocupacao_estimada"),
     "help": "Dias de permanência sobre leitos vezes 30. É aproximação: o "
             "SIH registra dias de permanência, não a data exata de ocupação "
             "do leito. Variação contra a competência anterior."},
    {"label": "Em pressão alta ou crítica", "value": ui.num(criticos),
     "delta": f"{criticos / total_classificados * 100:.0f}% dos classificados"
              if total_classificados else None,
     "delta_color": "inverse",
     "help": "Municípios nas duas faixas mais altas do ICPA. Municípios sem "
             "leito SUS ou sem produção hospitalar ficam fora do índice: "
             "ausência de serviço não é pressão baixa."},
    {"label": "Leitos por 10 mil hab.",
     "value": ui.num(atual["leitos_por_10mil"], 2),
     "delta": delta("leitos_por_10mil", 2),
     "help": "Capacidade instalada relativa à população do recorte. Variação "
             "contra a competência anterior."},
])

# ---------------------------------------------------------------------
# Linha 1 · diagnóstico
# ---------------------------------------------------------------------

col_capacidade, col_matriz, col_leitura = st.columns([1.2, 1.2, 1], gap="small")

with col_capacidade:
    capacidade = db.capacidade_x_demanda(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql,
        filtros.porte_sql,
    )
    # A unidade da barra desce com o recorte: região, UF e, com um estado
    # escolhido, os sete municípios de maior demanda daquele estado. O
    # subtítulo diz qual delas está na tela.
    if filtros.uf_sql:
        descricao = f"Sete municípios de maior demanda · {filtros.uf_sql}"
    elif filtros.regiao_sql:
        descricao = "Leitos SUS contra internações, por UF"
    else:
        descricao = "Leitos SUS contra internações, por região"
    bloco = ui.painel("Capacidade e demanda", descricao,
                      chave="capdem", altura=ui.ALTURA_CARTAO)
    if capacidade.empty:
        bloco.info("Sem dados.")
    else:
        capacidade = capacidade.assign(
            rot_leitos=lambda d: d["leitos_sus"].map(ui.num),
            rot_internacoes=lambda d: d["internacoes"].map(ui.num),
            rot_giro=lambda d: d["internacoes_por_leito"].map(
                lambda v: f"{ui.num(v, 1)} por leito"),
        )
        # Duas barras por linha, coladas: a demanda em cima e a
        # capacidade que a absorveu logo abaixo, na mesma escala. O par
        # se lê como um bloco, e a diferença de comprimento entre as duas
        # é o próprio indicador. O passo é teto: com sete municípios ele
        # encolhe sozinho para o conjunto caber no cartão.
        bloco.altair_chart(
            ui.barras_agrupadas(
                capacidade, "dimensao",
                [("leitos_sus", "Leitos SUS", "rot_leitos"),
                 ("internacoes", "Internações", "rot_internacoes")],
                passo=44, altura_cartao=ui.ALTURA_CARTAO,
                dicas_extra=[("rot_giro", "Giro")],
            ),
            width="stretch", theme=None,
        )

with col_matriz:
    # A linha da matriz acompanha o recorte, como no cartão ao lado: sem
    # filtro territorial ela é a região; com região ou UF escolhida, passa
    # a ser a UF — senão a matriz viraria uma linha só.
    linha_por_uf = filtros.recorte_territorial
    bloco = ui.painel(
        "Matriz de pressão",
        f"Municípios por {'UF' if linha_por_uf else 'região'} e faixa do ICPA",
        chave="matriz", altura=ui.ALTURA_CARTAO,
    )
    matriz = db.matriz_pressao(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql,
        filtros.porte_sql,
    )
    if matriz.empty:
        bloco.info("Sem dados.")
    else:
        # A grade é preenchida antes de desenhar: célula ausente no banco
        # significa nenhum município naquela combinação, e zero é um dado,
        # não um buraco.
        grade = (
            matriz.pivot(index="dimensao", columns="faixa_pressao", values="municipios")
            .reindex(columns=ui.FAIXAS_ORDEM)
            .fillna(0).astype(int)
            .stack().rename("municipios").reset_index()
        )
        grade = grade.assign(rotulo=lambda d: d["municipios"].map(ui.num))
        bloco.altair_chart(
            ui.mapa_calor(
                grade, "dimensao", "faixa_pressao", "municipios", "rotulo",
                ordem_coluna=ui.FAIXAS_ORDEM, titulo_valor="Municípios",
                # Com uma região escolhida a matriz ganha uma linha por UF
                # — nove no Nordeste. O passo encolhe para caber no cartão
                # em vez de o gráfico ganhar rolagem própria.
                altura_cartao=ui.ALTURA_CARTAO,
            ),
            width="stretch", theme=None,
        )

    # NOTA DE ESCOPO
    # A tela de referência usa região por especialidade de leito. Isso
    # exigiria TP_LEITO preservado na Silver, e a extração atual agrega
    # essa coluna antes de gravar. Enquanto ela não existir, a matriz usa
    # a faixa do ICPA, que é a dimensão disponível.

# Fora do `with`: aninhada, a função era recriada a cada rerun e os nomes
# dos parâmetros sombreavam os globais de mesmo nome — ler o corpo exigia
# saber qual dos dois estava em jogo. Os recortes chegam prontos de cima,
# em vez de cada frase refazer o próprio filtro e a própria ordenação.
def leitura(todas: pd.DataFrame, criticas: pd.DataFrame,
            por_tamanho: pd.DataFrame, matriz: pd.DataFrame) -> list[str]:
    """
    Frases derivadas do recorte em tela.

    Cada uma sai de uma conta sobre os mesmos dados dos gráficos ao
    lado — nada aqui é texto fixo, e nada depende de LLM. Se o filtro
    muda, a leitura muda junto.
    """
    notas: list[str] = []
    if todas.empty:
        return notas

    total = int(todas["municipios"].sum())
    if total and not criticas.empty:
        quantos = int(criticas["municipios"].sum())
        internacoes = int(criticas["internacoes"].sum())
        total_internacoes = int(todas["internacoes"].sum())
        parcela = internacoes / total_internacoes * 100 if total_internacoes else 0
        notas.append(
            f"**{ui.num(quantos)}** municípios "
            f"({quantos / total * 100:.0f}% dos classificados) estão em "
            f"pressão alta ou crítica, e respondem por "
            f"**{ui.pct(parcela, 0)}** das internações."
        )

    if not matriz.empty:
        # A dimensão da matriz muda com o recorte, então a frase fala
        # de região ou de UF conforme o que está desenhado ao lado.
        criticas_por_area = (
            matriz[matriz["faixa_pressao"].isin(FAIXAS_CRITICAS)]
            .groupby("dimensao")["municipios"].sum().sort_values(ascending=False)
        )
        if not criticas_por_area.empty:
            notas.append(
                f"Maior concentração em **{criticas_por_area.index[0]}**, com "
                f"**{ui.num(int(criticas_por_area.iloc[0]))}** municípios "
                "nessas duas faixas."
            )

    maior = por_tamanho.iloc[0]
    notas.append(
        f"Faixa mais numerosa: **{maior['faixa_pressao']}**, com "
        f"{ui.num(maior['municipios'])} municípios e "
        f"{ui.num(maior['internacoes'])} internações."
    )
    return notas


with col_leitura:
    bloco = ui.painel("Leitura dos números", chave="leitura",
                      altura=ui.ALTURA_CARTAO)

    with bloco:
        for nota in leitura(faixas, criticas, faixas_por_tamanho, matriz):
            st.markdown(f":material/arrow_right: {nota}")
        if not faixas.empty:
            st.divider()
            for linha in faixas_por_tamanho.itertuples(index=False):
                st.markdown(
                    f"**{linha.faixa_pressao}** · "
                    f"{ui.num(linha.municipios)} municípios  \n"
                    f":grey[{ui.num(linha.internacoes)} internações]"
                )

# ---------------------------------------------------------------------
# Linha 2 · ranking de sobrecarga
# ---------------------------------------------------------------------

# Único cartão da faixa, e por isso o único que pode crescer: sem vizinho
# na linha, esticar não desalinha nada. Sem altura fixa o cartão acompanha
# o conteúdo, e as quinze barras cabem inteiras em vez de o gráfico ganhar
# rolagem própria dentro de um bloco menor que ele.
bloco = ui.painel(
    "Ranking de sobrecarga",
    "Municípios ordenados pelo Índice Composto de Pressão Assistencial",
    chave="ranking",
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
        # A tabela mantém viewport próprio: trinta linhas rolando dentro
        # dela é o comportamento esperado de uma tabela, e deixá-la crescer
        # faria o cartão dobrar de altura ao trocar de aba.
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
# Linha 3 · vazios assistenciais
# ---------------------------------------------------------------------
# Faixa própria, como a do ranking. Sozinho na linha, o cartão pode
# crescer com o conteúdo sem desalinhar vizinho nenhum, e a tabela deixa
# de espremer cinco colunas em um terço da tela — sobra largura para a
# demanda que esses municípios geram e para o destino com a UF.

bloco = ui.painel(
    "Vazios assistenciais",
    "Municípios sem leito SUS e acima de 10 mil habitantes",
    chave="vazios",
)
vazios = db.vazios_assistenciais(
    filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql,
    filtros.porte_sql,
)
if vazios.empty:
    bloco.info("Nenhum município nesta condição no recorte.")
else:
    # A evasão é a coluna que interessa aqui, então o ordenamento passa
    # a ser por ela — a população continua como leitura de porte.
    vazios = vazios.sort_values("taxa_evasao", ascending=False,
                                na_position="last").assign(
        destino=lambda d: d["municipio_destino"].fillna("—")
                          + " · " + d["uf_destino"].fillna(""),
    )
    bloco.dataframe(
        vazios[["municipio", "uf", "populacao", "internacoes_residentes",
                "taxa_evasao", "destino"]],
        width="stretch", hide_index=True,
        height=ui.altura_util(ui.ALTURA_CARTAO_ALTO),
        column_config={
            "municipio": st.column_config.TextColumn("Município"),
            "uf": st.column_config.TextColumn("UF", width="small"),
            "populacao": st.column_config.NumberColumn(
                "População", format="localized"),
            "internacoes_residentes": st.column_config.NumberColumn(
                "Internações de residentes", format="localized",
                help="Internações de moradores do município, onde quer que "
                     "tenham sido atendidas. É a demanda que ele gera sem "
                     "ter leito próprio."),
            "taxa_evasao": st.column_config.ProgressColumn(
                "Evasão", format="%.1f%%", min_value=0, max_value=100,
                color=ui.CORES_FAIXA["Crítica"],
                help="Parte das internações de residentes que ocorreu "
                     "fora do município."),
            "destino": st.column_config.TextColumn("Destino principal"),
        },
    )

# ---------------------------------------------------------------------
# Linha 4 · modelo analítico e deslocamento
# ---------------------------------------------------------------------
# Dois cartões dividindo a página. O do modelo leva um pouco mais de
# largura porque guarda dois gráficos empilhados, e a linha inteira usa a
# altura do cartão alto para os dois caberem sem rolagem.

col_cluster, col_evasao = st.columns([1.3, 1], gap="small")
altura_tabela = ui.altura_util(ui.ALTURA_CARTAO_ALTO)

with col_cluster:
    # A gold_cluster guarda a atribuição de UMA competência, então este
    # cartão não segue o filtro de mês — o subtítulo diz qual é. Região,
    # UF e porte seguem: eles não mudam o grupo de cada município, apenas
    # restringem quem entra nas médias.
    perfis = db.perfis_de_cluster(
        filtros.regiao_sql, filtros.uf_sql, filtros.porte_sql
    )
    competencia_modelo = (
        ui.competencia_legivel(perfis["competencia"].iloc[0])
        if not perfis.empty else "—"
    )
    bloco = ui.painel(
        "Modelo analítico · clusterização",
        f"Perfis de município do agrupamento · competência {competencia_modelo}",
        chave="cluster", altura=ui.ALTURA_CARTAO_ALTO,
    )
    if perfis.empty:
        bloco.info("Sem municípios agrupados no recorte.")
    else:
        ordem_perfis = perfis["perfil"].tolist()   # já vem por ICPA médio
        perfis = perfis.assign(
            rot_icpa=lambda d: d["icpa_medio"].map(lambda v: ui.num(v, 1)),
            rot_municipios=lambda d: d["municipios"].map(ui.num),
            rot_populacao=lambda d: d["populacao_media"].map(ui.num),
        )

        # A matriz compara os quatro eixos do modelo entre os grupos. As
        # três primeiras variáveis são componentes do ICPA, já normalizados
        # de 0 a 1; a oferta de leitos é uma taxa por 10 mil habitantes,
        # de outra ordem de grandeza. Numa escala de cor só, a oferta
        # pintaria tudo e as outras três sairiam brancas.
        #
        # Por isso a COR é a posição da célula dentro da própria linha —
        # o quadrado mais escuro é o grupo mais alto naquela variável — e
        # o NÚMERO impresso continua sendo a média de verdade. Comparar
        # linhas pela cor não faria sentido; comparar dentro de uma linha,
        # que é a pergunta do cartão, faz.
        celulas = []
        for coluna, rotulo_variavel, casas in ui.VARIAVEIS_CLUSTER:
            valores = perfis[coluna].astype(float)
            piso, teto = valores.min(), valores.max()
            vao = teto - piso
            for perfil, valor in zip(perfis["perfil"], valores):
                celulas.append({
                    "variavel": rotulo_variavel,
                    "perfil": perfil,
                    "intensidade": 0.5 if vao == 0 else (valor - piso) / vao,
                    "rotulo": ui.num(valor, casas),
                })
        matriz_cluster = pd.DataFrame(celulas)

        with bloco:
            st.altair_chart(
                ui.barras_horizontais(
                    perfis, "perfil", "icpa_medio", "rot_icpa",
                    titulo_valor="ICPA médio do grupo", passo=32,
                    dicas=[ui.alt.Tooltip("perfil:N", title=""),
                           ui.alt.Tooltip("rot_icpa:N", title="ICPA médio"),
                           ui.alt.Tooltip("rot_municipios:N", title="Municípios"),
                           ui.alt.Tooltip("rot_populacao:N", title="População média")],
                ),
                width="stretch", theme=None,
            )
            st.altair_chart(
                ui.mapa_calor(
                    matriz_cluster, "variavel", "perfil", "intensidade", "rotulo",
                    ordem_coluna=ordem_perfis, titulo_valor="Média do grupo",
                    titulo_legenda="Mais claro a mais escuro: menor a maior na linha",
                    passo=30,
                ),
                width="stretch", theme=None,
            )

with col_evasao:
    bloco = ui.painel("Deslocamento de pacientes",
                      "Internações fora do município de residência",
                      chave="evasao", altura=ui.ALTURA_CARTAO_ALTO)
    dados_evasao = db.evasao(
        filtros.competencia_sql, filtros.regiao_sql, filtros.uf_sql,
        filtros.porte_sql, minimo=100,
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
            aba_grafico, aba_tabela = st.tabs(["Quinze maiores", "Tabela"])
            with aba_grafico:
                st.altair_chart(
                    ui.barras_horizontais(
                        dados_evasao.head(15), "rotulo_origem", "taxa_evasao",
                        "rot_taxa", titulo_valor="Taxa de evasão (%)",
                        passo=ui.passo_barras(ui.ALTURA_CARTAO_ALTO, 15),
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
    "O **modelo de clusterização** foi ajustado numa competência só, e a "
    "atribuição de cada município vem gravada dela — por isso aquele cartão "
    "não acompanha o filtro de competência, e diz no subtítulo a que mês se "
    "refere. Na matriz, a cor compara os grupos DENTRO de cada linha: o "
    "quadrado mais escuro é o grupo mais alto naquela variável, e o número "
    "impresso é a média de verdade. Comparar linhas pela cor não vale, "
    "porque demanda, uso e permanência são componentes normalizados do ICPA "
    "e a oferta de leitos é uma taxa por 10 mil habitantes.",
    "**Deslocamento** considera apenas municípios com pelo menos 100 "
    "internações de residentes, para evitar distorção por volume baixo. Sem "
    "leito próprio a evasão tende a 100%: ela mede deslocamento, não a "
    "qualidade da rede de destino.",
])
