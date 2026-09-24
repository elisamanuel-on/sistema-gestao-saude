# Sistema de Gestão de Utentes e Cuidados de Saúde

Projeto de portfólio: um dashboard/aplicação web (Dash + Plotly + scikit-learn)
para gestão de utentes num contexto de cuidados continuados/residências sénior
(UCC/ERPI/SAD), com avaliação de risco clínico por machine learning e um
resumo automático em linguagem natural para o profissional de saúde.

**Vitrine pública, sem precisares de instalar nada:** https://sistema-gestao-saude.onrender.com/
(o link abre uma landing page com um botão "Simulação", para entrares direto
num perfil de demonstração).

## Porque é que isto existe

Antes de construir, pesquisei dois produtos reais do mesmo tipo de mercado:
**hitCare** (hitEcosystem, software português para UCC/ERPI/SAD, com mapas de
ocupação/altas e faturação com a Segurança Social) e **LinkHMS** (sistema
hospitalar com ficha clínica por paciente: EMR, exames, consultas). Este
projeto cobre os dois tipos de contexto, cuidados continuados (UCC/ERPI/SAD)
e ambulatório clínico/hospitalar (**Clínica/Hospital**), mas é uma
implementação **original e independente**: nenhum código, design, marca ou
dado de nenhum dos dois produtos foi copiado. É só inspiração na ideia
funcional, combinada e depois redesenhada.

## Módulos

- **Vitrine** (`/vitrine`, e também a raiz `/` para quem chega sem sessão):
  landing page pública, sem login nenhum. Tem duas entradas: **"Ver o
  sistema inteiro"**, que leva ao login real, e **"Simulação"**
  (`/simulacao`), que entra logo num perfil de demonstração à escolha (com
  os mesmos dados reais do resto do sistema) e mostra um aviso persistente
  de "Modo simulação" em todas as páginas, com saída direta de volta para a
  vitrine.
- **Login por perfil** (`/login`): simulação de acesso sem autenticação
  real (sem palavra-passe): **Enfermeiro**, **Médico**, **Receção** ou
  **Admin**. Cada perfil só vê as secções de navegação relevantes ao seu
  papel:
  - **Receção** e **Admin** são os únicos que marcam, cancelam e reagendam
    consultas, e que têm acesso a Faturação; o Médico e o Enfermeiro
    continuam a ver a própria agenda (filtrada à sua identidade), mas só a
    gerem através da Receção, tal como aconteceria com contas reais.
  - **Admin** tem tudo o que a Receção tem, mais a gestão do cadastro de
    profissionais e o relatório de atividade de qualquer profissional (a
    Receção só vê o resumo de uma consulta específica, não a atividade
    agregada de alguém).
  - **Receção** não tem acesso a atos clínicos: avaliação de risco,
    prescrições nem receita.

  O perfil escolhido fica guardado na sessão do browser (`sessionStorage`) e
  há um botão "Sair" para trocar de perfil (volta para `/vitrine` numa
  sessão de simulação, ou para `/login` numa sessão normal).
- **Visão Geral** (`/`): dashboard inicial com KPIs agregados de todos os
  módulos (total de utentes, ocupação, consultas hoje, utentes com risco
  elevado, exames por rever, faturas com erro), um painel de **alertas** com
  ligação direta para o utente/página relevante, e um banner de orientação
  que aparece uma vez por perfil (guardado em `localStorage`) com uma frase
  a explicar o que aquele perfil pode fazer no sistema.
- **Utentes**: registo único, pesquisável/filtrável, para **todos os tipos
  de unidade** (UCC, ERPI, SAD e Clínica/Hospital), com KPIs gerais e uma
  etiqueta de cor por tipo de unidade.
- **Ficha do utente**: resumo, sinais vitais (gráfico ao longo do tempo),
  alergias & diagnósticos, **exames**, prescrições, **plano de cuidados
  multidisciplinar**, visitas, documentos, **histórico/auditoria**, e
  **avaliação de risco** (esta última secção fica escondida para o perfil
  Receção, que não faz atos clínicos), com **exportação da ficha em PDF**
  (reportlab).
  - **Exames**: análises, imagiologia, cardiológico e outros, com estado
    (Normal / Alterado / Pendente) e resumo do resultado.
  - **Plano de cuidados multidisciplinar**: objetivos e intervenções por
    área profissional (Enfermagem, Medicina, Fisioterapia, Nutrição,
    Psicologia, Serviço Social), cada um com profissional responsável,
    datas de início/revisão, estado e barra de progresso.
  - **Histórico**: registo (fictício) de quem alterou o quê e quando, para
    dar uma noção de rastreabilidade, típica de sistemas clínicos reais.
