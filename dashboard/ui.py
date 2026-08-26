"""
Componentes de interface compartilhados pelas três páginas.

Concentra aqui o que se repete — filtros, formatação e cabeçalho — para
que cada view cuide só do que é específico dela.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import db

# ---------------------------------------------------------------------
# Identidade visual
# ---------------------------------------------------------------------

PALETA = ["#0F5C73", "#1D9E75", "#E8A33D", "#C4553B", "#7F77DD"]

CORES_FAIXA = {
    "Crítica": "#C4553B",
    "Alta": "#E8A33D",
    "Moderada": "#1D9E75",
    "Baixa": "#0F5C73",
}

PORTES = ["Todos", "Até 20 mil", "20 a 100 mil", "100 a 500 mil", "Acima de 500 mil"]


# ---------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------

def num(valor, casas: int = 0) -> str:
    """Formata número no padrão brasileiro: 2.482.731 e 5,4."""
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(valor, casas: int = 1) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{num(valor, casas)}%"


def reais(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    if valor >= 1_000_000_000:
        return f"R$ {num(valor / 1_000_000_000, 1)} bi"
    if valor >= 1_000_000:
        return f"R$ {num(valor / 1_000_000, 1)} mi"
    return f"R$ {num(valor)}"


def competencia_legivel(competencia: str) -> str:
    return f"{competencia[4:]}/{competencia[:4]}" if competencia else "—"


# ---------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------

@dataclass
class Filtros:
    """Estado dos filtros, passado para as consultas do db."""
    competencia: str
    regiao: str | None
    uf: str | None
    porte: str | None

    @property
    def regiao_sql(self) -> str | None:
        return None if self.regiao in (None, "Todos") else self.regiao

    @property
    def uf_sql(self) -> str | None:
        return None if self.uf in (None, "Todos") else self.uf

    @property
    def porte_sql(self) -> str | None:
        return None if self.porte in (None, "Todos") else self.porte

    @property
    def rotulo_territorio(self) -> str:
        if self.uf_sql:
            return self.uf_sql
        if self.regiao_sql:
            return self.regiao_sql
        return "Brasil"


# ---------------------------------------------------------------------
# Estrutura da página
# ---------------------------------------------------------------------
#
# O arranjo segue o de um painel de BI: filtros numa faixa lateral, fita
# de indicadores no topo e o restante em cartões de altura fixa alinhados
# em linhas.
#
# A altura fixa é o que sustenta a grade. Sem ela cada cartão cresce
# conforme o próprio conteúdo, e basta um filtro devolver menos linhas
# para a linha inteira desalinhar. Em troca, todo gráfico precisa caber
# na altura útil do cartão — daí as constantes abaixo, e não um número
# solto em cada chamada.

ALTURA_CARTAO = 404          # linha padrão
ALTURA_CARTAO_BAIXO = 366    # linha de série temporal e tabelas
ALTURA_CARTAO_ALTO = 486     # linha de um cartão só, largo

# Desconto do cabeçalho do cartão e do respiro interno, para o gráfico
# não empurrar o eixo para fora e criar barra de rolagem aninhada.
_MIOLO = 96


def altura_util(altura_cartao: int, com_legenda: bool = False) -> int:
    """Altura que sobra para o gráfico dentro de um cartão."""
    return altura_cartao - _MIOLO - (34 if com_legenda else 0)


def painel_filtros(mostrar_porte: bool = True) -> Filtros:
    """
    Segmentadores na barra lateral.

    Ficavam no topo da página, ocupando uma faixa inteira da tela em cada
    aba. Na lateral eles saem do caminho do conteúdo, valem para as três
    páginas no mesmo lugar e liberam a largura toda para a grade.
    """
    competencias = listar_ou_vazio(db.listar_competencias)
    regioes = ["Todos"] + listar_ou_vazio(db.listar_regioes)

    with st.sidebar:
        st.markdown('<div class="cs-slicer">Filtros</div>', unsafe_allow_html=True)

        competencia = st.selectbox(
            "Competência", competencias or ["—"],
            index=max(len(competencias) - 1, 0),
            format_func=competencia_legivel,
            key="f_competencia",
        )
        regiao = st.selectbox("Região", regioes, key="f_regiao")
        ufs = ["Todos"] + listar_ou_vazio(
            db.listar_ufs, None if regiao == "Todos" else regiao
        )
        uf = st.selectbox("UF", ufs, key="f_uf")

        porte = "Todos"
        if mostrar_porte:
            porte = st.selectbox("Porte do município", PORTES, key="f_porte")

        if st.button("Limpar filtros", icon=":material/filter_alt_off:",
                     width="stretch"):
            for chave in ("f_regiao", "f_uf", "f_porte"):
                st.session_state.pop(chave, None)
            st.rerun()

    return Filtros(competencia=competencia, regiao=regiao, uf=uf, porte=porte)


def listar_ou_vazio(consulta, *argumentos) -> list:
    """Lista do banco, ou lista vazia se ele não responder."""
    try:
        return consulta(*argumentos)
    except Exception:
        return []


# ---------------------------------------------------------------------
# Cabeçalho, fita de indicadores e cartões
# ---------------------------------------------------------------------

def cabecalho(titulo: str, subtitulo: str, filtros: Filtros | None = None) -> None:
    """Barra de título compacta, com o recorte ativo à mostra."""
    esquerda, direita = st.columns([6, 1], vertical_alignment="center")

    with esquerda:
        fichas = ""
        if filtros is not None:
            ativos = [competencia_legivel(filtros.competencia),
                      filtros.rotulo_territorio]
            if filtros.porte_sql:
                ativos.append(filtros.porte_sql)
            fichas = "".join(f'<span class="cs-ficha">{a}</span>' for a in ativos)
        st.markdown(
            f'<div class="cs-cabecalho">'
            f'<div class="cs-titulo">{titulo}</div>'
            f'<div class="cs-subtitulo">{subtitulo}</div>'
            f'<div class="cs-fichas">{fichas}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with direita:
        if st.button("Atualizar", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.rerun()


def fita_indicadores(itens) -> None:
    """
    Fita de KPIs no topo.

    `itens` é uma lista de dicionários aceitos por st.metric. A ressalva
    de método vai em `help`, e não numa legenda solta embaixo: no arranjo
    em grade um parágrafo de texto entre a fita e a primeira linha de
    cartões empurra tudo para baixo e quebra o alinhamento.
    """
    colunas = st.columns(len(itens), gap="small")
    for coluna, item in zip(colunas, itens):
        with coluna:
            st.metric(border=True, **item)


def painel(titulo: str, descricao: str | None = None, *,
           chave: str, altura=None):
    """
    Cartão da grade. `chave` nomeia o container e vira a classe
    `st-key-cartao_<chave>`, por onde o CSS do app.py estiliza o relevo.

    Sem `altura` o cartão acompanha o conteúdo — que é o que se quer fora
    de uma linha da grade. Dentro dela, passe uma das constantes
    ALTURA_CARTAO para os cartões vizinhos terminarem na mesma linha.
    """
    caixa = st.container(border=True, height=altura or "content",
                         key=f"cartao_{chave}")
    linha_descricao = f'<div class="cs-cartao-sub">{descricao}</div>' if descricao else ""
    caixa.markdown(
        f'<div class="cs-cartao-topo">'
        f'<div class="cs-cartao-titulo">{titulo}</div>'
        f"{linha_descricao}</div>",
        unsafe_allow_html=True,
    )
    return caixa


def rodape(notas_metodologicas=()) -> None:
    """Rodapé de uma linha, com as ressalvas recolhidas."""
    if notas_metodologicas:
        with st.expander("Notas metodológicas", icon=":material/info:",
                         type="compact"):
            for nota in notas_metodologicas:
                st.markdown(f"- {nota}")

    conectado, _ = db.testar_conexao()
    estado = "conectado" if conectado else "indisponível"
    st.markdown(
        f'<div class="cs-rodape">'
        f"Conecta Saúde · Challenge 2026 Oracle + FIAP · DATASUS "
        f"(SIH/SUS, CNES, SIGTAP) e IBGE · 202401 a 202412"
        f'<span class="cs-estado">Banco: {estado}</span></div>',
        unsafe_allow_html=True,
    )


def bloco_vazio(mensagem: str = "Sem dados para os filtros selecionados.") -> None:
    st.info(mensagem, icon=":material/info:")


# ---------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------
#
# O Altair já vem junto com o Streamlit, então os gráficos não
# acrescentam dependência. As funções abaixo concentram o acabamento —
# grade em fio de cabelo, marca fina, rótulo direto — para que as três
# páginas saiam com a mesma cara.
#
# Duas regras de cor valem em todas elas:
#
#   · uma cor só quando o gráfico compara grandeza. Tingir cada barra
#     conforme o próprio valor apenas repetiria o comprimento dela e
#     gastaria o único canal de informação que ainda estava livre;
#   · a escala de faixa (CORES_FAIXA) apenas quando a cor significa
#     gravidade, e sempre junto do nome da faixa na legenda e na dica de
#     contexto — nunca cor sozinha.
#
# Os eixos de valor usam notação SI (1.2M) porque o formatador do Vega
# não conhece a localidade pt-BR. Os rótulos diretos e as dicas usam
# num()/pct(), que conhecem, e por isso são calculados em pandas antes
# de virarem coluna do gráfico.

COR_PRINCIPAL = PALETA[0]
COR_APOIO = PALETA[1]
COR_TINTA = "#1F2933"
COR_TINTA_SUAVE = "#5A6B75"
COR_GRADE = "#E3EAED"
COR_SUPERFICIE = "#FFFFFF"

FAIXAS_ORDEM = ["Baixa", "Moderada", "Alta", "Crítica"]

ESCALA_FAIXA = alt.Scale(
    domain=FAIXAS_ORDEM, range=[CORES_FAIXA[f] for f in FAIXAS_ORDEM]
)


def _acabamento(grafico):
    """Eixos e grade recuados, sem moldura, tipografia menor que o corpo."""
    return (
        grafico.configure_axis(
            gridColor=COR_GRADE, gridWidth=1, domainColor=COR_GRADE,
            tickColor=COR_GRADE, tickSize=4,
            labelColor=COR_TINTA_SUAVE, titleColor=COR_TINTA_SUAVE,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_view(stroke=None)
        .configure_legend(
            labelColor=COR_TINTA_SUAVE, titleColor=COR_TINTA_SUAVE,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
            symbolType="square", symbolSize=110,
        )
        .configure_title(
            color=COR_TINTA_SUAVE, fontSize=11, fontWeight="normal", anchor="start",
        )
    )


def _eixo_valor(titulo: str = ""):
    return alt.Axis(title=titulo or None, format="~s", grid=True, tickCount=4)


def _eixo_categoria(titulo: str | None = None):
    return alt.Axis(title=titulo, grid=False, labelLimit=190)


def _folga(dados: pd.DataFrame, campo: str, fator: float = 1.18):
    """Estica o eixo para o rótulo do fim da barra não sair do painel."""
    maximo = pd.to_numeric(dados[campo], errors="coerce").max()
    if maximo is None or pd.isna(maximo) or maximo <= 0:
        return alt.Undefined
    return alt.Scale(domain=[0, float(maximo) * fator])


def barras_horizontais(dados: pd.DataFrame, categoria: str, valor: str,
                       rotulo: str, *, titulo_valor: str = "",
                       titulo_categoria: str | None = None,
                       cor_por: str | None = None, dicas=(), passo: int = 24,
                       ordenar: bool = True):
    """
    Barras horizontais ordenadas por volume, com o número no fim da barra.

    `rotulo` nomeia uma coluna já formatada em pandas: o eixo sai em
    notação SI e o rótulo direto no padrão brasileiro. `cor_por` só deve
    ser usado quando a cor carrega significado — sem ele, todas as
    barras saem na cor principal da marca.
    """
    ordem = alt.EncodingSortField(field=valor, order="descending") if ordenar else None

    base = alt.Chart(dados).encode(
        y=alt.Y(f"{categoria}:N", sort=ordem, axis=_eixo_categoria(titulo_categoria)),
        x=alt.X(f"{valor}:Q", axis=_eixo_valor(titulo_valor),
                scale=_folga(dados, valor)),
        tooltip=list(dicas),
    )

    if cor_por:
        barras = base.mark_bar(cornerRadiusEnd=4).encode(
            color=alt.Color(f"{cor_por}:N", scale=ESCALA_FAIXA, sort=FAIXAS_ORDEM,
                            legend=alt.Legend(title=None, orient="top")),
        )
    else:
        barras = base.mark_bar(cornerRadiusEnd=4, color=COR_PRINCIPAL)

    texto = base.mark_text(
        align="left", baseline="middle", dx=6, fontSize=11, color=COR_TINTA_SUAVE,
    ).encode(text=f"{rotulo}:N")

    return _acabamento((barras + texto).properties(height=alt.Step(passo)))


def barras_pareadas(dados: pd.DataFrame, categoria: str, medidas, *,
                    passo: int = 24, titulo_categoria: str | None = None):
    """
    Duas medidas de escalas diferentes, lado a lado sobre as mesmas
    categorias. `medidas` é uma lista de (campo, título, coluna_rótulo).

    Leitos estão na casa dos milhares e internações na dos milhões: num
    eixo comum a primeira série vira um traço. A saída não é um segundo
    eixo y — dois eixos se alinham num ponto arbitrário e sugerem uma
    correlação que o dado não tem —, e sim um painel por medida.
    """
    ordem = alt.EncodingSortField(field=medidas[0][0], order="descending")
    dicas = [alt.Tooltip(f"{categoria}:N", title="")] + [
        alt.Tooltip(f"{coluna}:N", title=titulo) for _, titulo, coluna in medidas
    ]
    paineis = []

    for indice, (campo, titulo, rotulo) in enumerate(medidas):
        base = alt.Chart(dados).encode(
            y=alt.Y(f"{categoria}:N", sort=ordem,
                    axis=_eixo_categoria(titulo_categoria) if indice == 0 else None),
            x=alt.X(f"{campo}:Q", axis=_eixo_valor(), scale=_folga(dados, campo, 1.3)),
            tooltip=dicas,
        )
        cor = COR_PRINCIPAL if indice == 0 else COR_APOIO
        barras = base.mark_bar(cornerRadiusEnd=4, color=cor)
        texto = base.mark_text(
            align="left", baseline="middle", dx=6, fontSize=11, color=COR_TINTA_SUAVE,
        ).encode(text=f"{rotulo}:N")
        paineis.append(
            (barras + texto).properties(height=alt.Step(passo), title=titulo)
        )

    return _acabamento(alt.hconcat(*paineis, spacing=26))


def series_temporais(dados: pd.DataFrame, x: str, series, *, altura: int = 170):
    """
    Séries no tempo empilhadas, compartilhando o eixo horizontal.
    `series` é uma lista de (campo, título, coluna_rótulo).

    Mesmo motivo de barras_pareadas: grandezas diferentes ganham painéis
    separados em vez de um segundo eixo y. Só o último ponto recebe
    rótulo — número em cada marcador vira ruído.
    """
    ultimo = dados[x].iloc[-1]
    # Nomeado de propósito: os painéis compartilham um seletor só, para que
    # a régua acompanhe a mesma competência nos dois ao mesmo tempo.
    seletor = alt.selection_point(
        name="competencia_sob_cursor", nearest=True, on="pointerover",
        fields=[x], empty=False,
    )
    dicas = [alt.Tooltip(f"{x}:N", title="Competência")] + [
        alt.Tooltip(f"{coluna}:N", title=titulo) for _, titulo, coluna in series
    ]
    paineis = []

    for indice, (campo, titulo, rotulo) in enumerate(series):
        eixo_x = (_eixo_categoria() if indice == len(series) - 1
                  else alt.Axis(title=None, labels=False, grid=False, ticks=False))
        base = alt.Chart(dados).encode(
            x=alt.X(f"{x}:N", axis=eixo_x),
            y=alt.Y(f"{campo}:Q", axis=_eixo_valor(),
                    scale=alt.Scale(zero=False, nice=True)),
        )
        regua = (
            alt.Chart(dados).mark_rule(color=COR_GRADE, strokeWidth=1)
            .encode(x=f"{x}:N").transform_filter(seletor)
        )
        linha = base.mark_line(color=COR_PRINCIPAL, strokeWidth=2)
        marcadores = base.mark_point(
            filled=True, size=70, color=COR_PRINCIPAL,
            stroke=COR_SUPERFICIE, strokeWidth=2,
        ).encode(
            opacity=alt.condition(seletor, alt.value(1), alt.value(0)),
            tooltip=dicas,
        )
        fim = (
            base.mark_text(align="right", baseline="bottom", dy=-10, fontSize=11,
                           fontWeight="bold", color=COR_PRINCIPAL)
            .encode(text=f"{rotulo}:N")
            .transform_filter(alt.datum[x] == ultimo)
        )
        paineis.append(
            (regua + linha + marcadores + fim).properties(height=altura, title=titulo)
        )

    # O parâmetro é declarado uma vez no topo do vconcat: assim vale para
    # os dois painéis em vez de virar um seletor independente por painel.
    return _acabamento(alt.vconcat(*paineis, spacing=18).add_params(seletor))


def mapa_calor(dados: pd.DataFrame, linha: str, coluna: str, valor: str,
               rotulo: str, *, ordem_coluna=None, titulo_valor: str = ""):
    """
    Grade categoria x categoria com a contagem em cada célula.

    A cor é sequencial numa tonalidade só, clara para escura, porque o
    que ela codifica é a contagem — uma grandeza. A gravidade já está no
    eixo, que vem ordenado: pintar de verde a vermelho colocaria duas
    informações no mesmo canal, e verde contra vermelho é justamente o
    par que se perde no daltonismo mais comum.
    """
    maximo = pd.to_numeric(dados[valor], errors="coerce").max()
    limiar = float(maximo) * 0.6 if maximo is not None and not pd.isna(maximo) else 0

    base = alt.Chart(dados).encode(
        x=alt.X(f"{coluna}:N", sort=ordem_coluna,
                axis=alt.Axis(title=None, grid=False, labelAngle=0, orient="top")),
        y=alt.Y(f"{linha}:N", axis=_eixo_categoria()),
    )
    celulas = base.mark_rect(
        cornerRadius=3, stroke=COR_SUPERFICIE, strokeWidth=2,
    ).encode(
        color=alt.Color(f"{valor}:Q",
                        scale=alt.Scale(range=["#E8F1F4", COR_PRINCIPAL]),
                        legend=alt.Legend(title=titulo_valor or None, orient="bottom",
                                          gradientLength=140, format="~s")),
        tooltip=[alt.Tooltip(f"{linha}:N", title=""),
                 alt.Tooltip(f"{coluna}:N", title="Faixa"),
                 alt.Tooltip(f"{rotulo}:N", title=titulo_valor or "Municípios")],
    )
    numeros = base.mark_text(fontSize=11).encode(
        text=f"{rotulo}:N",
        color=alt.condition(alt.datum[valor] > limiar,
                            alt.value(COR_SUPERFICIE), alt.value(COR_TINTA)),
    )
    return _acabamento((celulas + numeros).properties(height=alt.Step(38)))


def dispersao(dados: pd.DataFrame, x: str, y: str, *, tamanho: str, cor: str,
              titulo_x: str, titulo_y: str, titulo_cor: str, dicas=(),
              altura: int = 320):
    """
    Dispersão com o volume no tamanho da marca e uma terceira medida
    contínua na cor — sequencial, uma tonalidade só, com escala na
    legenda. Anel da cor da superfície para marcas sobrepostas não se
    fundirem numa mancha.
    """
    grafico = alt.Chart(dados).mark_circle(
        opacity=0.85, stroke=COR_SUPERFICIE, strokeWidth=1.5,
    ).encode(
        x=alt.X(f"{x}:Q", axis=_eixo_valor(titulo_x),
                scale=alt.Scale(zero=False, nice=True)),
        y=alt.Y(f"{y}:Q", axis=_eixo_valor(titulo_y),
                scale=alt.Scale(zero=False, nice=True)),
        size=alt.Size(f"{tamanho}:Q", scale=alt.Scale(range=[60, 700]),
                      legend=alt.Legend(title=None, orient="bottom", format="~s")),
        color=alt.Color(f"{cor}:Q",
                        scale=alt.Scale(range=["#9CC5D1", COR_PRINCIPAL]),
                        legend=alt.Legend(title=titulo_cor, orient="right",
                                          gradientLength=120)),
        tooltip=list(dicas),
    )
    return _acabamento(grafico.properties(height=altura))


# ---------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------

MALHA_UF = Path(__file__).parent / "geo" / "malha_uf_ibge.json"

# A malha do IBGE identifica a UF pelo código numérico; a camada Gold, pela
# sigla. São 27 pares fixos — mesa de tradução, não dado a consultar.
CODIGO_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}


@st.cache_data(show_spinner=False)
def carregar_malha_uf() -> dict:
    """
    Contorno das UFs com a sigla injetada em properties.

    O arquivo está versionado em geo/ (ver geo/FONTE.md) justamente para
    o mapa não depender de rede durante a apresentação. O cache evita
    reabrir e reserializar 98 KB a cada rerun do Streamlit.
    """
    malha = json.loads(MALHA_UF.read_text(encoding="utf-8"))
    feicoes = []
    for feicao in malha.get("features", []):
        sigla = CODIGO_UF.get(str(feicao.get("properties", {}).get("codarea")))
        if sigla:
            feicao["properties"]["uf"] = sigla
            feicoes.append(feicao)
    return {"type": "FeatureCollection", "features": feicoes}


# Faixas de ocupação estimada, na ordem em que a gravidade cresce.
# (teto, rótulo, glifo, texto da faixa, cor)
#
# Os cortes são absolutos, nunca calculados sobre o recorte em tela: se
# dependessem dos quantis do filtro, trocar de região repintaria UFs que
# não mudaram, e a mesma cor passaria a significar coisas diferentes.
#
# 85% é a referência operacional de segurança hospitalar — acima disso não
# sobra leito para absorver oscilação. Os cortes de baixo acompanham a
# distribuição nacional, cuja mediana por UF fica perto de 50%.
#
# O glifo repete a informação da cor em outro canal: verde e vermelho são
# justamente o par que se perde no daltonismo mais comum, e o preenchimento
# do círculo já se lê como "quanto do leito está ocupado".
FAIXAS_OCUPACAO = (
    (45, "Folga", "○", "Até 45%", "#1D9E75"),
    (60, "Atenção", "◔", "45% a 60%", "#E8A33D"),
    (85, "Pressão alta", "◕", "60% a 85%", "#C4553B"),
    (None, "Acima do limite", "●", "Mais de 85%", "#7A2E1E"),
)

SEM_DADO = ("Sem produção registrada", "—", "", "#E2E8EB")


def faixa_ocupacao(valor) -> tuple[str, str, str, str]:
    """Devolve (rótulo, glifo, texto da faixa, cor) para uma ocupação."""
    if valor is None or pd.isna(valor) or valor <= 0:
        return SEM_DADO
    for teto, rotulo, glifo, texto, cor in FAIXAS_OCUPACAO:
        if teto is None or valor < teto:
            return rotulo, glifo, texto, cor
    return FAIXAS_OCUPACAO[-1][1:]


def _rgba(cor_hex: str, alfa: int = 235) -> list[int]:
    cor_hex = cor_hex.lstrip("#")
    return [int(cor_hex[i:i + 2], 16) for i in (0, 2, 4)] + [alfa]


def legenda_faixas(titulo: str, incluir_sem_dado: bool = False) -> str:
    """
    Legenda discreta das faixas.

    Cor de status nunca anda sozinha: cada faixa aparece com glifo,
    nome e o intervalo numérico. Quem não distingue verde de vermelho
    continua lendo o mapa pelo glifo e pela dica de contexto.
    """
    itens = [
        (glifo, rotulo, texto, cor)
        for _, rotulo, glifo, texto, cor in FAIXAS_OCUPACAO
    ]
    if incluir_sem_dado:
        rotulo, glifo, texto, cor = SEM_DADO
        itens.append((glifo, rotulo, texto, cor))

    def bloco(glifo: str, rotulo: str, texto: str, cor: str) -> str:
        intervalo = f'<span style="opacity:.65">{texto}</span>' if texto else ""
        return (
            '<span style="display:inline-flex;align-items:center;gap:5px;'
            'white-space:nowrap">'
            f'<span style="width:11px;height:11px;border-radius:3px;'
            f'background:{cor};display:inline-block"></span>'
            f'<span style="color:#1F2933">{glifo} {rotulo}</span>'
            f"{intervalo}</span>"
        )

    blocos = "".join(bloco(*item) for item in itens)
    return (
        '<div style="font-size:11px;color:#5A6B75;margin-top:4px">'
        f'<div style="margin-bottom:3px">{titulo}</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:10px 14px">'
        f"{blocos}</div></div>"
    )


def mapa_uf(dados: pd.DataFrame, valor: str, campos, *,
            titulo_legenda: str = "", altura: int = 340):
    """
    Coroplético das UFs por faixa de ocupação. Devolve (deck, legenda).

    A cor aqui é de status, não de grandeza: ela diz em que situação a UF
    está diante da própria capacidade instalada, e por isso os cortes são
    fixos. Volume absoluto não serve para colorir mapa — pintaria São
    Paulo de escuro todo mês só por ser São Paulo, e a leitura viraria
    "onde mora mais gente", que o mapa já mostra pelo tamanho.

    UF sem produção registrada sai em cinza, e não na cor de folga: leito
    vazio por falta de dado não é leito vazio por sobra de capacidade.

    `campos` é uma lista de (coluna, título) para a dica de contexto. As
    chaves entram planas em properties porque o interpolador do tooltip
    do Streamlit resolve `{chave}` contra properties[chave], sem aceitar
    caminho pontilhado.
    """
    malha = carregar_malha_uf()
    medida = pd.to_numeric(dados[valor], errors="coerce")
    por_uf = {
        str(linha["uf"]): linha
        for _, linha in dados.assign(**{valor: medida}).iterrows()
    }

    feicoes, houve_sem_dado = [], False
    for feicao in malha["features"]:
        sigla = feicao["properties"]["uf"]
        linha = por_uf.get(sigla)
        bruto = None if linha is None else linha[valor]
        rotulo, glifo, _, cor = faixa_ocupacao(bruto)
        if rotulo == SEM_DADO[0]:
            houve_sem_dado = True

        propriedades = {
            "uf": sigla,
            "situacao": f"{glifo} {rotulo}",
            "ocupacao": "—" if bruto is None or pd.isna(bruto) or bruto <= 0
                        else pct(bruto),
            "cor": _rgba(cor, 235 if linha is not None else 140),
        }
        if linha is None:
            propriedades.update({coluna: "—" for coluna, _ in campos})
        else:
            propriedades.update({coluna: str(linha[coluna]) for coluna, _ in campos})

        feicoes.append({
            "type": "Feature",
            "geometry": feicao["geometry"],
            "properties": propriedades,
        })

    linhas_dica = "".join(
        f'<div style="opacity:.75">{titulo}: <b>{{{coluna}}}</b></div>'
        for coluna, titulo in campos
    )
    deck = pdk.Deck(
        layers=[pdk.Layer(
            "GeoJsonLayer",
            data={"type": "FeatureCollection", "features": feicoes},
            stroked=True, filled=True, pickable=True,
            get_fill_color="properties.cor",
            get_line_color=[255, 255, 255],
            line_width_min_pixels=1,
        )],
        initial_view_state=pdk.ViewState(
            latitude=-14.5, longitude=-53.0, zoom=2.4, min_zoom=2, max_zoom=6,
        ),
        map_style=None,
        tooltip={
            "html": (
                '<div style="font-size:12px"><b>{uf}</b> · {situacao}'
                '<div style="opacity:.75">Ocupação estimada: <b>{ocupacao}</b></div>'
                f"{linhas_dica}</div>"
            ),
            "style": {"backgroundColor": "#1F2933", "color": "#FFFFFF",
                      "borderRadius": "6px", "padding": "8px 10px"},
        },
        height=altura,
    )
    return deck, legenda_faixas(titulo_legenda or "Ocupação estimada",
                                incluir_sem_dado=houve_sem_dado)


# ---------------------------------------------------------------------
# Escolha automática de forma
# ---------------------------------------------------------------------

# Nomes que denunciam uma coluna de tempo no resultado da consulta.
COLUNAS_TEMPO = ("competencia", "mes", "mes_ano", "ano", "data", "periodo")

# As colunas chegam do Oracle sem acento e em minúsculas. Como o assistente
# pode devolver qualquer uma delas, o rótulo do eixo é traduzido aqui em vez
# de sair um "Internacoes" no meio de uma tela que acentua todo o resto.
TITULOS_COLUNA = {
    "icpa": "ICPA", "uf": "UF", "cnes": "CNES", "estado": "Estado",
    "municipio": "Município", "municipios": "Municípios", "regiao": "Região",
    "competencia": "Competência", "populacao": "População",
    "internacoes": "Internações", "obitos": "Óbitos", "leitos_sus": "Leitos SUS",
    "valor_total": "Valor total", "valor_medio": "Valor médio",
    "permanencia_media": "Permanência média",
    "internacoes_por_leito": "Internações por leito",
    "leitos_por_10mil_hab": "Leitos por 10 mil hab.",
    "internacoes_por_10mil_hab": "Internações por 10 mil hab.",
    "taxa_evasao": "Taxa de evasão", "taxa_mortalidade": "Taxa de mortalidade",
    "faixa_pressao": "Faixa de pressão", "porte_municipio": "Porte do município",
    "ocupacao_estimada": "Ocupação estimada",
    "ocupacao_estimada_pct": "Ocupação estimada",
    "municipios_sem_leito": "Municípios sem leito",
    "pct_municipios_sem_leito": "Municípios sem leito (%)",
    "internacoes_residentes": "Internações de residentes",
    "internacoes_fora": "Internações fora do município",
    "municipio_destino": "Município de destino", "uf_destino": "UF de destino",
    "ranking_nacional": "Ranking nacional", "tipo_gestao": "Tipo de gestão",
    "tipo_unidade": "Tipo de unidade", "estabelecimentos": "Estabelecimentos",
    "procedimento": "Procedimento", "complexidade": "Complexidade",
    "dias_permanencia": "Dias de permanência",
}


def titulo_coluna(nome: str) -> str:
    """Rótulo de exibição para um nome de coluna do banco."""
    return TITULOS_COLUNA.get(nome.lower(), nome.replace("_", " ").capitalize())


def rotulo_medida(nome: str) -> str:
    """Título em caixa de frase, preservando siglas como ICPA."""
    titulo = titulo_coluna(nome)
    return titulo if titulo.isupper() else titulo.lower()


# Medidas que não somam: índices, taxas, médias e razões. Somar o ICPA de
# vários municípios — ou tirar percentual sobre essa soma — não significa
# coisa nenhuma, e "as três primeiras concentram 20% do total de ICPA" é
# uma frase que parece análise sem ser. Quem gera texto automático precisa
# saber a diferença antes de escrever.
MARCAS_NAO_ADITIVAS = (
    "icpa", "taxa", "media", "medio", "_por_", "pct_", "percentual",
    "ocupacao", "indice", "razao",
)


def e_aditiva(nome: str) -> bool:
    """A medida faz sentido somada entre linhas?"""
    minusculo = nome.lower()
    return not any(marca in minusculo for marca in MARCAS_NAO_ADITIVAS)

# Acima disso, barra deixa de comparar e vira parede: a tabela lê melhor.
LIMITE_BARRAS = 20


def e_numerica(serie: pd.Series) -> bool:
    """
    Numérica de fato, tolerando o que vem do banco como texto.

    Pública porque a página do assistente decide a leitura do resultado
    pelo mesmo critério com que aqui se decide a forma do gráfico.
    """
    convertida = pd.to_numeric(serie, errors="coerce")
    return bool(convertida.notna().sum() >= max(1, int(len(serie) * 0.8)))


def medida_principal(dados: pd.DataFrame, numericas: list[str]) -> str:
    """
    Entre as colunas numéricas, a que o resultado já vem ordenando.

    Pública porque a leitura do resultado, na página do assistente, precisa
    comentar exatamente a medida que o gráfico desenhou.

    Toda consulta útil termina em ORDER BY, e é essa coluna que responde à
    pergunta — as outras são contexto. Pegar simplesmente a primeira
    numérica erra feio: num ranking de pressão assistencial ela seria
    "populacao", que só está lá para dar escala ao município. Se nenhuma
    estiver ordenada, a primeira volta a ser um palpite tão bom quanto
    qualquer outro.
    """
    for coluna in numericas:
        serie = pd.to_numeric(dados[coluna], errors="coerce").dropna()
        if len(serie) >= 3 and (serie.is_monotonic_increasing
                                or serie.is_monotonic_decreasing):
            return coluna
    return numericas[0]


def grafico_automatico(dados: pd.DataFrame):
    """
    Escolhe a forma a partir do formato do resultado, e devolve
    (gráfico, legenda) ou (None, motivo).

    O assistente responde o que a pergunta pedir, então a página não pode
    fixar um tipo de gráfico. A regra aqui é a mesma que se aplicaria à
    mão: coluna de tempo com uma medida vira linha; uma categoria com uma
    medida vira barra ordenada; o resto continua tabela — que é a forma
    honesta quando não dá para afirmar o que o dado é. Nenhum palpite
    entra em gráfico.
    """
    if dados is None or dados.empty:
        return None, "A consulta não retornou linhas."
    if len(dados) < 2:
        return None, "Resultado de uma linha só — os números acima já dizem tudo."

    # O tempo é identificado antes da medida, e sai da disputa: competência
    # vem do banco como "202401", que é coercível a número e seria eleito
    # medida se a ordem fosse a inversa.
    tempo = next((c for c in dados.columns if c.lower() in COLUNAS_TEMPO), None)

    candidatas = [c for c in dados.columns if c != tempo]
    numericas = [c for c in candidatas if e_numerica(dados[c])]
    categoricas = [c for c in candidatas if c not in numericas]

    if not numericas:
        return None, "Nenhuma coluna numérica para medir."

    valor = medida_principal(dados, numericas)
    medida = pd.to_numeric(dados[valor], errors="coerce")
    if medida.dropna().empty or medida.dropna().nunique() < 2:
        return None, "A medida não varia entre as linhas."

    casas = 0 if float(medida.dropna().abs().max()) >= 100 else 2
    titulo = titulo_coluna(valor)

    if tempo:
        base = (
            dados.assign(**{valor: medida})
            .dropna(subset=[valor])
            .sort_values(tempo)
            .astype({tempo: "string"})
        )
        base = base.assign(rotulo_valor=base[valor].map(lambda v: num(v, casas)))
        return (
            series_temporais(base, tempo, [(valor, titulo, "rotulo_valor")], altura=230),
            f"Série de **{titulo.lower()}** por {titulo_coluna(tempo).lower()}.",
        )

    if categoricas:
        categoria = categoricas[0]
        base = (
            dados.assign(**{valor: medida})
            .dropna(subset=[valor])
            .nlargest(LIMITE_BARRAS, valor)
            .astype({categoria: "string"})
        )
        base = base.assign(rotulo_valor=base[valor].map(lambda v: num(v, casas)))
        legenda = f"**{titulo}** por {titulo_coluna(categoria).lower()}"
        if len(dados) > LIMITE_BARRAS:
            legenda += f", {LIMITE_BARRAS} maiores de {num(len(dados))} linhas"
        return (
            barras_horizontais(
                base, categoria, valor, "rotulo_valor",
                titulo_valor=titulo, passo=26,
                dicas=[alt.Tooltip(f"{categoria}:N", title=""),
                       alt.Tooltip("rotulo_valor:N", title=titulo)],
            ),
            legenda + ". A tabela completa está na aba ao lado.",
        )

    return None, "O resultado é só de medidas, sem uma dimensão para comparar."
