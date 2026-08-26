"""
Página 3 · Assistente de consulta

Pergunta em linguagem natural sobre a camada Gold.

A página não escolhe o provedor: ela pergunta ao módulo ai qual modo
está disponível e se adapta. Isso significa que o mesmo código funciona
com Select AI, com Gemini ou sem LLM nenhum — e que trocar de provedor
não exige mexer aqui.

Pelo mesmo motivo ela também não fixa um tipo de gráfico: a forma é
escolhida a partir do formato do resultado, por ui.grafico_automatico.
"""

import pandas as pd
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

competencias = ui.listar_ou_vazio(db.listar_competencias)

with st.sidebar:
    st.markdown('<div class="cs-slicer">Filtros</div>', unsafe_allow_html=True)
    competencia = st.selectbox(
        "Competência de referência", competencias or ["—"],
        index=max(len(competencias) - 1, 0),
        format_func=ui.competencia_legivel,
    )

ui.cabecalho(titulo, subtitulo)

# O aviso de modo é uma linha, não um bloco: o provedor ativo é contexto
# permanente da página, e um alerta de altura cheia empurraria a entrada
# para fora da primeira tela a cada execução.
ICONES = {"select_ai": ":material/database:", "gemini": ":material/smart_toy:",
          "catalogo": ":material/info:"}
if modo == "catalogo":
    mensagem = (f"{mensagem} As consultas abaixo são pré-escritas e "
                "validadas, e não dependem de provedor externo.")
st.caption(f"{ICONES[modo]} {mensagem}")

# ---------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------

pergunta_livre = modo in ("select_ai", "gemini")

esquerda, direita = st.columns([3, 1], gap="small")

with esquerda:
    bloco = ui.painel("Pergunte aos dados", chave="pergunta",
                      altura=ui.ALTURA_CARTAO_BAIXO)
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
                                          width="stretch"):
                    st.session_state["pergunta_escolhida"] = exemplo
                    st.rerun()
        else:
            pergunta = st.selectbox(
                "Escolha uma pergunta",
                list(ai.CATALOGO),
                label_visibility="collapsed",
            )

        enviar = st.button("Gerar análise", type="primary", width="stretch")

with direita:
    bloco = ui.painel("Como funciona", chave="ajuda",
                      altura=ui.ALTURA_CARTAO_BAIXO)
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
# Leitura do resultado
# ---------------------------------------------------------------------


def leitura_resultado(dados: pd.DataFrame) -> list[str]:
    """
    Frases derivadas do próprio resultado devolvido pela consulta.

    São contas sobre as linhas em tela — quem lidera, quanto o topo
    concentra, qual a amplitude. Nada aqui é gerado por modelo: a
    narrativa do provedor já tem espaço próprio na aba de resposta, e
    misturar as duas coisas tiraria do leitor a chance de saber o que é
    dado e o que é redação.
    """
    if dados is None or dados.empty or len(dados) < 2:
        return []

    numericas = [c for c in dados.columns if ui.e_numerica(dados[c])]
    tempo = next((c for c in dados.columns if c.lower() in ui.COLUNAS_TEMPO), None)
    numericas = [c for c in numericas if c != tempo]
    categoricas = [c for c in dados.columns if c not in numericas and c != tempo]
    if not numericas:
        return []

    valor = ui.medida_principal(dados, numericas)
    medida = pd.to_numeric(dados[valor], errors="coerce").dropna()
    if medida.empty:
        return []

    nome = ui.rotulo_medida(valor)
    casas = 0 if float(medida.abs().max()) >= 100 else 2
    notas: list[str] = []

    if categoricas:
        rotulo = dados.loc[medida.idxmax(), categoricas[0]]
        notas.append(
            f"Maior **{nome}**: {rotulo}, com {ui.num(medida.max(), casas)}."
        )

    # Concentração só vale para medida que soma. Para índice, taxa ou
    # média, a leitura equivalente é quantas linhas passam da mediana.
    if ui.e_aditiva(valor):
        total = float(medida.sum())
        if total > 0 and len(medida) >= 4:
            topo = float(medida.nlargest(3).sum())
            notas.append(
                f"As três primeiras linhas concentram "
                f"**{ui.pct(topo / total * 100, 0)}** do total de {nome}."
            )
    elif len(medida) >= 4:
        acima = int((medida > medida.median()).sum())
        notas.append(
            f"**{ui.num(acima)}** das {ui.num(len(medida))} linhas ficam acima "
            f"da mediana de {nome} — medida de índice não se soma, então a "
            "leitura aqui é de dispersão, não de concentração."
        )

    if len(medida) >= 3:
        notas.append(
            f"Amplitude: de {ui.num(medida.min(), casas)} a "
            f"{ui.num(medida.max(), casas)}, mediana {ui.num(medida.median(), casas)}."
        )

    return notas


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
                grafico, legenda = ui.grafico_automatico(resposta.dados)
                if grafico is not None:
                    st.altair_chart(grafico, width="stretch", theme=None)
                    st.caption(legenda)
                else:
                    st.dataframe(resposta.dados.head(15),
                                 width="stretch", hide_index=True)
                    st.caption(legenda)

        with aba_sql:
            st.caption("Somente leitura. Comandos de escrita são bloqueados.")
            st.code(resposta.sql or "—", language="sql")

        with aba_dados:
            if resposta.dados.empty:
                st.info("A consulta não retornou linhas.")
            else:
                st.dataframe(resposta.dados, width="stretch", hide_index=True)
                st.download_button(
                    "Baixar em CSV",
                    resposta.dados.to_csv(index=False).encode("utf-8"),
                    file_name="conecta_saude_consulta.csv",
                    mime="text/csv",
                )

    with coluna_lateral:
        bloco = ui.painel("Sobre esta resposta", chave="sobre")
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

        notas = leitura_resultado(resposta.dados)
        if notas:
            bloco.divider()
            bloco.markdown("**O que o resultado mostra**")
            for nota in notas:
                bloco.markdown(f":material/arrow_right: {nota}")

        seguintes = [p for p in ai.CATALOGO if p != resposta.pergunta][:3]
        if seguintes:
            bloco.divider()
            bloco.markdown("**Continuar por aqui**")
            for indice, proxima in enumerate(seguintes):
                if bloco.button(proxima, key=f"seguinte_{indice}", width="stretch"):
                    st.session_state["pergunta_escolhida"] = proxima
                    st.rerun()

ui.rodape([
    "O **SQL** de cada resposta fica visível na aba correspondente. O "
    "usuário da aplicação tem permissão apenas de leitura, e comandos de "
    "escrita são bloqueados antes de chegar ao banco.",
    "O **gráfico** é escolhido pelo formato do resultado: coluna de tempo "
    "com uma medida vira linha; uma categoria com uma medida vira barra "
    "ordenada; o resto continua tabela.",
    "O painel **O que o resultado mostra** é calculado sobre as linhas "
    "devolvidas, não gerado por modelo. Medidas de índice, taxa ou média "
    "não são somadas: para elas a leitura é de dispersão.",
])