- **Avaliação de risco**: três domínios clínicos, cada um com o seu
  formulário (pré-preenchido com os últimos valores conhecidos do utente):
  - **Risco de diabetes**: modelo de machine learning (random forest)
    treinado no dataset público *Pima Indians Diabetes*.
  - **Risco cardiovascular**: modelo de machine learning treinado no
    dataset público *UCI Heart Disease* (Cleveland).
  - **Risco de queda**: não é machine learning, é a **Morse Fall Scale**,
    uma escala clínica publicada (Morse, 1989) amplamente usada em hospitais
    e unidades de cuidados continuados.
  - **Resumo automático**: depois de calculado pelo menos um dos três
    riscos, um botão gera um parágrafo em português juntando os três
    resultados, destacando o que precisa de revisão prioritária. É um
    **motor de regras local** (template), não uma chamada a uma API de IA
    generativa: corre offline, sem custos e sem depender de uma chave de
    API, e o resultado é sempre determinístico e auditável. A ideia é o
    profissional ler isto em segundos e decidir; nunca é a decisão final.
- **Mapa de Ocupação**: capacidade vs. ocupação atual por tipo de cuidado
  continuado (UCC/ERPI/SAD) e altas registadas por motivo. O tipo
  Clínica/Hospital não usa mapa de camas, é ambulatório, por isso tem o
  módulo Consultas em vez de ocupação.
- **Consultas** (módulo Clínica/Hospital, gestão reservada a Receção/Admin):
  agendamento por especialidade e profissional, com KPIs (consultas hoje,
  agendadas nos próximos 7 dias, taxa de comparência, faltas), gráfico de
  consultas por especialidade, e duas vistas: **lista** filtrável/
  pesquisável por utente, especialidade e estado (Agendada, Realizada,
  Cancelada, Falta), ou **calendário semanal** (com navegação para a semana
  anterior/seguinte). Inclui **CRUD completo de agendamento**: formulário
  "+ Nova Consulta" (utente, especialidade → profissional filtrado
  automaticamente pela especialidade escolhida, data, hora, sala) com
  **validação de conflitos** (não deixa marcar duas consultas para o mesmo
  profissional ou a mesma sala à mesma hora), e um painel "Gerir consulta
  existente" para **cancelar** ou **reagendar** (nova data/hora/sala, com a
  mesma validação de conflitos) qualquer consulta com estado Agendada.
- **Profissionais** (`/profissionais`, acesso reservado ao perfil Admin):
  cadastro da equipa (médicos, com especialidade, para as consultas; e
  equipa de apoio, enfermagem, fisioterapia, nutrição, psicologia, serviço
  social, para o plano de cuidados), com KPIs (total, ativos, inativos) e
  **CRUD completo**: formulário "+ Novo Profissional" (nome, categoria,
  especialidade, só para Médico, contacto, nº de cédula profissional, data
  de admissão), e um painel "Gerir profissional" para editar contacto/
  cédula/especialidade, alternar entre Ativo/Inativo, ou remover. A
  **remoção é bloqueada** sempre que o profissional tenha qualquer
  histórico associado (consultas, plano de cuidados, diagnósticos,
  prescrições, visitas, exames ou histórico), para não partir esses
  registos, sugerindo marcar como **Inativo** em alternativa (soft-delete).
- **Faturação** (acesso reservado a Receção/Admin): valor a pagar pelos
  utentes, comparticipação da Segurança Social, verbas ARS (diárias,
  medicamentos, remuneração adicional), **faturação a seguradoras
  privadas** (cobertura, valor pago pela seguradora, copagamento do
  utente), saldos e sinalização de erros de fatura, com **exportação em
  Excel** (`.xlsx`, formatado: cabeçalho a negrito, valores em formato
  moeda, largura de colunas ajustada, linha de cabeçalho fixa) como formato
  principal, e **CSV** como alternativa secundária (separador `;`, vírgula
  decimal e `utf-8-sig`, para abrir corretamente acentos, colunas e casas
  decimais no Excel em português).
- **Sobre este projeto** (`/sobre`): página dentro da própria aplicação,
  para quem abre o link em produção sem nunca ver o repositório.

## Sobre os dados: nada disto é real

