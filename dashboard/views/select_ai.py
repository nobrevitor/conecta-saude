"""
Página 3 · Assistente Select AI

Pergunta em português, resposta em quatro partes.

A tradução para SQL acontece dentro do Autonomous Database. Esta página
não conhece o modelo nem a chave: ela manda a pergunta ao módulo ai e
compõe o que volta.

    Resposta       narrativa do modelo, leitura calculada e gráfico
    SQL gerado     o que foi executado, para auditoria
    Resultado      a tabela completa, com download

A forma do gráfico não é fixa: sai de ui.grafico_automatico, que decide
pelo formato do resultado — coluna de tempo com uma medida vira linha,
uma categoria com uma medida vira barra ordenada, o resto continua
tabela, que é a forma honesta quando não dá para afirmar o que o dado é.
"""

import streamlit as st

import ai
import db
import ui

ativo, mensagem = ai.disponivel()

competencias = ui.listar_ou_vazio(db.listar_competencias)

with st.sidebar:
    st.markdown('<div class="cs-slicer">Filtros</div>', unsafe_allow_html=True)
    competencia = st.selectbox(
        "Competência de referência", competencias or ["—"],
        index=max(len(competencias) - 1, 0),
        format_func=ui.competencia_legivel,
    )

ui.cabecalho(
    "Assistente Select AI",
    "Consulta em linguagem natural pelo Autonomous Database",
)

if not ativo:
    st.error(mensagem, icon=":material/error:")
    st.stop()

# O provedor ativo é contexto permanente, não um alerta: uma linha, para
# não empurrar a entrada para fora da primeira tela a cada execução.
st.caption(f":material/database: {mensagem}")

# ---------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------

coluna_pergunta, coluna_ajuda = st.columns([3, 1], gap="small")

with coluna_pergunta:
    bloco = ui.painel("Pergunte aos dados", chave="pergunta",
                      altura=ui.ALTURA_CARTAO_BAIXO)
    with bloco:
        pergunta = st.text_area(
            "Sua pergunta",
            value=st.session_state.get("pergunta_escolhida", ""),
            placeholder="Quais regiões têm maior pressão assistencial e "
                        "menor oferta de leitos por habitante?",
            height=110,
            label_visibility="collapsed",
        )
        st.caption("Ou comece por uma destas:")
        colunas = st.columns(3)
        for indice, exemplo in enumerate(ai.PERGUNTAS_EXEMPLO[:3]):
            rotulo = exemplo if len(exemplo) <= 38 else exemplo[:35] + "..."
            if colunas[indice].button(rotulo, key=f"exemplo_{indice}",
                                      width="stretch"):
                st.session_state["pergunta_escolhida"] = exemplo
                st.rerun()

        enviar = st.button("Gerar análise", type="primary", width="stretch")

with coluna_ajuda:
    bloco = ui.painel("Como funciona", chave="ajuda",
                      altura=ui.ALTURA_CARTAO_BAIXO)
    bloco.markdown(
        "A pergunta é traduzida em SQL pelo **Select AI**, executado "
        "dentro do próprio Autonomous Database. O modelo enxerga apenas "
        "as tabelas da camada Gold."
    )
    bloco.caption(
        "O SQL fica visível na aba correspondente — nada é executado sem "
        "que você possa auditar. Comandos de escrita são bloqueados antes "
        "de chegar ao banco, e o usuário da aplicação tem permissão "
        "apenas de leitura."
    )

# ---------------------------------------------------------------------
# Resposta
# ---------------------------------------------------------------------

if enviar and pergunta:
    st.session_state.pop("pergunta_escolhida", None)

    with st.spinner("Traduzindo a pergunta em SQL e consultando o banco..."):
        resposta = ai.perguntar(pergunta, competencia)

    if resposta.erro:
        st.error(resposta.erro, icon=":material/error:")
        if resposta.sql:
            st.caption("SQL que seria executado:")
            st.code(resposta.sql, language="sql")
        st.stop()

    coluna_resposta, coluna_lateral = st.columns([3, 1], gap="small")

    with coluna_resposta:
        aba_resposta, aba_sql, aba_dados = st.tabs(
            ["Resposta", "SQL gerado", "Resultado estruturado"]
        )

        with aba_resposta:
            st.markdown(f"**{resposta.pergunta}**")
            if resposta.narrativa:
                st.write(resposta.narrativa)
            if resposta.tem_dados:
                grafico, legenda = ui.grafico_automatico(resposta.dados)
                if grafico is not None:
                    st.altair_chart(grafico, width="stretch", theme=None)
                else:
                    st.dataframe(resposta.dados.head(15),
                                 width="stretch", hide_index=True)
                st.caption(legenda)
            else:
                ui.bloco_vazio("A consulta não retornou linhas.")

        with aba_sql:
            st.caption("Somente leitura. Comandos de escrita são bloqueados.")
            st.code(resposta.sql, language="sql")

        with aba_dados:
            if not resposta.tem_dados:
                ui.bloco_vazio("A consulta não retornou linhas.")
            else:
                st.dataframe(resposta.dados, width="stretch", hide_index=True)
                st.download_button(
                    "Baixar em CSV",
                    resposta.dados.to_csv(index=False).encode("utf-8"),
                    file_name="conecta_saude_consulta.csv",
                    mime="text/csv",
                    icon=":material/download:",
                )

    with coluna_lateral:
        bloco = ui.painel("O que o resultado mostra", chave="leitura_ai")
        with bloco:
            if resposta.tem_dados:
                st.metric("Linhas", ui.num(len(resposta.dados)))
                st.metric("Colunas", ui.num(len(resposta.dados.columns)))

            # Contas sobre as linhas devolvidas, separadas da narrativa do
            # modelo de propósito: o leitor precisa saber o que é dado
            # verificado e o que é redação.
            notas = ui.leitura_do_resultado(resposta.dados)
            if notas:
                st.divider()
                for nota in notas:
                    st.markdown(f":material/arrow_right: {nota}")

        seguintes = [p for p in ai.PERGUNTAS_EXEMPLO if p != resposta.pergunta][:3]
        if seguintes:
            bloco = ui.painel("Continuar por aqui", chave="seguintes")
            with bloco:
                for indice, proxima in enumerate(seguintes):
                    if st.button(proxima, key=f"seguinte_{indice}",
                                 width="stretch"):
                        st.session_state["pergunta_escolhida"] = proxima
                        st.rerun()

ui.rodape([
    "O **SQL** de cada resposta fica visível na aba correspondente. O "
    "usuário da aplicação tem permissão apenas de leitura, e comandos de "
    "escrita são bloqueados antes de chegar ao banco.",
    "A **narrativa** é redigida pelo modelo. O painel *O que o resultado "
    "mostra* é calculado sobre as linhas devolvidas — medidas de índice, "
    "taxa ou média não são somadas, e para elas a leitura é de dispersão.",
    "O **gráfico** é escolhido pelo formato do resultado: coluna de tempo "
    "com uma medida vira linha; uma categoria com uma medida vira barra "
    "ordenada; o resto continua tabela.",
])
