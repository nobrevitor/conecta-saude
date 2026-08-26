"""
Componentes de interface compartilhados pelas três páginas.

Concentra aqui o que se repete — filtros, formatação e cabeçalho — para
que cada view cuide só do que é específico dela.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
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


def barra_filtros(mostrar_porte: bool = True) -> Filtros:
    """Filtros no topo da página, como nas telas de referência."""
    competencias = db.listar_competencias()
    regioes = ["Todos"] + db.listar_regioes()

    colunas = st.columns([1, 1, 1, 1, 0.8] if mostrar_porte else [1, 1, 1, 0.8])

    with colunas[0]:
        competencia = st.selectbox(
            "Competência", competencias,
            index=len(competencias) - 1,
            format_func=competencia_legivel,
            key="f_competencia",
        )

    with colunas[1]:
        regiao = st.selectbox("Região", regioes, key="f_regiao")

    with colunas[2]:
        ufs = ["Todos"] + db.listar_ufs(None if regiao == "Todos" else regiao)
        uf = st.selectbox("UF", ufs, key="f_uf")

    porte = "Todos"
    if mostrar_porte:
        with colunas[3]:
            porte = st.selectbox("Porte do município", PORTES, key="f_porte")

    with colunas[-1]:
        st.write("")
        if st.button("Limpar filtros", use_container_width=True):
            for chave in ("f_regiao", "f_uf", "f_porte"):
                st.session_state.pop(chave, None)
            st.rerun()

    return Filtros(competencia=competencia, regiao=regiao, uf=uf, porte=porte)


# ---------------------------------------------------------------------
# Cabeçalho e rodapé
# ---------------------------------------------------------------------

def cabecalho(titulo: str, subtitulo: str) -> None:
    esquerda, direita = st.columns([4, 1])
    with esquerda:
        st.title(titulo)
        st.caption(subtitulo)
    with direita:
        st.write("")
        if st.button("Atualizar dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


def rodape() -> None:
    st.divider()
    esquerda, direita = st.columns([4, 1])
    with esquerda:
        st.caption(
            "Conecta Saúde · Challenge 2026 Oracle + FIAP · "
            "Dados públicos do DATASUS (SIH/SUS, CNES, SIGTAP) e IBGE, "
            "competências 202401 a 202412."
        )
    with direita:
        conectado, _ = db.testar_conexao()
        st.caption(f"Banco: {'conectado' if conectado else 'indisponível'}")


def aviso_metodologico(texto: str) -> None:
    """Ressalvas de método. Usar sempre que o número for estimativa."""
    st.caption(f":grey[{texto}]")


def bloco_vazio(mensagem: str = "Sem dados para os filtros selecionados.") -> None:
    st.info(mensagem, icon=":material/info:")


def painel(titulo: str, descricao: str | None = None):
    """Container com borda, no padrão dos cartões das telas de referência."""
    caixa = st.container(border=True)
    caixa.markdown(f"**{titulo}**")
    if descricao:
        caixa.caption(descricao)
    return caixa
