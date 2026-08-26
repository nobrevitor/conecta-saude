"""
Conecta Saúde — Painel de Pressão Assistencial do SUS
Challenge 2026 · Oracle + FIAP

Ponto de entrada. Só monta a navegação; cada página vive em views/.

Fontes: SIH/SUS, CNES, SIGTAP (DATASUS) e IBGE · competências 202401-202412
Arquitetura: Object Storage → Autonomous AI Database → Streamlit
"""

from pathlib import Path

import streamlit as st

# Caminhos resolvidos a partir do próprio arquivo: o painel roda igual
# tanto com `streamlit run app.py` quanto a partir da raiz do repositório.
DOCS = Path(__file__).parent / "docs"
LOGO_CLARO = DOCS / "conecta_saude_logo.svg"
LOGO_ESCURO = DOCS / "conecta_saude_icone_sem_texto_para_fundo_escuro_transparente.png"
LOGO_ICONE = DOCS / "conecta-saude-icone.svg"

st.set_page_config(
    page_title="Conecta Saúde",
    page_icon=LOGO_ICONE,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilo compartilhado. Mantido aqui para valer nas três páginas.
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1500px; }
      [data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 600; }
      [data-testid="stMetricLabel"] { font-size: 0.78rem; opacity: 0.75; }
      [data-testid="stMetric"] {
          background: #FFFFFF;
          border: 1px solid #E3EAED;
          border-radius: 10px;
          padding: 0.9rem 1rem;
      }
      /* st.logo satura em 2rem (o "large" da API) e escala pela altura.
         Como o nosso logo é o lockup horizontal, subimos a altura aqui e
         abrimos espaço no cabeçalho do sidebar, que é fixo em 3.75rem. */
      [data-testid="stSidebarHeader"] { height: 6.5rem !important; }
      [data-testid="stSidebarLogo"] { height: 5.5rem !important; }
      /* Recolhido, o logo migra para o cabeçalho principal (3.75rem). */
      [data-testid="stHeaderLogo"] { height: 2.5rem !important; }
      h1 { font-size: 1.9rem !important; }
      h2 { font-size: 1.25rem !important; }
      h3 { font-size: 1.02rem !important; }
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
