# Malha territorial

Dois níveis, porque o mapa da visão geral tem dois: o país por estado e,
quando o filtro escolhe uma UF, o estado por município.

## `malha_uf_ibge.json` — contorno das 27 unidades federativas

- **Origem:** API de malhas territoriais do IBGE, servicodados.ibge.gov.br
  (`/api/v3/malhas/paises/BR`, `intrarregiao=UF`, `qualidade=minima`).
- **Baixado em:** 2026-08-25.
- **Chave de junção:** as feições trazem apenas `properties.codarea`, o
  código numérico da UF. A sigla — que é como a camada Gold identifica a
  UF — é acrescentada no carregamento, por `ui.CODIGO_UF`.

## `municipios/{SIGLA}.json` — contorno dos municípios, um arquivo por UF

- **Origem:** mesma API, `/api/v3/malhas/estados/{código da UF}` com
  `intrarregiao=municipio` e `qualidade=minima`.
- **Baixado em:** 2026-08-27.
- **Total:** 3,1 MB, 5.570 feições. O maior arquivo é MG, com 853
  municípios e 444 KB; o menor é DF, com um.
- **Chave de junção:** `properties.codarea` traz o código do IBGE de sete
  dígitos. A Gold guarda o código do DATASUS, de seis, então a consulta
  `db.pressao_por_municipio` busca o de sete em `silver_municipio`.
- **Por que um arquivo por UF:** a malha municipal do país inteiro seria
  carregada por completo para desenhar um estado só. O painel nunca
  desenha municípios sem uma UF escolhida, então o recorte por arquivo
  acompanha o recorte da tela e o consumo de memória fica limitado ao
  maior estado.

Para rebaixar as duas malhas, trocar a data acima e refazer as chamadas:

```
# UFs
/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&intrarregiao=UF&qualidade=minima

# municípios de uma UF (35 = SP)
/api/v3/malhas/estados/35?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=minima
```

A API responde com `Content-Encoding: gzip`. Nos arquivos versionados
ficam apenas `codarea` e a geometria, em JSON compacto.

## Comum aos dois

- **Por que versionado:** o mapa não deve depender de rede em tempo de
  execução. A malha só muda quando o IBGE redivide o território.
- **Licença:** dado público produzido pelo IBGE, mesma origem dos dados de
  população já usados no projeto.
