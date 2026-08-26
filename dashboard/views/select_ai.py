"""
Página 3 · Assistente de consulta

Pergunta em linguagem natural sobre a camada Gold.

A página não escolhe o provedor: ela pergunta ao módulo ai qual modo
está disponível e se adapta. Isso significa que o mesmo código funciona
com Select AI, com Gemini ou sem LLM nenhum — e que trocar de provedor
não exige mexer aqui.

As visualizações estão como PLACEHOLDER; estrutura e lógica completas.
"""

import streamlit as st

import ai
import db
import ui

modo, mensagem = ai.modo_disponivel()

TITULOS = {
    "select_ai": ("Assistente Select AI",
                  "Consulta em linguagem natural pelo Autonomous Database"),
    "gemini": ("Assistente de consulta",
               "Consulta em linguagem natural sobre os dados do SUS"),
    "catalogo": ("Consultas analíticas",
                 "Perguntas pré-definidas sobre a camada Gold"),
}
titulo, subtitulo = TITULOS[modo]

ui.cabecalho(titulo, subtitulo)

competencias = db.listar_competencias()
coluna_comp, coluna_status = st.columns([1, 3])

with coluna_comp:
    competencia = st.selectbox(
        "Competência de referência",
        competencias,
        index=len(competencias) - 1,
        format_func=ui.competencia_legivel,
    )

with coluna_status:
    st.write("")
    if modo == "select_ai":
        st.success(mensagem, icon=":material/database:")
    elif modo == "gemini":
        st.info(mensagem, icon=":material/smart_toy:")
    else:
        st.warning(
            f"{mensagem} As consultas abaixo são pré-escritas e validadas, "
            "e não dependem de provedor externo.",
            icon=":material/info:",
        )

st.write("")

# ---------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------

pergunta_livre = modo in ("select_ai", "gemini")

esquerda, direita = st.columns([3, 1])

with esquerda:
    bloco = ui.painel("Pergunte aos dados")
    with bloco:
        if pergunta_livre:
            pergunta = st.text_area(
                "Sua pergunta",
                value=st.session_state.get("pergunta_escolhida", ""),
                placeholder="Quais regiões têm maior pressão assistencial e "
                            "menor oferta de leitos por habitante?",
                height=110,
                label_visibility="collapsed",
            )
            st.caption("Ou escolha uma pergunta pronta:")
            colunas = st.columns(3)
            for indice, exemplo in enumerate(list(ai.CATALOGO)[:3]):
                rotulo = exemplo if len(exemplo) <= 40 else exemplo[:37] + "..."
                if colunas[indice].button(rotulo, key=f"sug_{indice}",
                                          use_container_width=True):
                    st.session_state["pergunta_escolhida"] = exemplo
                    st.rerun()
        else:
            pergunta = st.selectbox(
                "Escolha uma pergunta",
                list(ai.CATALOGO),
                label_visibility="collapsed",
            )

        enviar = st.button("Gerar análise", type="primary", use_container_width=True)

with direita:
    bloco = ui.painel("Como funciona")
    if modo == "select_ai":
        bloco.markdown(
            "A pergunta é traduzida em SQL pelo **Select AI**, executado "
            "dentro do próprio Autonomous Database."
        )
    elif modo == "gemini":
        bloco.markdown(
            "O esquema da camada Gold é enviado ao **Gemini**, que devolve "
            "o SQL. A execução acontece no Autonomous Database."
        )
    else:
        bloco.markdown(
            "Consultas **pré-escritas e validadas**, executadas diretamente "
            "no Autonomous Database."
        )
    bloco.caption(
        "O SQL fica visível na aba correspondente — nada é executado sem "
        "que você possa auditar. O usuário da aplicação tem permissão "
        "apenas de leitura, e comandos de escrita são bloqueados antes de "
        "chegar ao banco."
    )

# ---------------------------------------------------------------------
# Resposta
# ---------------------------------------------------------------------

if enviar and pergunta:
    st.session_state.pop("pergunta_escolhida", None)

    with st.spinner("Interpretando a pergunta e consultando o banco..."):
        resposta = ai.perguntar(pergunta, competencia, modo)

    st.write("")

    if resposta.erro:
        st.error(f"Não foi possível responder: {resposta.erro}")
        if resposta.sql:
            st.caption("SQL que seria executado:")
            st.code(resposta.sql, language="sql")
        st.stop()

    coluna_resposta, coluna_lateral = st.columns([3, 1])

    with coluna_resposta:
        aba_resposta, aba_sql, aba_dados = st.tabs(
            ["Resposta", "SQL gerado", "Resultado estruturado"]
        )

        with aba_resposta:
            st.markdown(f"**{resposta.pergunta}**")
            st.write(resposta.narrativa or "Consulta executada com sucesso.")
            if not resposta.dados.empty:
                # PLACEHOLDER · escolher o gráfico conforme o formato do
                # resultado: barras para ranking, linha para série temporal
                st.dataframe(resposta.dados.head(15),
                             use_container_width=True, hide_index=True)

        with aba_sql:
            st.caption("Somente leitura. Comandos de escrita são bloqueados.")
            st.code(resposta.sql or "—", language="sql")

        with aba_dados:
            if resposta.dados.empty:
                st.info("A consulta não retornou linhas.")
            else:
                st.dataframe(resposta.dados, use_container_width=True, hide_index=True)
                st.download_button(
                    "Baixar em CSV",
                    resposta.dados.to_csv(index=False).encode("utf-8"),
                    file_name="conecta_saude_consulta.csv",
                    mime="text/csv",
                )

    with coluna_lateral:
        bloco = ui.painel("Sobre esta resposta")
        rotulos = {
            "select_ai": ("Select AI", "Pergunta traduzida em SQL pelo banco."),
            "gemini": ("Gemini", "Pergunta traduzida em SQL pelo modelo."),
            "catalogo": ("Catálogo", "Consulta pré-escrita e validada."),
        }
        nome, explicacao = rotulos[resposta.origem]
        bloco.markdown(f"**{nome}**")
        bloco.caption(explicacao)
        if not resposta.dados.empty:
            bloco.metric("Linhas", ui.num(len(resposta.dados)))
            bloco.metric("Colunas", ui.num(len(resposta.dados.columns)))

        # PLACEHOLDER · painel de insights automáticos e ações sugeridas

ui.rodape()
