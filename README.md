# Sistema de Gestão de Utentes e Cuidados de Saúde

Projeto de portfólio: um dashboard/aplicação web (Dash + Plotly + scikit-learn)
para gestão de utentes num contexto de cuidados continuados/residências sénior
(UCC/ERPI/SAD), com avaliação de risco clínico por machine learning e um
resumo automático em linguagem natural para o profissional de saúde.

## Porque é que isto existe

Antes de construir, pesquisei dois produtos reais do mesmo tipo de mercado:
**hitCare** (hitEcosystem — software português para UCC/ERPI/SAD, com mapas de
ocupação/altas e faturação com a Segurança Social) e **LinkHMS** (sistema
hospitalar com ficha clínica por paciente — EMR). Este projeto cobre o mesmo
tipo de módulos, mas é uma implementação **original e independente** — nenhum
código, design, marca ou dado de nenhum dos dois produtos foi copiado. É só
inspiração na ideia funcional.

## Módulos

- **Utentes** — lista pesquisável/filtrável (nome, tipo de cuidado, estado),
  com KPIs gerais.
- **Ficha do utente** — resumo, sinais vitais (gráfico ao longo do tempo),
  alergias & diagnósticos, prescrições, visitas, documentos, e **avaliação de
  risco**.
- **Avaliação de risco** — três domínios clínicos, cada um com o seu
  formulário (pré-preenchido com os últimos valores conhecidos do utente):
  - **Risco de diabetes** — modelo de machine learning (random forest)
    treinado no dataset público *Pima Indians Diabetes*.
  - **Risco cardiovascular** — modelo de machine learning treinado no
    dataset público *UCI Heart Disease* (Cleveland).
  - **Risco de queda** — não é machine learning, é a **Morse Fall Scale**,
    uma escala clínica publicada (Morse, 1989) amplamente usada em hospitais
    e unidades de cuidados continuados.
  - **Resumo automático** — depois de calculado pelo menos um dos três
    riscos, um botão gera um parágrafo em português juntando os três
    resultados, destacando o que precisa de revisão prioritária. É um
    **motor de regras local** (template), não uma chamada a uma API de IA
    generativa — corre offline, sem custos e sem depender de uma chave de
    API, e o resultado é sempre determinístico e auditável. A ideia é o
    profissional ler isto em segundos e decidir — nunca é a decisão final.
- **Mapa de Ocupação** — capacidade vs. ocupação atual por tipo de cuidado
  (UCC/ERPI/SAD) e altas registadas por motivo.
- **Faturação** — valor a pagar pelos utentes, comparticipação da Segurança
  Social, verbas ARS (diárias, medicamentos, remuneração adicional), saldos
  e sinalização de erros de fatura, com exportação para CSV.

## Sobre os dados — nada disto é real

**Nenhuma pessoa real, utente ou paciente está representada em nenhum
ficheiro deste projeto.** Os 45 utentes (`dados/utentes.csv`), os sinais
vitais, diagnósticos, prescrições, visitas, alergias, documentos e faturação
são **todos gerados sinteticamente** (`scripts/gerar_dados_utentes.py`),
incluindo os nomes (biblioteca `Faker`, nunca uma pessoa real). Os valores
clínicos usados para pré-preencher os formulários de risco foram amostrados a
partir de dois datasets públicos e anonimizados amplamente usados em
investigação/ensino — nunca de pacientes reais:

- **Pima Indians Diabetes Database** (National Institute of Diabetes and
  Digestive and Kidney Diseases) — 768 registos anonimizados.
- **UCI Heart Disease Dataset** (Cleveland) — 303 registos anonimizados.

O ficheiro `dados/registo_bruto.csv` é uma versão *propositadamente
desorganizada* do dataset de diabetes (datas em 3 formatos diferentes,
marcadores de valor em falta inconsistentes, duplicados, valores inválidos),
gerada por `scripts/gerar_dados_brutos.py` só para dar ao módulo de limpeza
(`limpeza.py`) um problema realista de estruturação de dados para resolver —
o mesmo tipo de tarefa pedida em várias vagas de "digitalização/limpeza de
dados" que vimos no Freelancer.com.

## Aviso importante

Esta ferramenta é uma **demonstração técnica de portfólio**, não um sistema
clínico certificado nem um produto pronto para produção. Os modelos de risco
não foram validados clinicamente. O aviso "esta ferramenta é uma demonstração
técnica..." aparece sempre na página de avaliação de risco, nunca escondido
em letra pequena. **Nunca use isto com dados reais de pacientes** — os
datasets públicos usados para treinar os modelos são para fins de
investigação/ensino, não para diagnóstico.

## Qualidade dos modelos

| Modelo | Algoritmo escolhido | AUC-ROC (teste) | Acurácia (teste) |
|---|---|---|---|
| Diabetes | Random Forest | 0.90 | 77% |
| Cardiovascular | Random Forest | 0.91 | 84% |

(Escolhidos por validação cruzada de 5 folds entre regressão logística e
random forest — ver `scripts/treinar_modelo.py` e
`scripts/treinar_modelo_cardio.py`. Métricas completas, incluindo matriz de
confusão, em `modelo/metricas_modelo.json` e `modelo/metricas_modelo_cardio.json`,
e visíveis na própria página da calculadora.)

## Cores e acessibilidade

Tema único, claro. Cor de identidade "teal" (`#0f7a6c`, contraste 5.2:1 sobre
branco) associada a saúde/confiança. Risco usa uma escala de estado fixa e
sempre emparelhada com um rótulo em texto, nunca só cor: verde `#137a4c`
(5.4:1), laranja `#9a5700` (5.6:1) e vermelho `#c22b3f` (5.7:1) — todas acima
do mínimo WCAG de 4.5:1 para texto.

## Como correr localmente

```bash
pip install -r requirements-dev.txt

# (opcional — os dados e modelos já vêm gerados/treinados neste entregável)
python scripts/gerar_dados_brutos.py
python scripts/treinar_modelo.py
python scripts/treinar_modelo_cardio.py
python scripts/gerar_dados_utentes.py

python app.py
# abrir http://localhost:8051/utentes
```

## Testes

```bash
pytest -v
ruff check --select=F,E9,B .
```

26 testes cobrem: limpeza/estruturação de dados, a escala de risco de queda
(incluindo as fronteiras exatas entre baixo/moderado/elevado), o resumo
automático, o roteamento e os callbacks principais, e a validade das
previsões dos dois modelos de ML.

## O que ficaria para uma próxima iteração

Sendo um projeto de portfólio, há decisões de âmbito deliberadas: sem
autenticação/permissões por utilizador, sem persistência em base de dados
(os dados vivem em CSV, carregados uma vez no arranque), sem exportação em
Excel para os utentes (só CSV na faturação), e sem conformidade RGPD/RNCCI
formal — tudo isto seria o próximo passo natural para uma versão de
produção.
