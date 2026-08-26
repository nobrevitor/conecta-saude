"""
Conecta Saúde — Painel de Pressão Assistencial do SUS
Challenge 2026 · Oracle + FIAP

Ponto de entrada. Só monta a navegação; cada página vive em views/.

Fontes: SIH/SUS, CNES, SIGTAP (DATASUS) e IBGE · competências 202401-202412
Arquitetura: Object Storage → Autonomous AI Database → Streamlit
"""

from pathlib import Path

import streamlit as st

# Caminhos resolvidos a partir do próprio arquivo, e absolutos: o painel
# roda igual tanto com `streamlit run app.py` quanto a partir da raiz do
# repositório. O resolve() importa porque em execução programática o
# __file__ chega relativo, e aí o parent sozinho não sai do diretório atual.
DOCS = Path(__file__).resolve().parent / "docs"
LOGO_CLARO = DOCS / "conecta_saude_logo.svg"      # lockup, sidebar aberto
LOGO_ICONE = DOCS / "conecta-saude-icone.svg"     # símbolo, sidebar recolhido
LOGO_ESCURO = DOCS / "conecta_saude_icone_sem_texto_para_fundo_escuro_transparente.png"

st.set_page_config(
    page_title="Conecta Saúde",
    page_icon=LOGO_ESCURO,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilo compartilhado pelas três páginas.
#
# O arranjo é o de um painel de BI: tela larga, respiro curto, cartões de
# borda fina e tipografia menor que a do Streamlit padrão — que é feita
# para documento, não para grade. As medidas estão aqui, e não espalhadas
# pelas views, porque o alinhamento das linhas depende de todas as
# páginas usarem os mesmos valores.
st.markdown(
    """
    <style>
      /* ---------- Tela ---------- */
      .block-container {
          padding: 1.1rem 1.5rem 1.5rem;
          max-width: 1760px;
      }
      /* Grade apertada: o padrão do Streamlit separa blocos como texto
         corrido, e num painel isso vira rolagem sem conteúdo novo. */
      [data-testid="stVerticalBlock"] { gap: 0.55rem; }
      [data-testid="stHorizontalBlock"] { gap: 0.6rem; }

      /* ---------- Cabeçalho da página ---------- */
      .cs-cabecalho { line-height: 1.3; }
      .cs-titulo {
          font-size: 1.32rem; font-weight: 650; color: #1F2933;
          letter-spacing: -0.01em;
      }
      .cs-subtitulo { font-size: 0.78rem; color: #5A6B75; margin-top: 1px; }
      .cs-fichas { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 7px; }
      .cs-ficha {
          font-size: 0.69rem; font-weight: 600; letter-spacing: 0.02em;
          color: #0F5C73; background: #E8F1F4; border: 1px solid #D3E3E9;
          border-radius: 999px; padding: 2px 9px;
      }

      /* ---------- Fita de indicadores ---------- */
      [data-testid="stMetric"] {
          background: #FFFFFF;
          border: 1px solid #E3EAED;
          border-radius: 8px;
          padding: 0.6rem 0.8rem;
          box-shadow: 0 1px 2px rgba(15, 92, 115, 0.05);
      }
      [data-testid="stMetricLabel"] {
          font-size: 0.72rem; opacity: 0.8; font-weight: 500;
      }
      [data-testid="stMetricValue"] {
          font-size: 1.42rem; font-weight: 640; letter-spacing: -0.01em;
      }
      [data-testid="stMetricDelta"] { font-size: 0.71rem; }

      /* ---------- Cartões da grade ---------- */
      /* A borda vem do próprio st.container(border=True); daqui sai só o
         relevo, que é o que separa cartão de fundo num painel de BI. */
      [class*="st-key-cartao_"] {
          box-shadow: 0 1px 2px rgba(15, 92, 115, 0.05);
          border-radius: 8px;
      }
      .cs-cartao-topo { margin-bottom: 0.15rem; }
      .cs-cartao-titulo {
          font-size: 0.82rem; font-weight: 650; color: #1F2933;
          letter-spacing: -0.005em;
      }
      .cs-cartao-sub {
          font-size: 0.71rem; color: #5A6B75; margin-top: 1px;
      }

      /* ---------- Barra lateral ---------- */
      .cs-slicer {
          font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.07em; color: #5A6B75;
          margin: 0.5rem 0 -0.2rem;
      }
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.4rem; }

      /* ---------- Rodapé ---------- */
      .cs-rodape {
          display: flex; justify-content: space-between; flex-wrap: wrap;
          gap: 8px; font-size: 0.7rem; color: #8B9AA3;
          border-top: 1px solid #E3EAED; padding-top: 0.5rem;
          margin-top: 0.4rem;
      }
      .cs-estado { font-variant-numeric: tabular-nums; }

      /* ---------- Tipografia de conteúdo ---------- */
      /* Legendas e abas descem de tamanho junto com o resto: num painel
         elas são apoio, não leitura principal. */
      [data-testid="stCaptionContainer"] { font-size: 0.71rem; }
      .stTabs [data-baseweb="tab"] { font-size: 0.78rem; padding: 0 0.7rem; }
      h1 { font-size: 1.9rem !important; }
      h2 { font-size: 1.25rem !important; }
      h3 { font-size: 1.02rem !important; }

      /* ---------- Logo ---------- */
      /* st.logo satura em 2rem (o "large" da API) e escala pela altura.
         Como o nosso logo é o lockup horizontal, subimos a altura aqui e
         abrimos espaço no cabeçalho do sidebar, que é fixo em 3.75rem. */
      [data-testid="stSidebarHeader"] { height: 6.5rem !important; }
      [data-testid="stSidebarLogo"] { height: 5.5rem !important; }
      /* Recolhido, o logo migra para o cabeçalho principal (3.75rem). */
      [data-testid="stHeaderLogo"] { height: 2.5rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

visao_geral = st.Page(
    "views/visao_geral.py",
    title="Visão geral da rede",
    icon=":material/dashboard:",
    default=True,
)

capacidade = st.Page(
    "views/capacidade.py",
    title="Indicadores de capacidade",
    icon=":material/monitor_heart:",
)

select_ai = st.Page(
    "views/select_ai.py",
    title="Assistente Select AI",
    icon=":material/smart_toy:",
)

navegacao = st.navigation(
    {
        "Painéis": [visao_geral, capacidade],
        "Consulta": [select_ai],
    }
)

# Tema claro (config.toml): lockup completo no sidebar aberto e só o
# símbolo quando ele está recolhido. A altura real vem do CSS acima.
st.logo(str(LOGO_CLARO), size="large", icon_image=str(LOGO_ICONE))

navegacao.run()