**Nenhuma pessoa real, utente ou paciente está representada em nenhum
ficheiro deste projeto.** Os 45 utentes (`dados/utentes.csv`), os sinais
vitais, diagnósticos, prescrições, visitas, alergias, documentos, exames,
plano de cuidados, consultas, os 14 profissionais (`dados/profissionais.csv`)
e faturação são **todos gerados sinteticamente**
(`scripts/gerar_dados_utentes.py`, com as listas partilhadas em
`constantes.py`), incluindo os nomes (biblioteca `Faker`, nunca uma pessoa
real) e os contactos dos profissionais. As **seguradoras** que aparecem na
faturação (SegurCuidar, ViverSeguro, Confiança Saúde, Proteger+) também têm
nomes inventados, nenhuma é uma marca real. Os valores clínicos usados para
pré-preencher os formulários de risco foram amostrados a partir de dois
datasets públicos e anonimizados amplamente usados em investigação/ensino,
nunca de pacientes reais:

- **Pima Indians Diabetes Database** (National Institute of Diabetes and
  Digestive and Kidney Diseases): 768 registos anonimizados.
- **UCI Heart Disease Dataset** (Cleveland): 303 registos anonimizados.

O ficheiro `dados/registo_bruto.csv` é uma versão *propositadamente
desorganizada* do dataset de diabetes (datas em 3 formatos diferentes,
marcadores de valor em falta inconsistentes, duplicados, valores inválidos),
gerada por `scripts/gerar_dados_brutos.py` só para dar ao módulo de limpeza
(`limpeza.py`) um problema realista de estruturação de dados para resolver,
o mesmo tipo de tarefa pedida em várias vagas de "digitalização/limpeza de
dados" que vimos no Freelancer.com.

## Aviso importante

Esta ferramenta é uma **demonstração técnica de portfólio**, não um sistema
clínico certificado nem um produto pronto para produção. Os modelos de risco
não foram validados clinicamente. O aviso "esta ferramenta é uma demonstração
técnica..." aparece sempre na página de avaliação de risco, nunca escondido
em letra pequena. **Nunca use isto com dados reais de pacientes**, os
datasets públicos usados para treinar os modelos são para fins de
investigação/ensino, não para diagnóstico.

## Qualidade dos modelos

| Modelo | Algoritmo escolhido | AUC-ROC (teste) | Acurácia (teste) |
|---|---|---|---|
| Diabetes | Random Forest | 0.90 | 77% |
| Cardiovascular | Random Forest | 0.91 | 84% |

(Escolhidos por validação cruzada de 5 folds entre regressão logística e
random forest, ver `scripts/treinar_modelo.py` e
`scripts/treinar_modelo_cardio.py`. Métricas completas, incluindo matriz de
confusão, em `modelo/metricas_modelo.json` e `modelo/metricas_modelo_cardio.json`,
e visíveis na própria página da calculadora.)

## Cores e acessibilidade

Tema único, claro. Cor de identidade "teal" (`#0f7a6c`, contraste 5.2:1 sobre
branco) associada a saúde/confiança. Risco usa uma escala de estado fixa e
sempre emparelhada com um rótulo em texto, nunca só cor: verde `#137a4c`
(5.4:1), laranja `#9a5700` (5.6:1) e vermelho `#c22b3f` (5.7:1), todas acima
do mínimo WCAG de 4.5:1 para texto.

Os 4 tipos de unidade têm uma cor categórica própria (nunca reutilizada para
risco, para não confundir "tipo" com "gravidade"), todas também acima de
4.5:1 sobre branco: UCC `#0f7a6c` (5.2:1, a mesma cor de identidade), ERPI
`#4338b0` (8.6:1), SAD `#8f3569` (7.3:1) e Clínica/Hospital `#155696` (7.5:1).

## Como correr localmente

```bash
pip install -r requirements-dev.txt

# (opcional, os dados e modelos já vêm gerados/treinados neste entregável)
# Nota: corre estes scripts como módulo (-m), não como ficheiro direto,
# é o que faz "from limpeza import ..." e "from constantes import ..."
# funcionarem sem teres de mexer em PYTHONPATH.
python -m scripts.gerar_dados_brutos
python -m scripts.treinar_modelo
python -m scripts.treinar_modelo_cardio
python -m scripts.gerar_dados_utentes

python app.py
# abrir http://localhost:8051/vitrine
```

## Deploy no Render

