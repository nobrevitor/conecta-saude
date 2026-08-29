"""
Componentes de interface compartilhados pelas três páginas.

Concentra aqui o que se repete — filtros, formatação e cabeçalho — para
que cada view cuide só do que é específico dela.
"""

from __future__ import annotations

import json
import math
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

# Eixos do modelo de agrupamento, na ordem em que a matriz os empilha:
# (coluna da consulta, rótulo na tela, casas decimais).
#
# As três primeiras são os componentes do ICPA, normalizados de 0 a 1 na
# construção do índice; a quarta é uma taxa por 10 mil habitantes. Duas
# ordens de grandeza no mesmo quadro — por isso a matriz colore por
# posição dentro da linha, e não pelo valor cru.
VARIAVEIS_CLUSTER = (
    ("demanda", "Demanda", 2),
    ("uso", "Uso da capacidade", 2),
    ("permanencia", "Permanência", 2),
    ("oferta_leitos", "Oferta de leitos", 1),
)

# Opção "todas as competências" do filtro. Quando escolhida, as consultas
# passam a devolver média mensal em vez do valor de um mês — a soma dos
# doze responderia outra pergunta, e leito nem soma entre meses.
TODAS = "__todas__"


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
    if competencia == TODAS:
        return "Todas · média mensal"
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
    def competencia_sql(self) -> str | None:
        """None quando o recorte é o ano inteiro. Ver db._por_mes."""
        return None if self.competencia in (None, TODAS) else self.competencia

    @property
    def rotulo_periodo(self) -> str:
        if self.competencia_sql:
            return competencia_legivel(self.competencia_sql)
        return "2024 · média mensal"

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
    def recorte_territorial(self) -> bool:
        """True quando o recorte cobre parte do país, e não o Brasil todo."""
        return bool(self.regiao_sql or self.uf_sql)

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

# Desconto do cabeçalho do cartão, do respiro interno e do afastamento
# entre título e gráfico (.cs-cartao-topo no app.py), para o gráfico não
# empurrar o eixo para fora e criar barra de rolagem aninhada.
_MIOLO = 104


def altura_util(altura_cartao: int, com_legenda: bool = False) -> int:
    """Altura que sobra para o gráfico dentro de um cartão."""
    return altura_cartao - _MIOLO - (34 if com_legenda else 0)


# Altura que o eixo de valor consome abaixo das barras — traços, rótulos e
# título, com folga para a última barra não empurrar nada para fora e
# abrir barra de rolagem dentro do cartão.
_EIXO_VALOR = 44


