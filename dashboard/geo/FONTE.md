# Malha territorial

`malha_uf_ibge.json` — contorno das 27 unidades federativas.

- **Origem:** API de malhas territoriais do IBGE, servicodados.ibge.gov.br
  (`/api/v3/malhas/paises/BR`, `intrarregiao=UF`, `qualidade=minima`).
- **Baixado em:** 2026-08-25.
- **Por que versionado:** o mapa da página de visão geral não deve depender
  de rede em tempo de execução. São 98 KB, e a malha só muda quando o IBGE
  redivide o território.
- **Chave de junção:** as feições trazem apenas `properties.codarea`, o
  código numérico da UF. A sigla — que é como a camada Gold identifica a
  UF — é acrescentada no carregamento, por `ui.CODIGO_UF`.
- **Licença:** dado público produzido pelo IBGE, mesma origem dos dados de
  população já usados no projeto.