O projeto já vem preparado para o [Render](https://render.com): `gunicorn`
está no `requirements.txt` e `app.py` expõe `server = app.server` (o Flask
por trás do Dash), que é o que o `gunicorn` corre.

**Opção A: Blueprint automático (`render.yaml`):** no dashboard do Render,
"New +" → "Blueprint" → liga o repositório GitHub → o Render lê o
`render.yaml` da raiz do projeto e configura tudo sozinho.

**Opção B: Manual.** "New +" → "Web Service" → liga o repositório → nos
campos:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:server --bind 0.0.0.0:$PORT`
- **Plan**: Free chega perfeitamente para uma demonstração de portfólio.

Nota sobre o plano gratuito: a instância "adormece" ao fim de uns minutos
sem tráfego, e o primeiro pedido a seguir demora ~30-50 segundos a acordar.
Não é um bug, é assim que o plano gratuito funciona. Se fores mostrar isto
a um cliente ao vivo, vale a pena abrir o link uns minutos antes.

## Testes

```bash
pytest -v
ruff check --select=F,E9,B .
```

121 testes cobrem: limpeza/estruturação de dados, a escala de risco de queda
(incluindo as fronteiras exatas entre baixo/moderado/elevado), o resumo
automático, o roteamento e os callbacks principais, a validade das
previsões dos dois modelos de ML, o módulo Clínica/Hospital (coerência
profissional/especialidade nas consultas, coerência profissional/área no
plano de cuidados, exames, e as colunas de seguro na faturação), o acesso
por perfil nos 4 perfis (que secções cada perfil vê, quem gere a agenda de
consultas, quem vê o cadastro de profissionais, quem escolhe livremente o
profissional no relatório de atividade), a vitrine e o modo simulação
(rotas públicas, propagação da flag de simulação, banner persistente, saída
para o sítio certo), o banner de orientação da Visão Geral (aparece uma vez
por perfil, dispensa sem apagar o de outro perfil), a Visão Geral e o
cálculo de utentes com risco elevado, a vista de calendário de consultas, a
exportação em PDF da ficha (valida que o ficheiro gerado é um PDF válido),
a exportação da faturação em CSV (separador `;` e vírgula decimal) e em
Excel (valida que o ficheiro gerado é um `.xlsx` válido), o **CRUD de
agendamento** (criar consulta sem conflito, bloquear conflito de
profissional/sala/hora, exigir todos os campos, cancelar, reagendar), e o
**CRUD de profissionais** (carregamento dos dados, recusar Médico sem
especialidade, recusar nome duplicado, criar e remover sem histórico,
bloquear remoção com histórico, alternar Ativo/Inativo, editar contacto, e
o carregamento da página).

## O que ficaria para uma próxima iteração

Sendo um projeto de portfólio, há decisões de âmbito deliberadas: o login
por perfil (e o modo simulação) é só uma simulação de interface (sem
palavra-passe nem autenticação real, não há verificação de identidade nem
proteção real dos dados por trás), sem conformidade RGPD/RNCCI formal, e a
vista de calendário de consultas é semanal, sem arrastar/largar para
reagendar.

**Persistência**: os dados-base (utentes, sinais vitais, diagnósticos, etc.)
vivem em CSV, carregados uma vez no arranque. As **consultas criadas,
canceladas ou reagendadas**, e os **profissionais criados, editados ou
removidos**, através da aplicação ficam **apenas em memória do processo do
servidor**, não são escritos de volta para o CSV, por isso são perdidos
quando o servidor reinicia, e são partilhados por todas as pessoas a usar a
mesma instância ao mesmo tempo (não há sessão isolada por utilizador). É
uma decisão de âmbito consciente para uma demonstração de portfólio: a
próxima iteração natural seria trocar os CSV por uma base de dados real
(p.ex. PostgreSQL/SQLite) para persistência verdadeira e concorrência
segura entre utilizadores.

**Organização do código**: `app.py` concentra layout, callbacks, lógica de
negócio e geração de PDF/Excel num único ficheiro (~3200 linhas). Funciona
bem para o tamanho atual do projeto, mas separar em módulos (`pages/`,
`callbacks/`, `pdf/`) seria o próximo passo de organização antes de o
projeto crescer mais.

**Integração contínua**: os testes e o `ruff` correm manualmente antes de
cada `git push` (ver secção "Testes" acima), não há ainda um workflow de
CI (GitHub Actions) a correr isto automaticamente a cada commit antes do
deploy no Render. É o próximo passo mais simples para apanhar cedo o tipo
de erro que já aconteceu neste projeto (um ficheiro atualizado localmente
mas esquecido do `git add`, só descoberto quando o deploy falhava).

Tudo isto seria o próximo passo natural para uma versão de produção.