def passo_barras(altura_cartao: int, categorias: int, minimo: int = 24) -> int:
    """
    Passo que espalha as barras por toda a altura útil do cartão.

    Sem ele o passo é fixo e o gráfico termina onde os dados acabam: com
    poucas categorias sobra meio cartão vazio embaixo. Com poucas
    categorias o passo cresce bastante — quem segura a espessura da barra
    é o `espessura` de barras_horizontais, e o passo vira respiro.
    """
    if categorias <= 0:
        return minimo
    return max(minimo, (altura_util(altura_cartao) - _EIXO_VALOR) // categorias)


# Estado que liga o clique no mapa ao selectbox da UF. São duas chaves
# porque são dois papéis: UF_PENDENTE é o recado de um rerun para o outro,
# consumido assim que chega; ULTIMO_CLIQUE é a memória do que já foi
# tratado, e existe para o mesmo clique não ser processado duas vezes.
UF_PENDENTE = "_uf_do_mapa"
ULTIMO_CLIQUE = "_ultimo_clique_mapa"
CICLO_MAPA = "_ciclo_do_mapa"
GERACAO_FILTROS = "_geracao_filtros"


def chave_filtro(nome: str) -> str:
    """
    Chave de um segmentador na geração corrente.

    O valor de um widget não vive só na sessão do Python: o navegador
    guarda a própria cópia e continua exibindo e reenviando a escolha
    antiga. Apagar a chave no servidor limpa metade do mundo — a tela não
    muda, e no primeiro reenvio a escolha volta. É por isso que o botão de
    limpar parecia não fazer nada até a página ser recarregada.

    Trocar a chave resolve pela raiz: o widget passa a ser outro, sem
    valor guardado de nenhum dos dois lados, e o índice inicial de cada
    selectbox volta a mandar.
    """
    return f"f_{nome}_{st.session_state.get(GERACAO_FILTROS, 0)}"


def chave_do_mapa() -> str:
    """
    Chave do widget do mapa, renovada a cada clique consumido.

    A seleção não vive no script: ela fica guardada no estado do widget,
    de onde é relida a cada rerun. Reaproveitar a mesma chave depois de
    consumir um clique faz a seleção velha reaparecer assim que o mapa do
    país volta à tela, e o painel cai de novo no mesmo estado — o clique
    seguinte nunca chega a ser dado. Chave nova é widget novo, sem estado
    herdado, e isso não depende de qual camada guardou o valor.
    """
    return f"clique_mapa_uf_{st.session_state.get(CICLO_MAPA, 0)}"


def _consumir_clique_do_mapa() -> None:
    """
    Aplica no filtro a UF que veio de um clique no mapa.

    Roda ANTES de qualquer widget nascer: o Streamlit só aceita escrever
    no estado de um widget por chave enquanto ele ainda não existe no
    rerun. Depois de instanciado o selectbox, a escrita vira exceção.

    Se a UF clicada estiver fora da região filtrada, a região sai do
    caminho. O clique é uma escolha territorial direta, e engoli-lo calado
    seria pior do que ajustar o filtro que o contradiz.
    """
    pendente = st.session_state.pop(UF_PENDENTE, None)
    if not pendente:
        return
    # O ciclo avança mesmo que a UF não sirva: o que não pode é o mapa
    # voltar com a seleção que já foi lida uma vez.
    st.session_state[CICLO_MAPA] = st.session_state.get(CICLO_MAPA, 0) + 1
    if pendente not in listar_ou_vazio(db.listar_ufs):
        return
    regiao = st.session_state.get(chave_filtro("regiao"))
    regiao = None if regiao in (None, "Todos") else regiao
    if pendente not in listar_ou_vazio(db.listar_ufs, regiao):
        st.session_state[chave_filtro("regiao")] = "Todos"
    st.session_state[chave_filtro("uf")] = pendente


def uf_do_clique(selecao) -> str | None:
    """
    Sigla da UF no clique do mapa, ou None quando nada está selecionado.

    A camada é GeoJson, então o deck.gl devolve a feição inteira e o
    Streamlit repassa o objeto cru — daí a descida por `properties`.

    A chave é o `id` da camada. O deck.gl sobe a picking info até a camada
    raiz, então o que chega é "ufs", o id definido em ui.mapa_uf. O prefixo
    também é aceito porque GeoJsonLayer é camada composta: se um dia a
    informação parar na subcamada, ela chega como "ufs-polygons-fill", e
    perder o clique por causa de um sufixo seria um jeito bobo de quebrar.
    """
    objetos = []
    for camada, valores in (selecao or {}).get("selection", {}).get("objects", {}).items():
        if camada == "ufs" or str(camada).startswith("ufs-"):
            objetos = valores
            break
    if not objetos:
        return None
    primeiro = objetos[0]
    sigla = primeiro.get("properties", primeiro).get("uf")
    return str(sigla) if sigla else None


def tratar_clique_no_mapa(selecao) -> None:
    """
    Traduz o clique no mapa em recado para o próximo rerun.

    A escrita no filtro não acontece aqui — quando o mapa é desenhado, o
    selectbox da UF já existe. Guarda-se o pedido e recomeça-se o script;
    na volta, _consumir_clique_do_mapa aplica antes dos widgets.

    Repetir a mesma seleção é ignorado de propósito, e essa trava é o
    coração da coisa. A seleção não chega como evento: ela fica guardada
    do lado do navegador e é reenviada em TODO rerun em que o mapa do país
    está na tela. Do lado do Python, o eco é idêntico a um clique novo — o
    que os separa é apenas a lembrança de já ter tratado aquele valor.

    Sem essa memória, voltar ao mapa do país (pelo filtro ou pelo botão de
    limpar) reaplicava na hora a última UF clicada, e o painel caía de
    novo nela. Por isso ULTIMO_CLIQUE sobrevive a limpar_filtros.

    O eco só se apaga quando o próprio mapa devolve seleção vazia, que é o
    que acontece ao clicar fora de qualquer estado ou ao reclicar o estado
    já selecionado — o deck.gl trata o segundo clique como desmarcar.
    """
    escolhida = uf_do_clique(selecao)
    if not escolhida:
        st.session_state.pop(ULTIMO_CLIQUE, None)
        return
    if escolhida in (st.session_state.get(ULTIMO_CLIQUE),
                     st.session_state.get(chave_filtro("uf"))):
        return
    st.session_state[ULTIMO_CLIQUE] = escolhida
    st.session_state[UF_PENDENTE] = escolhida
    st.rerun()


# Nomes dos segmentadores, na ordem em que aparecem na lateral. A chave
# real de cada um sai de chave_filtro, que costura a geração.
NOMES_FILTRO = ("competencia", "regiao", "uf", "porte")


def limpar_filtros() -> None:
    """
    Devolve o painel ao estado de abertura — 2024 inteiro, Brasil, todos
    os portes — como se a página tivesse acabado de ser aberta.

    Avança a geração dos filtros e o ciclo do mapa: todo widget da lateral
    e o próprio mapa renascem com chave nova, sem valor guardado nem no
    Python nem no navegador. As chaves velhas ainda são descartadas, para
    a sessão não acumular estado de gerações passadas.

    ULTIMO_CLIQUE fica de fora, e não por esquecimento: o mapa reenvia a
    seleção guardada quando volta à tela, e é essa memória que impede o
    eco de ser lido como clique novo.
    """
    for nome in NOMES_FILTRO:
        st.session_state.pop(chave_filtro(nome), None)
    st.session_state.pop(chave_do_mapa(), None)
    st.session_state.pop(UF_PENDENTE, None)
    st.session_state[GERACAO_FILTROS] = st.session_state.get(GERACAO_FILTROS, 0) + 1
    st.session_state[CICLO_MAPA] = st.session_state.get(CICLO_MAPA, 0) + 1


def painel_filtros(mostrar_porte: bool = True) -> Filtros:
    """
    Segmentadores na barra lateral.

    Ficavam no topo da página, ocupando uma faixa inteira da tela em cada
    aba. Na lateral eles saem do caminho do conteúdo, valem para as três
    páginas no mesmo lugar e liberam a largura toda para a grade.
    """
    competencias = listar_ou_vazio(db.listar_competencias)
    regioes = ["Todos"] + listar_ou_vazio(db.listar_regioes)

    _consumir_clique_do_mapa()

    with st.sidebar:
        st.markdown('<div class="cs-slicer">Filtros</div>', unsafe_allow_html=True)

        opcoes = ([TODAS] + competencias) if competencias else ["—"]
        competencia = st.selectbox(
            "Competência", opcoes,
            index=0,                        # abre em 2024 inteiro, como TODAS
            format_func=competencia_legivel,
            key=chave_filtro("competencia"),
            help="Todas as competências mostra a média mensal de 2024, "
                 "não a soma dos doze meses.",
        )
        regiao = st.selectbox("Região", regioes, key=chave_filtro("regiao"))
        ufs = ["Todos"] + listar_ou_vazio(
            db.listar_ufs, None if regiao == "Todos" else regiao
        )
        uf = st.selectbox("UF", ufs, key=chave_filtro("uf"))

        porte = "Todos"
        if mostrar_porte:
            porte = st.selectbox("Porte do município", PORTES,
                                 key=chave_filtro("porte"))

        if st.button("Limpar filtros", icon=":material/filter_alt_off:",
                     width="stretch"):
            limpar_filtros()
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
            ativos = [filtros.rotulo_periodo, filtros.rotulo_territorio]
            if filtros.porte_sql:
                ativos.append(filtros.porte_sql)
            fichas = "".join(f'<span class="cs-ficha">{a}</span>' for a in ativos)
        # Sem fichas o div sai da marcação: ele tem margem própria e,
        # numa página sem fita de indicadores para encostar, isso só
        # abriria espaço morto embaixo do subtítulo.
        linha_fichas = f'<div class="cs-fichas">{fichas}</div>' if fichas else ""
        st.markdown(
            f'<div class="cs-cabecalho">'
            f'<div class="cs-titulo">{titulo}</div>'
            f'<div class="cs-subtitulo">{subtitulo}</div>'
            f"{linha_fichas}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with direita:
        if st.button("Atualizar", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.rerun()


# Espaço de largura zero, para reservar a linha da variação sem desenhar
# nada nela. Não serve espaço comum nem NBSP: o st.metric passa o delta
# por textwrap.dedent, que a partir do Python 3.13 apaga linha composta
# só de espaço em branco — e os dois se enquadram nisso, o U+200B não.
_DELTA_VAZIO = "​"


def variacao(atual, anterior, campo: str, casas: int = 1) -> str | None:
    """
    Variação percentual de um indicador contra a competência anterior.

    Devolve None — e o cartão sai sem variação — quando não existe período
    anterior (é o caso do recorte de ano inteiro) ou quando um dos dois
    lados é zero ou ausente. Zero no denominador não é queda de 100%: é
    falta de base de comparação, e inventar um número ali seria pior do
    que não mostrar nenhum.

    As duas páginas de painel usam esta mesma conta, para a mesma seta
    significar a mesma coisa nas duas.
    """
    if atual is None or anterior is None:
        return None
    if getattr(atual, "empty", False) or getattr(anterior, "empty", False):
        return None
    antes, agora = anterior.get(campo), atual.get(campo)
    if not antes or not agora:
        return None
    return f"{(agora - antes) / antes * 100:+.{casas}f}%"


def fita_indicadores(itens) -> None:
    """
    Fita de KPIs no topo.

    `itens` é uma lista de dicionários aceitos por st.metric. A ressalva
    de método vai em `help`, e não numa legenda solta embaixo: no arranjo
    em grade um parágrafo de texto entre a fita e a primeira linha de
    cartões empurra tudo para baixo e quebra o alinhamento.

    Todos os cartões terminam na mesma linha, mesmo quando um cresce por
    rótulo em duas linhas ou por ter `delta` onde os vizinhos não têm.
    Duas travas sustentam isso, porque só o CSS já se mostrou frágil:

    · `height="stretch"` manda o próprio Streamlit esticar o cartão até a
      altura da coluna, que por sua vez acompanha a mais alta da linha;

    · a linha da variação é reservada nos cartões sem `delta`, com um
      espaço rígido, sem seta e sem cor. Assim os cinco cartões têm a
      mesma estrutura e a mesma altura natural, com CSS ou sem ele.

    O contêiner nomeado dá a classe `st-key-fita_indicadores`, gancho do
    CSS que acompanha essas duas travas no app.py.
    """
    itens = list(itens)
    if any(item.get("delta") for item in itens):
        itens = [
            item if item.get("delta")
            else {**item, "delta": _DELTA_VAZIO, "delta_color": "off",
                  "delta_arrow": "off"}
            for item in itens
        ]

    faixa = st.container(key="fita_indicadores")
    colunas = faixa.columns(len(itens), gap="small")
    for coluna, item in zip(colunas, itens):
        with coluna:
            st.metric(border=True, height="stretch", **item)


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
        f"(SIH/SUS, CNES, SIGTAP) e IBGE · 01/2024 a 12/2024"
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
COR_CONTEXTO = "#9CC5D1"   # tom claro da rampa, para a série de apoio
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
                       espessura: int | None = None, ordenar: bool = True):
    """
    Barras horizontais ordenadas por volume, com o número no fim da barra.

    `rotulo` nomeia uma coluna já formatada em pandas: o eixo sai em
    notação SI e o rótulo direto no padrão brasileiro. `cor_por` só deve
    ser usado quando a cor carrega significado — sem ele, todas as
    barras saem na cor principal da marca.

    `espessura` desliga a regra de a barra preencher a faixa: com o passo
    calculado por passo_barras, poucas categorias dariam barras enormes.
    Fixando a espessura, o passo sobrando vira espaço entre as barras.
    """
    # A ordem vai como LISTA de categorias, já ordenada em pandas, e não
    # como "ordene por este campo". O gráfico é em camadas — barra mais
    # rótulo — e o Vega-Lite funde o domínio das duas antes de desenhar;
    # a ordenação por campo não sobrevive a essa fusão de forma
    # confiável, ainda mais com encoding de cor no meio, que liga o
    # empilhamento. Com a lista, a ordem é dado, não inferência: o
    # primeiro item fica no topo. É o mesmo caminho de barras_agrupadas.
    ordem = None
    if ordenar:
        ordem = (
            dados.sort_values(valor, ascending=False)[categoria]
            .astype(str).tolist()
        )

    base = alt.Chart(dados).encode(
        y=alt.Y(f"{categoria}:N", sort=ordem, axis=_eixo_categoria(titulo_categoria)),
        x=alt.X(f"{valor}:Q", axis=_eixo_valor(titulo_valor),
                scale=_folga(dados, valor)),
        tooltip=list(dicas),
    )

    tamanho = {"size": espessura} if espessura else {}

    if cor_por:
        barras = base.mark_bar(cornerRadiusEnd=4, **tamanho).encode(
            color=alt.Color(f"{cor_por}:N", scale=ESCALA_FAIXA, sort=FAIXAS_ORDEM,
                            legend=alt.Legend(title=None, orient="top")),
        )
    else:
        barras = base.mark_bar(cornerRadiusEnd=4, color=COR_PRINCIPAL, **tamanho)

    texto = base.mark_text(
        align="left", baseline="middle", dx=6, fontSize=11, color=COR_TINTA_SUAVE,
    ).encode(text=f"{rotulo}:N")

    return _acabamento((barras + texto).properties(height=alt.Step(passo)))


def barras_agrupadas(dados: pd.DataFrame, categoria: str, medidas, *,
                     passo: int = 44, titulo_valor: str = "",
                     titulo_categoria: str | None = None, dicas_extra=()):
    """
    Duas medidas por categoria, uma barra colada embaixo da outra.

    `medidas` é uma lista de dois (campo, título, coluna_rótulo). A
    primeira é a medida de referência, em barra escura; a segunda é o
    contexto, em barra clara. Dentro de cada categoria a de contexto vai
    em cima e a de referência logo abaixo, sem respiro entre elas — o par
    se lê como um bloco só, e a diferença de comprimento entre as duas é
    a leitura que interessa.

    Antes as duas dividiam a mesma faixa, sobrepostas. Funcionava como
    proporção, mas obrigava o número da barra de dentro a cair sobre a
    barra de fora, e o par exigia um instante para ser desmontado pelo
    olho. Agrupadas, cada barra tem a própria linha, o próprio rótulo em
    campo limpo e a mesma escala.

    Um eixo só, uma escala só: a comparação de comprimento é direta e o
    leitor não precisa conferir dois conjuntos de marcações.

    `passo` é a altura do GRUPO — as duas barras mais o respiro que as
    separa do grupo seguinte —, e não a de uma barra.
    """
    (campo_frente, titulo_frente, rotulo_frente) = medidas[0]
    (campo_fundo, titulo_fundo, rotulo_fundo) = medidas[1]

    # Formato longo com um registro por medida, para o eixo de valor, a
    # legenda e o agrupamento saírem de um campo só — é o que garante a
    # escala partilhada.
    colunas_carregadas = [rotulo_frente, rotulo_fundo, *(c for c, _ in dicas_extra)]
    partes = []
    for campo, titulo, rotulo in (medidas[0], medidas[1]):
        parte = dados[[categoria, *colunas_carregadas]].copy()
        parte["medida"] = titulo
        parte["valor"] = pd.to_numeric(dados[campo], errors="coerce")
        # O rótulo da própria medida, para o texto sair de uma coluna só
        # em vez de uma camada por medida.
        parte["rotulo"] = dados[rotulo].astype(str)
        partes.append(parte)
    longo = pd.concat(partes, ignore_index=True)

    ordem = (
        dados.sort_values(campo_fundo, ascending=False)[categoria]
        .astype(str).tolist()
    )
    dentro_do_grupo = [titulo_fundo, titulo_frente]
    escala = alt.Scale(domain=dentro_do_grupo, range=[COR_CONTEXTO, COR_PRINCIPAL])
    dicas = [
        alt.Tooltip(f"{categoria}:N", title=""),
        alt.Tooltip(f"{rotulo_fundo}:N", title=titulo_fundo),
        alt.Tooltip(f"{rotulo_frente}:N", title=titulo_frente),
    ] + [alt.Tooltip(f"{coluna}:N", title=titulo) for coluna, titulo in dicas_extra]

    base = alt.Chart(longo).encode(
        y=alt.Y(f"{categoria}:N", sort=ordem,
                axis=_eixo_categoria(titulo_categoria)),
        # paddingInner=0 encosta uma barra na outra dentro do grupo. O
        # respiro fica entre grupos, que é onde ele separa coisas
        # diferentes; entre as duas medidas do mesmo território, não.
        yOffset=alt.YOffset("medida:N", sort=dentro_do_grupo,
                            scale=alt.Scale(paddingInner=0)),
        x=alt.X("valor:Q", axis=_eixo_valor(titulo_valor),
                scale=_folga(longo, "valor", 1.16)),
        color=alt.Color("medida:N", scale=escala, sort=dentro_do_grupo,
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=dicas,
    )

    barras = base.mark_bar(cornerRadiusEnd=3)
    # Cada barra leva o próprio número, agora sempre em campo limpo: as
    # duas terminam em pontos distintos e nenhuma passa por cima da outra.
    rotulos = base.mark_text(
        align="left", baseline="middle", dx=6, fontSize=11,
    ).encode(text="rotulo:N", color=alt.value(COR_TINTA_SUAVE))

    # Altura em pixels, e não em Step: com o agrupamento o step passa a
    # valer para a subfaixa de cada barra, e o cartão da grade precisa
    # saber a altura do conjunto para o gráfico não transbordar.
    return _acabamento(
        (barras + rotulos).properties(height=len(ordem) * passo)
    )


def series_temporais(dados: pd.DataFrame, x: str, series, *, altura: int = 170):
    """
    Séries no tempo empilhadas, compartilhando o eixo horizontal.
    `series` é uma lista de (campo, título, coluna_rótulo).

    Grandezas de ordens diferentes ganham painéis separados em vez de
    um segundo eixo y, que alinharia as curvas num ponto arbitrário.
    Só o último ponto recebe rótulo — número em cada marcador vira
    ruído.
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
               rotulo: str, *, ordem_coluna=None, titulo_valor: str = "",
               titulo_legenda: str | None = None, passo: int | None = None,
               altura_cartao: int | None = None):
    """
    Grade categoria x categoria com a contagem em cada célula.

    A cor é sequencial numa tonalidade só, clara para escura, porque o
    que ela codifica é a contagem — uma grandeza. A gravidade já está no
    eixo, que vem ordenado: pintar de verde a vermelho colocaria duas
    informações no mesmo canal, e verde contra vermelho é justamente o
    par que se perde no daltonismo mais comum.
    """
    # Com `altura_cartao`, o passo encolhe para o número de linhas caber.
    # O desconto é maior que o de passo_barras porque esta grade gasta
    # altura em dois lugares que o gráfico de barras não tem: os rótulos
    # das faixas no topo e a régua de cor no rodapé. O teto de 38 mantém
    # a aparência de sempre quando sobra espaço.
    linhas = max(int(dados[linha].nunique()), 1)
    if passo is None:
        passo = 38
        if altura_cartao:
            passo = max(22, min(38, (altura_util(altura_cartao) - 66) // linhas))

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
                        legend=alt.Legend(
                            # A régua de cor e a dica podem falar de coisas
                            # diferentes: onde a cor mostra posição relativa,
                            # a dica ainda traz o valor de verdade.
                            title=(titulo_legenda if titulo_legenda is not None
                                   else (titulo_valor or None)),
                            orient="bottom", gradientLength=140, format="~s")),
        tooltip=[alt.Tooltip(f"{linha}:N", title=""),
                 alt.Tooltip(f"{coluna}:N", title="Faixa"),
                 alt.Tooltip(f"{rotulo}:N", title=titulo_valor or "Municípios")],
    )
    numeros = base.mark_text(fontSize=11).encode(
        text=f"{rotulo}:N",
        color=alt.condition(alt.datum[valor] > limiar,
                            alt.value(COR_SUPERFICIE), alt.value(COR_TINTA)),
    )
    return _acabamento((celulas + numeros).properties(height=alt.Step(passo)))


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
MALHA_MUNICIPIOS = Path(__file__).parent / "geo" / "municipios"

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


# Seis estados no cache: quem navega os 27 guardaria a malha de todos, e
# GeoJSON decodificado ocupa em objetos Python bem mais do que os bytes do
# arquivo. Seis cobre o vaivém entre estados vizinhos numa análise; passar
# disso é reler um arquivo de algumas centenas de KB, que é barato.
@st.cache_data(show_spinner=False, max_entries=6)
def carregar_malha_municipios(uf: str) -> dict:
    """
    Contorno dos municípios de uma UF, um arquivo por estado.

    A malha municipal do país inteiro tem 3,1 MB e 5.570 feições. Carregar
    tudo para desenhar um estado custaria memória que o plano gratuito não
    tem de sobra, e o painel só desenha municípios quando há uma UF
    escolhida — então o recorte por arquivo acompanha o recorte da tela.
    As feições trazem o código do IBGE em properties.codarea.
    """
    arquivo = MALHA_MUNICIPIOS / f"{uf}.json"
    if not arquivo.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(arquivo.read_text(encoding="utf-8"))


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

# UF que o filtro de região ou de UF deixou de fora. Cinza como a de cima,
# mas é outra afirmação: ali não há dado, aqui há dado e ele não foi pedido.
# Chamar as duas de "sem produção" faria o mapa mentir a cada filtro — com
# uma UF escolhida, seriam 26 estados acusados de não ter produção.
FORA_DO_RECORTE = ("Fora do recorte", "·", "", "#F1F4F5")


def faixa_ocupacao(valor) -> tuple[str, str, str, str]:
    """Devolve (rótulo, glifo, texto da faixa, cor) para uma ocupação."""
    if valor is None or pd.isna(valor) or valor <= 0:
        return SEM_DADO
    for teto, rotulo, glifo, texto, cor in FAIXAS_OCUPACAO:
        if teto is None or valor < teto:
            return rotulo, glifo, texto, cor
    return FAIXAS_OCUPACAO[-1][1:]


# Faixas do ICPA, mesmos cortes do gold_icpa_classificado (03_gold.sql) e
# mesmas cores que a página de capacidade usa nas barras e na matriz: a
# mesma faixa não pode trocar de cor entre duas telas do mesmo painel.
#
# Elas existem porque a escala de ocupação NÃO desce ao município. Os
# cortes de ocupação foram calibrados para UF, cuja mediana ronda os 50%;
# a mediana municipal é de 25%, e 73% dos municípios com leito cairiam em
# "Folga". O mapa sairia verde quase inteiro, dizendo o contrário do que
# o dado diz. O ICPA já nasce normalizado dentro da competência.
FAIXAS_ICPA = (
    (20, "Baixa", "○", "ICPA até 20", CORES_FAIXA["Baixa"]),
    (40, "Moderada", "◔", "20 a 40", CORES_FAIXA["Moderada"]),
    (60, "Alta", "◕", "40 a 60", CORES_FAIXA["Alta"]),
    (None, "Crítica", "●", "Acima de 60", CORES_FAIXA["Crítica"]),
)

# Município sem leito SUS ou sem produção hospitalar não entra no índice.
# Cinza, nunca a cor da faixa baixa: ausência de serviço não é pressão
# baixa — é a própria tese do projeto.
FORA_DO_INDICE = ("Sem leito SUS ou sem produção", "—", "", "#E2E8EB")


def faixa_icpa(valor) -> tuple[str, str, str, str]:
    """Devolve (rótulo, glifo, texto da faixa, cor) para um ICPA."""
    if valor is None or pd.isna(valor):
        return FORA_DO_INDICE
    for teto, rotulo, glifo, texto, cor in FAIXAS_ICPA:
        if teto is None or valor < teto:
            return rotulo, glifo, texto, cor
    return FAIXAS_ICPA[-1][1:]


def _rgba(cor_hex: str, alfa: int = 235) -> list[int]:
    cor_hex = cor_hex.lstrip("#")
    return [int(cor_hex[i:i + 2], 16) for i in (0, 2, 4)] + [alfa]


def _legenda(titulo: str, itens) -> str:
    """
    Legenda discreta, no formato (glifo, rótulo, intervalo, cor).

    Cor de status nunca anda sozinha: cada faixa aparece com glifo,
    nome e o intervalo numérico. Quem não distingue verde de vermelho
    continua lendo o mapa pelo glifo e pela dica de contexto.
    """

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


def legenda_faixas(titulo: str, incluir_sem_dado: bool = False,
                   incluir_fora: bool = False) -> str:
    """Legenda do mapa por UF: faixas de ocupação e os dois cinzas."""
    itens = [
        (glifo, rotulo, texto, cor)
        for _, rotulo, glifo, texto, cor in FAIXAS_OCUPACAO
    ]
    if incluir_sem_dado:
        rotulo, glifo, texto, cor = SEM_DADO
        itens.append((glifo, rotulo, texto, cor))
    if incluir_fora:
        rotulo, glifo, texto, cor = FORA_DO_RECORTE
        itens.append((glifo, rotulo, texto, cor))
    return _legenda(titulo, itens)


def legenda_icpa(titulo: str, incluir_fora_do_indice: bool = False) -> str:
    """Legenda do mapa por município: faixas do ICPA e o fora do índice."""
    itens = [
        (glifo, rotulo, texto, cor)
        for _, rotulo, glifo, texto, cor in FAIXAS_ICPA
    ]
    if incluir_fora_do_indice:
        rotulo, glifo, texto, cor = FORA_DO_INDICE
        itens.append((glifo, rotulo, texto, cor))
    return _legenda(titulo, itens)


# Largura presumida do cartão do mapa, em pixels. A altura vem da grade e
# é conhecida; a largura não, porque a coluna é fluida. Presumir uma
# largura curta deixa margem sobrando em tela larga — que é o erro barato.
# O contrário cortaria o estado pelas laterais, e mapa cortado não é mapa.
_LARGURA_MAPA = 440

# Tamanho do tile do deck.gl: no zoom z o mundo inteiro tem 512 · 2^z px.
_TILE = 512


def _mercator(latitude: float) -> float:
    """Latitude em fração vertical do mundo, na projeção do mapa."""
    latitude = max(min(latitude, 85.0), -85.0)
    return math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))


@st.cache_data(show_spinner=False)
def limites_municipios(uf: str) -> tuple[float, float, float, float] | None:
    """Caixa (oeste, sul, leste, norte) que cobre os municípios da UF."""
    lons: list[float] = []
    lats: list[float] = []

    def coletar(coordenadas) -> None:
        # GeoJSON aninha coordenadas em profundidade variável (Polygon e
        # MultiPolygon diferem em um nível), então a descida é genérica:
        # par de números é ponto, qualquer outra coisa é lista de partes.
        if coordenadas and isinstance(coordenadas[0], (int, float)):
            lons.append(coordenadas[0])
            lats.append(coordenadas[1])
            return
        for parte in coordenadas:
            coletar(parte)

    for feicao in carregar_malha_municipios(uf)["features"]:
        coletar(feicao["geometry"]["coordinates"])
    if not lons:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _vista(limites, altura: int) -> pdk.ViewState:
    """
    Enquadramento que cabe a caixa inteira dentro do cartão.

    O zoom sai do menor entre o que a largura permite e o que a altura
    permite: fechar pelo maior encheria o cartão e cortaria o estado no
    outro eixo. Estados largos (o Pará) fecham pela largura; estados
    compridos (o Amazonas, o Rio Grande do Sul) fecham pela altura.
    """
    if limites is None:
        return pdk.ViewState(latitude=-14.5, longitude=-53.0, zoom=2.4,
                             min_zoom=2, max_zoom=9)
    oeste, sul, leste, norte = limites
    # 8% de folga para o contorno não encostar na borda do cartão.
    vao_lon = max((leste - oeste) * 1.08, 1e-6)
    vao_y = max((_mercator(norte) - _mercator(sul)) / (2 * math.pi) * 1.08, 1e-9)
    zoom = min(math.log2(_LARGURA_MAPA * 360 / (_TILE * vao_lon)),
               math.log2(altura / (_TILE * vao_y)))
    # O centro vertical é o meio da caixa JÁ projetada, e não a média das
    # latitudes: em Mercator os graus de cima são mais altos que os de
    # baixo, e a média crua desloca o estado para fora do quadro.
    y_centro = (_mercator(norte) + _mercator(sul)) / 2
    return pdk.ViewState(
        latitude=math.degrees(2 * math.atan(math.exp(y_centro)) - math.pi / 2),
        longitude=(oeste + leste) / 2,
        zoom=max(2.0, min(round(zoom, 2), 9.0)),
        min_zoom=2, max_zoom=9,
    )


class _DeckCompacto(pdk.Deck):
    """
    Deck que serializa sem indentação.

    O pydeck escreve o JSON com indent=2 e o Streamlit manda essa string
    inteira ao navegador a cada rerun. Num mapa de 853 municípios a
    indentação sozinha responde por três quartos do payload — 2,4 MB
    contra 0,6 MB, em cada troca de filtro.

    O to_json do pydeck é reaproveitado, e não substituído: são os
    serializadores dele que produzem o `@@type` da camada e as expressões
    que leem properties. Daqui sai só o espaço em branco. Se um dia a
    saída deixar de ser JSON parseável, devolve-se a original — payload
    grande é ruim, mapa quebrado é pior.
    """

    def to_json(self) -> str:
        bruto = super().to_json()
        try:
            return json.dumps(json.loads(bruto), separators=(",", ":"))
        except ValueError:
            return bruto


def _deck_coropletico(feicoes, campos, *, rotulo_medida: str, altura: int,
                      vista: pdk.ViewState, identificador: str,
                      espessura_linha: float = 1) -> pdk.Deck:
    """
    Camada, dica de contexto e enquadramento — o que os dois mapas têm em
    comum.

    Toda feição chega com as mesmas chaves PLANAS em properties: `titulo`,
    `situacao`, `medida` e `cor`, mais uma por campo de contexto. O
    interpolador do tooltip do Streamlit resolve `{chave}` contra
    properties[chave] e não aceita caminho pontilhado — nada aqui pode
    ser aninhado.

    O `id` da camada não é decoração: é por ele que o st.pydeck_chart
    devolve a seleção, quando o mapa passar a responder ao clique.
    """
    linhas_dica = "".join(
        f'<div style="opacity:.75">{titulo}: <b>{{{coluna}}}</b></div>'
        for coluna, titulo in campos
    )
    return _DeckCompacto(
        layers=[pdk.Layer(
            "GeoJsonLayer",
            id=identificador,
            data={"type": "FeatureCollection", "features": feicoes},
            stroked=True, filled=True, pickable=True,
            get_fill_color="properties.cor",
            get_line_color=[255, 255, 255],
            line_width_min_pixels=espessura_linha,
        )],
        initial_view_state=vista,
        map_style=None,
        tooltip={
            "html": (
                '<div style="font-size:12px"><b>{titulo}</b> · {situacao}'
                f'<div style="opacity:.75">{rotulo_medida}: <b>{{medida}}</b></div>'
                f"{linhas_dica}</div>"
            ),
            "style": {"backgroundColor": "#1F2933", "color": "#FFFFFF",
                      "borderRadius": "6px", "padding": "8px 10px"},
        },
        height=altura,
    )


def mapa_uf(dados: pd.DataFrame, valor: str, campos, *,
            titulo_legenda: str = "", altura: int = 340,
            fora_do_recorte: bool = False):
    """
    Coroplético das UFs por faixa de ocupação. Devolve (deck, legenda).

    A cor aqui é de status, não de grandeza: ela diz em que situação a UF
    está diante da própria capacidade instalada, e por isso os cortes são
    fixos. Volume absoluto não serve para colorir mapa — pintaria São
    Paulo de escuro todo mês só por ser São Paulo, e a leitura viraria
    "onde mora mais gente", que o mapa já mostra pelo tamanho.

    UF sem produção registrada sai em cinza, e não na cor de folga: leito
    vazio por falta de dado não é leito vazio por sobra de capacidade.

    `fora_do_recorte` diz que `dados` já vem filtrado por região ou por UF
    — as UFs ausentes ficam apagadas e sem número, marcadas como fora do
    recorte em vez de sem produção. O mapa passa a responder ao filtro
    territorial inteiro, e não só à região.

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

    feicoes, houve_sem_dado, houve_fora = [], False, False
    for feicao in malha["features"]:
        sigla = feicao["properties"]["uf"]
        linha = por_uf.get(sigla)
        bruto = None if linha is None else linha[valor]
        # Ausente do resultado com recorte ativo é UF que o filtro deixou
        # de fora; sem recorte, é ausência de dado mesmo. UF dentro do
        # recorte e com ocupação zerada continua caindo em SEM_DADO pelo
        # próprio valor, que é a leitura certa para ela.
        if linha is None and fora_do_recorte:
            rotulo, glifo, _, cor = FORA_DO_RECORTE
            houve_fora = True
        else:
            rotulo, glifo, _, cor = faixa_ocupacao(bruto)
            if rotulo == SEM_DADO[0]:
                houve_sem_dado = True

        propriedades = {
            "uf": sigla,
            "titulo": sigla,
            "situacao": f"{glifo} {rotulo}",
            "medida": "—" if bruto is None or pd.isna(bruto) or bruto <= 0
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

    deck = _deck_coropletico(
        feicoes, campos, rotulo_medida="Ocupação estimada", altura=altura,
        vista=pdk.ViewState(latitude=-14.5, longitude=-53.0, zoom=2.4,
                            min_zoom=2, max_zoom=6),
        identificador="ufs",
    )
    return deck, legenda_faixas(titulo_legenda or "Ocupação estimada",
                                incluir_sem_dado=houve_sem_dado,
                                incluir_fora=houve_fora)


def mapa_municipios(dados: pd.DataFrame, uf: str, valor: str, campos, *,
                    titulo_legenda: str = "", altura: int = 340):
    """
    Coroplético dos municípios de uma UF pela faixa do ICPA. Devolve
    (deck, legenda), como o mapa por estado.

    É o mesmo cartão do mapa por UF, um nível abaixo: quando o filtro
    escolhe um estado, a pergunta deixa de ser "qual estado aperta" e
    passa a ser "onde, dentro dele". A medida muda junto, e não por
    capricho — ver o comentário de FAIXAS_ICPA.

    Município fora do índice sai em cinza. Ele é maioria em boa parte do
    país, e é o achado central do projeto: contorno vazio no mapa é
    ausência de serviço, não falta de dado.

    A junção com a malha é pelo código do IBGE de sete dígitos, que a
    consulta traz em `cod_ibge` — a Gold guarda o do DATASUS, de seis.
    """
    malha = carregar_malha_municipios(uf)
    medida = pd.to_numeric(dados[valor], errors="coerce")
    por_codigo = {
        str(linha["cod_ibge"]): linha
        for _, linha in dados.assign(**{valor: medida}).iterrows()
    }

    feicoes, houve_fora = [], False
    for feicao in malha["features"]:
        codigo = str(feicao["properties"]["codarea"])
        linha = por_codigo.get(codigo)
        bruto = None if linha is None else linha[valor]
        rotulo, glifo, _, cor = faixa_icpa(bruto)
        if rotulo == FORA_DO_INDICE[0]:
            houve_fora = True

        propriedades = {
            "cod_ibge": codigo,
            "titulo": codigo if linha is None else str(linha["municipio"]),
            "situacao": f"{glifo} {rotulo}",
            "medida": "—" if bruto is None or pd.isna(bruto) else num(bruto, 1),
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

    deck = _deck_coropletico(
        feicoes, campos, rotulo_medida="ICPA", altura=altura,
        vista=_vista(limites_municipios(uf), altura),
        identificador="municipios",
        # Contorno mais fino que o do mapa por estado: com centenas de
        # municípios no mesmo quadro, a linha de 1px come o preenchimento
        # e o mapa vira uma malha branca.
        espessura_linha=0.4,
    )
    return deck, legenda_icpa(titulo_legenda or "Faixa de pressão (ICPA)",
                              incluir_fora_do_indice=houve_fora)


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


# Siglas que devem sair em caixa alta mesmo quando o nome da coluna não
# está no mapa acima. O Select AI batiza as colunas do resultado como bem
# entende — "Indice_ICPA", "TOTAL_INTERNACOES" — então o rótulo precisa
# funcionar para nomes que nunca existiram no esquema.
SIGLAS = {"icpa", "uf", "cnes", "sus", "uti", "sih", "ibge", "aih", "cid"}


def titulo_coluna(nome: str) -> str:
    """Rótulo de exibição para um nome de coluna, do banco ou do modelo."""
    conhecido = TITULOS_COLUNA.get(nome.lower())
    if conhecido:
        return conhecido
    palavras = [
        p.upper() if p.lower() in SIGLAS else p.lower()
        for p in nome.replace("_", " ").split()
    ]
    if not palavras:
        return nome
    if palavras[0].lower() not in SIGLAS:
        palavras[0] = palavras[0].capitalize()
    return " ".join(palavras)


def rotulo_medida(nome: str) -> str:
    """
    Título em caixa de frase para usar no meio de uma frase.

    Só as palavras comuns descem para minúscula: baixar a sigla junto
    produziria "leitos sus" e "indice icpa" no meio do texto.
    """
    return " ".join(
        palavra if palavra.lower() in SIGLAS else palavra.lower()
        for palavra in titulo_coluna(nome).split()
    )


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


def leitura_do_resultado(dados: pd.DataFrame) -> list[str]:
    """
    Frases derivadas do próprio resultado devolvido pela consulta.

    São contas sobre as linhas em tela — quem lidera, quanto o topo
    concentra, qual a amplitude. Nada aqui vem de modelo: a narrativa do
    Select AI tem espaço próprio na página, e misturar as duas tiraria do
    leitor a chance de saber o que é dado e o que é redação.

    Mora aqui, e não em ai.py, porque depende do mesmo par que decide a
    forma do gráfico — medida_principal e titulo_coluna. A leitura e o
    desenho precisam falar da mesma medida.
    """
    if dados is None or dados.empty or len(dados) < 2:
        return []

    tempo = next((c for c in dados.columns if c.lower() in COLUNAS_TEMPO), None)
    numericas = [c for c in dados.columns if c != tempo and e_numerica(dados[c])]
    categoricas = [c for c in dados.columns
                   if c not in numericas and c != tempo]
    if not numericas:
        return []

    valor = medida_principal(dados, numericas)
    medida = pd.to_numeric(dados[valor], errors="coerce").dropna()
    if medida.empty:
        return []

    nome = rotulo_medida(valor)
    casas = 0 if float(medida.abs().max()) >= 100 else 2
    notas: list[str] = []

    if categoricas:
        notas.append(
            f"Maior **{nome}**: {dados.loc[medida.idxmax(), categoricas[0]]}, "
            f"com {num(medida.max(), casas)}."
        )

    # Concentração só vale para medida que soma. Para índice, taxa ou
    # média, a leitura equivalente é quantas linhas passam da mediana.
    if e_aditiva(valor):
        total = float(medida.sum())
        if total > 0 and len(medida) >= 4:
            topo = float(medida.nlargest(3).sum())
            notas.append(
                f"As três primeiras linhas concentram "
                f"**{pct(topo / total * 100, 0)}** do total de {nome}."
            )
    elif len(medida) >= 4:
        acima = int((medida > medida.median()).sum())
        notas.append(
            f"**{num(acima)}** das {num(len(medida))} linhas ficam acima da "
            f"mediana de {nome} — medida de índice não se soma, então a "
            "leitura aqui é de dispersão, não de concentração."
        )

    if len(medida) >= 3:
        notas.append(
            f"Amplitude: de {num(medida.min(), casas)} a "
            f"{num(medida.max(), casas)}, mediana {num(medida.median(), casas)}."
        )

    return notas
