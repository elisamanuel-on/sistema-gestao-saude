"""Sistema de Gestão de Utentes e Cuidados de Saúde — projeto de portfólio.

Inspirado (só na ideia funcional, nunca na marca/design) em dois produtos
reais pesquisados antes de construir isto: hitCare (hitEcosystem), software
português para UCC/ERPI/SAD com mapas de ocupação/altas e faturação com a
Segurança Social, e LinkHMS, um sistema hospitalar com ficha clínica por
paciente (EMR, exames, consultas). Nada aqui reproduz o logótipo, as cores
de marca ou o layout exato de nenhum dos dois — é uma implementação
original, que cobre os dois tipos de contexto: cuidados continuados
(UCC/ERPI/SAD) e ambulatório clínico/hospitalar.

Módulos, navegação lateral agrupada por contexto (visível/oculta consoante
o perfil de acesso escolhido no login — Enfermeiro, Médico ou
Administrativo, uma simulação sem autenticação real):
  /login              — escolha de perfil (mock, sem palavra-passe)
  /                   — Visão Geral: KPIs agregados de todos os módulos e
                         painel de alertas (risco elevado, exames por rever,
                         faturas com erro)
  /utentes            — lista de utentes de todas as unidades (pesquisa/filtro)
  /utentes/<id>       — ficha do utente: resumo, sinais vitais, alergias &
                         diagnósticos, exames, prescrições, plano de cuidados
                         multidisciplinar, visitas, documentos, histórico/
                         auditoria, e avaliação de risco (diabetes +
                         cardiovascular, por machine learning, + risco de
                         queda pela Morse Fall Scale — instrumento clínico
                         publicado), com um resumo automático em linguagem
                         natural (motor de regras local, sem API externa)
                         para o profissional ler em segundos antes de
                         decidir, e exportação da ficha em PDF.
  /ocupacao           — capacidade, ocupação e altas (cuidados continuados)
  /consultas          — agendamento/consultas (módulo Clínica/Hospital),
                         em vista de lista ou de calendário semanal
  /faturacao          — valores a pagar, comparticipação, ARS, seguros, saldos
  /sobre              — sobre este projeto (para quem abre o link direto)

Dados: tudo sintético (ver scripts/gerar_dados_utentes.py e constantes.py).
Os modelos de risco são treinados em datasets públicos e anonimizados (Pima
Diabetes, UCI Heart Disease) — nenhuma pessoa real, utente ou paciente está
representada em nenhum ficheiro deste projeto, e as seguradoras que
aparecem na faturação têm nomes inventados (nenhuma marca real). Esta
ferramenta é uma demonstração técnica de portfólio, não um sistema clínico
certificado.
"""
import datetime
import io
import json
import pathlib
import unicodedata

import dash
import joblib
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dash_table, dcc, html
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from constantes import ESPECIALIDADES, PERFIS_ACESSO, SECCOES_POR_PERFIL, TIPOS_CUIDADO
from limpeza import LIMITES_PLAUSIVEIS
from riscos import (
    OPCOES_APOIO_MARCHA,
    OPCOES_DIAGNOSTICO_SECUNDARIO,
    OPCOES_ESTADO_MENTAL,
    OPCOES_HISTORICO_QUEDAS,
    OPCOES_MARCHA,
    OPCOES_SORO_IV,
    calcular_risco_queda,
    classificar_risco,
    gerar_resumo_ia,
    principais_fatores,
)
from scripts.treinar_modelo_cardio import COLUNAS_CARDIO

PASTA_DADOS = pathlib.Path("dados")
PASTA_MODELO = pathlib.Path("modelo")

ESTADOS_UTENTE = ["Internado", "Em acompanhamento", "Alta", "Em espera"]

TOM_PLANO = {"Em curso": "primaria", "Concluído": "risco_baixo", "Suspenso": "risco_moderado"}


def _slug(texto):
    """Normaliza texto em português para um sufixo de classe CSS seguro
    (sem acentos, sem espaços, sem barras) — ex.: 'Clínica/Hospital' ->
    'clinica-hospital', 'Concluído' -> 'concluido'."""
    sem_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acentos.lower().replace(" ", "-").replace("/", "-")

RES_DIABETES = {
    "gravidezes": "Nº de gravidezes",
    "glicose": "Glicose (mg/dL)",
    "pressao_arterial": "Pressão arterial (mmHg)",
    "espessura_pele": "Espessura da prega cutânea (mm)",
    "insulina": "Insulina (µU/mL)",
    "imc": "IMC (kg/m²)",
    "pedigree_diabetes": "Índice hereditário (pedigree)",
    "idade": "Idade (anos)",
}

OPCOES_SEXO = {"Feminino": 0, "Masculino": 1}
OPCOES_TIPO_DOR_PEITO = {"Angina típica": 0, "Angina atípica": 1, "Dor não anginosa": 2, "Assintomático": 3}
OPCOES_SIM_NAO = {"Não": 0, "Sim": 1}
OPCOES_ECG_REPOUSO = {"Normal": 0, "Anomalia da onda ST-T": 1, "Hipertrofia ventricular esquerda": 2}
OPCOES_INCLINACAO_ST = {"Ascendente": 0, "Plana": 1, "Descendente": 2}
OPCOES_TALASSEMIA = {"Normal": 1, "Defeito fixo": 2, "Defeito reversível": 3}

CORES = {
    "fundo": "#f7f9f8",
    "cartao": "#ffffff",
    "borda": "#dfe6e2",
    "texto": "#1f2a26",
    "texto_suave": "#5c6b65",
    "primaria": "#0f7a6c",
    "primaria_suave": "#e1f3ef",
    "risco_baixo": "#137a4c",
    "risco_baixo_suave": "#e3f5ec",
    "risco_moderado": "#9a5700",
    "risco_moderado_suave": "#fbeedd",
    "risco_elevado": "#c22b3f",
    "risco_elevado_suave": "#fbe4e7",
    # Cores categóricas dos 4 tipos de unidade (nunca usadas para risco —
    # risco usa sempre a escala baixo/moderado/elevado acima). Todas
    # validadas a 4.5:1+ de contraste sobre branco (ver README).
    "tipo_ucc": "#0f7a6c",
    "tipo_erpi": "#4338b0",
    "tipo_sad": "#8f3569",
    "tipo_clinica_hospital": "#155696",
}


# --- Carregamento de dados (uma vez, ficheiros só de leitura) --------------


def _carregar_todos_os_dados():
    dados = {}
    dados["utentes"] = pd.read_csv(PASTA_DADOS / "utentes.csv")
    dados["avaliacao_diabetes"] = pd.read_csv(PASTA_DADOS / "avaliacao_diabetes.csv").set_index("id_utente")
    dados["avaliacao_cardio"] = pd.read_csv(PASTA_DADOS / "avaliacao_cardio.csv").set_index("id_utente")
    dados["avaliacao_queda"] = pd.read_csv(PASTA_DADOS / "avaliacao_queda.csv").set_index("id_utente")
    dados["vitais"] = pd.read_csv(PASTA_DADOS / "vitais.csv", parse_dates=["data_hora"])
    dados["diagnosticos"] = pd.read_csv(PASTA_DADOS / "diagnosticos.csv")
    dados["prescricoes"] = pd.read_csv(PASTA_DADOS / "prescricoes.csv")
    dados["visitas"] = pd.read_csv(PASTA_DADOS / "visitas.csv")
    dados["alergias"] = pd.read_csv(PASTA_DADOS / "alergias.csv")
    dados["documentos"] = pd.read_csv(PASTA_DADOS / "documentos.csv")
    dados["exames"] = pd.read_csv(PASTA_DADOS / "exames.csv")
    dados["plano_cuidados"] = pd.read_csv(PASTA_DADOS / "plano_cuidados.csv")
    dados["consultas"] = pd.read_csv(PASTA_DADOS / "consultas.csv", parse_dates=["data_hora"])
    dados["faturacao"] = pd.read_csv(PASTA_DADOS / "faturacao.csv")
    dados["faturacao"]["seguradora"] = dados["faturacao"]["seguradora"].fillna("—")
    dados["faturacao"]["numero_apolice"] = dados["faturacao"]["numero_apolice"].fillna("—")
    dados["historico"] = pd.read_csv(PASTA_DADOS / "historico.csv", parse_dates=["data_hora"])
    dados["altas"] = pd.read_csv(PASTA_DADOS / "altas.csv")
    return dados


DADOS = _carregar_todos_os_dados()
MODELO_DIABETES = joblib.load(PASTA_MODELO / "modelo_risco.joblib")
MODELO_CARDIO = joblib.load(PASTA_MODELO / "modelo_cardio.joblib")

with open(PASTA_MODELO / "metricas_modelo.json", encoding="utf-8") as f:
    METRICAS_DIABETES = json.load(f)
with open(PASTA_MODELO / "metricas_modelo_cardio.json", encoding="utf-8") as f:
    METRICAS_CARDIO = json.load(f)

RES_CARDIO = {
    "idade": "Idade",
    "sexo": "Sexo",
    "tipo_dor_peito": "Tipo de dor no peito",
    "pressao_repouso": "Pressão arterial em repouso",
    "colesterol": "Colesterol",
    "glicemia_jejum_elevada": "Glicemia em jejum elevada",
    "ecg_repouso": "ECG em repouso",
    "freq_cardiaca_maxima": "Frequência cardíaca máxima",
    "angina_exercicio": "Angina induzida por exercício",
    "depressao_st": "Depressão ST",
    "inclinacao_st": "Inclinação do segmento ST",
    "n_vasos_principais": "Nº de vasos principais",
    "talassemia": "Talassemia",
}


def _nome_utente(id_utente):
    linha = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == id_utente]
    return linha["nome"].iloc[0] if len(linha) else id_utente


def _idade_utente(data_nascimento):
    nascimento = datetime.date.fromisoformat(data_nascimento)
    hoje = datetime.date.today()
    return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))


def _ids_utentes_risco_elevado():
    """IDs de utentes com risco elevado em pelo menos um dos três domínios
    (diabetes, cardiovascular ou queda), usando os modelos já treinados e a
    Morse Fall Scale sobre os dados clínicos guardados — a mesma lógica de
    classificar_risco()/calcular_risco_queda() usada nos formulários,
    aplicada de uma vez a todos os utentes para a Visão Geral."""
    x_diabetes = DADOS["avaliacao_diabetes"][list(RES_DIABETES.keys())]
    prob_diabetes = MODELO_DIABETES.predict_proba(x_diabetes)[:, 1]
    diabetes_elevado = pd.Series(prob_diabetes >= 0.66, index=DADOS["avaliacao_diabetes"].index)

    x_cardio = DADOS["avaliacao_cardio"][COLUNAS_CARDIO]
    prob_cardio = MODELO_CARDIO.predict_proba(x_cardio)[:, 1]
    cardio_elevado = pd.Series(prob_cardio >= 0.66, index=DADOS["avaliacao_cardio"].index)

    queda_elevado = DADOS["avaliacao_queda"]["classificacao"] == "Risco elevado"

    elevado = (
        diabetes_elevado.reindex(queda_elevado.index, fill_value=False)
        | cardio_elevado.reindex(queda_elevado.index, fill_value=False)
        | queda_elevado
    )
    return elevado[elevado].index.tolist()


# --- Componentes reutilizáveis ----------------------------------------------


def _cartao_kpi(titulo, valor, nota="", tom=""):
    classe = "kpi-cartao" + (f" kpi-cartao--{tom}" if tom else "")
    filhos = [html.Div(titulo, className="kpi-titulo"), html.Div(valor, className="kpi-valor")]
    if nota:
        filhos.append(html.Div(nota, className="kpi-nota"))
    return html.Div(filhos, className=classe)


def _aviso_medico():
    return html.Div(
        [
            html.Strong("Aviso: "),
            "esta ferramenta é uma demonstração técnica de portfólio, não um sistema clínico "
            "certificado. Não foi validada clinicamente e não substitui avaliação por um "
            "profissional de saúde.",
        ],
        className="aviso-medico",
    )


SECCOES_NAVEGACAO = [
    ("Início", [("/", "Visão Geral")]),
    ("Geral", [("/utentes", "Utentes")]),
    ("Cuidados continuados", [("/ocupacao", "Mapa de Ocupação")]),
    ("Clínica & Hospital", [("/consultas", "Consultas")]),
    ("Gestão", [("/faturacao", "Faturação")]),
]


def _barra_lateral(caminho_atual, perfil):
    seccoes_visiveis = SECCOES_POR_PERFIL.get(perfil, [titulo for titulo, _itens in SECCOES_NAVEGACAO])
    seccoes = []
    for titulo_seccao, itens in SECCOES_NAVEGACAO:
        if titulo_seccao not in seccoes_visiveis:
            continue
        ligacoes = []
        for destino, rotulo in itens:
            ativa = caminho_atual == destino or (destino == "/utentes" and caminho_atual.startswith("/utentes"))
            classe = "ligacao-lateral" + (" ligacao-lateral--ativa" if ativa else "")
            ligacoes.append(dcc.Link(rotulo, href=destino, className=classe))
        seccoes.append(
            html.Div(
                [html.Div(titulo_seccao, className="legenda-seccao-lateral"), html.Nav(ligacoes, className="nav-lateral")],
                className="seccao-lateral",
            )
        )
    return html.Div(
        [
            html.Div([html.Span("Gestão de Saúde", className="logotipo-lateral-texto")], className="logotipo-lateral"),
            html.Div(seccoes, className="grupo-nav-lateral"),
            html.Div(
                [
                    html.Div(f"Perfil: {perfil}", className="perfil-atual-lateral"),
                    dcc.Link("Sobre este projeto", href="/sobre", className="ligacao-lateral ligacao-lateral--sobre"),
                    html.Button("Sair", id="botao-sair-sessao", className="botao-sair-lateral", n_clicks=0),
                ],
                className="rodape-lateral",
            ),
        ],
        className="barra-lateral",
    )


def _etiqueta_tipo_cuidado(tipo):
    return html.Span(tipo, className=f"etiqueta-tipo etiqueta-tipo--{_slug(tipo)}")


def _etiqueta_tom(texto, tom, sufixo_classe="resultado-inline"):
    return html.Span(texto, className=f"{sufixo_classe} {sufixo_classe}--{tom}")


# --- Página: Login (demonstração, sem autenticação real) --------------------

ICONES_PERFIL = {"Enfermeiro": "🩺", "Médico": "⚕️", "Administrativo": "🗂️"}


def _pagina_login():
    botoes = [
        html.Button(
            [html.Span(ICONES_PERFIL.get(perfil, ""), className="icone-perfil-login"), html.Span(perfil)],
            id={"type": "botao-login-perfil", "perfil": perfil},
            n_clicks=0,
            className="botao-perfil-login",
        )
        for perfil in PERFIS_ACESSO
    ]
    return html.Div(
        html.Div(
            [
                html.Div("✚", className="logotipo-login"),
                html.H1("Gestão de Saúde"),
                html.P(
                    "Escolhe um perfil para entrar. Cada perfil vê um conjunto diferente de módulos, "
                    "tal como aconteceria com contas reais.",
                    className="texto-explicativo",
                ),
                html.Div(botoes, className="grupo-botoes-perfil-login"),
                html.P(
                    "Isto é uma simulação de acesso por perfil para fins de portfólio — não há "
                    "palavra-passe, autenticação real, nem dados sensíveis protegidos.",
                    className="nota-rodape-login",
                ),
            ],
            className="cartao-login",
        ),
        className="ecra-login",
    )


# --- Página: Visão Geral (dashboard inicial) ---------------------------------


def _linha_alerta(tom, texto, href):
    return dcc.Link(
        html.Div([html.Span(className=f"ponto-alerta ponto-alerta--{tom}"), html.Span(texto)], className="linha-alerta"),
        href=href,
        className="ligacao-alerta",
    )


def _pagina_visao_geral():
    utentes = DADOS["utentes"]
    total_utentes = len(utentes)

    with open(PASTA_DADOS / "capacidade.json", encoding="utf-8") as f:
        capacidade = json.load(f)
    internados_por_tipo = utentes[utentes["estado"] == "Internado"].groupby("tipo_cuidado").size()
    ocupados_total = sum(int(internados_por_tipo.get(t, 0)) for t in capacidade)
    capacidade_total = sum(capacidade.values())
    taxa_ocupacao = ocupados_total / capacidade_total * 100 if capacidade_total else 0

    consultas = DADOS["consultas"]
    hoje = pd.Timestamp.now().normalize()
    consultas_hoje = int((consultas["data_hora"].dt.normalize() == hoje).sum())

    exames = DADOS["exames"]
    exames_pendentes = int((exames["estado"] == "Pendente").sum())
    exames_alterados = int((exames["estado"] == "Alterado").sum())

    ids_risco_elevado = _ids_utentes_risco_elevado()
    n_risco_elevado = len(ids_risco_elevado)

    fat = DADOS["faturacao"]
    erros_fatura = int(fat["erro_fatura"].sum())

    kpis = html.Div(
        [
            _cartao_kpi("Total de utentes", total_utentes),
            _cartao_kpi(
                "Ocupação (cuidados continuados)",
                f"{taxa_ocupacao:.0f}%",
                nota=f"{ocupados_total} / {capacidade_total} camas",
                tom="risco_elevado" if taxa_ocupacao >= 90 else ("risco_moderado" if taxa_ocupacao >= 70 else "risco_baixo"),
            ),
            _cartao_kpi("Consultas hoje", consultas_hoje, tom="primaria"),
            _cartao_kpi("Utentes com risco elevado", n_risco_elevado, tom="risco_elevado" if n_risco_elevado else "risco_baixo"),
            _cartao_kpi(
                "Exames por rever",
                exames_pendentes + exames_alterados,
                nota=f"{exames_alterados} alterados · {exames_pendentes} pendentes",
                tom="risco_moderado" if (exames_pendentes + exames_alterados) else "risco_baixo",
            ),
            _cartao_kpi("Faturas com erro", erros_fatura, tom="risco_elevado" if erros_fatura else "risco_baixo"),
        ],
        className="kpis-linha",
    )

    alertas = []
    for id_utente in ids_risco_elevado[:5]:
        alertas.append(_linha_alerta("risco_elevado", f"{_nome_utente(id_utente)} — risco clínico elevado por rever", f"/utentes/{id_utente}"))
    alterados = (
        exames[exames["estado"] == "Alterado"]
        .merge(utentes[["id_utente", "nome"]], on="id_utente")
        .sort_values("data", ascending=False)
        .head(5)
    )
    for _idx, ex in alterados.iterrows():
        alertas.append(_linha_alerta("risco_moderado", f"{ex['nome']} — exame \"{ex['tipo_exame']}\" alterado, por rever", f"/utentes/{ex['id_utente']}"))
    if erros_fatura:
        faturas_erro = fat[fat["erro_fatura"]].merge(utentes[["id_utente", "nome"]], on="id_utente").head(5)
        for _idx, fx in faturas_erro.iterrows():
            alertas.append(_linha_alerta("risco_moderado", f"{fx['nome']} — fatura com erro por corrigir", "/faturacao"))

    painel_alertas = html.Div(
        [
            html.H3("Alertas"),
            html.Div(alertas, className="lista-alertas") if alertas else html.P("Sem alertas de momento.", className="texto-explicativo"),
        ],
        className="cartao-secao",
    )

    contagem_tipo = utentes["tipo_cuidado"].value_counts()
    cores_tipo = [CORES[f"tipo_{_slug(t).replace('-', '_')}"] for t in contagem_tipo.index]
    fig_tipo = go.Figure(go.Bar(x=contagem_tipo.index, y=contagem_tipo.values, marker_color=cores_tipo))
    fig_tipo.update_layout(
        template="plotly_white", height=280, margin=dict(t=20, l=40, r=20, b=40),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
    )

    return html.Div(
        [
            html.H1("Visão Geral"),
            html.P(
                "Ponto de partida com os indicadores mais importantes de todos os módulos — cuidados "
                "continuados e ambulatório clínico/hospitalar.",
                className="texto-explicativo",
            ),
            kpis,
            painel_alertas,
            html.Div(
                [html.H3("Utentes por tipo de unidade"), dcc.Graph(figure=fig_tipo, config={"displayModeBar": False})],
                className="cartao-secao",
            ),
        ]
    )


# --- Página: Sobre este projeto ----------------------------------------------


def _pagina_sobre():
    return html.Div(
        [
            html.H1("Sobre este projeto"),
            html.P(
                "Projeto de portfólio: um sistema de gestão de utentes e cuidados de saúde que combina dois "
                "contextos — cuidados continuados/residências sénior (UCC/ERPI/SAD) e ambulatório clínico/"
                "hospitalar (Clínica/Hospital) — com avaliação de risco clínico por machine learning.",
                className="texto-explicativo",
            ),
            html.H3("O que inclui", className="titulo-secao-espacado"),
            html.Ul(
                [
                    html.Li("Registo de utentes para os 4 tipos de unidade, com pesquisa e filtros."),
                    html.Li(
                        "Ficha clínica: sinais vitais, alergias/diagnósticos, exames, prescrições, plano de "
                        "cuidados multidisciplinar, visitas, documentos e histórico/auditoria — com "
                        "exportação em PDF."
                    ),
                    html.Li(
                        "Avaliação de risco: diabetes e risco cardiovascular por machine learning (random "
                        "forest), risco de queda pela Morse Fall Scale, e resumo automático em português."
                    ),
                    html.Li("Mapa de ocupação (cuidados continuados) e agendamento de consultas com vista de lista e de calendário (Clínica/Hospital)."),
                    html.Li("Faturação com comparticipação da Segurança Social e seguradoras privadas."),
                    html.Li("Visão Geral com KPIs agregados e alertas, e acesso por perfil (Enfermeiro/Médico/Administrativo)."),
                ]
            ),
            html.H3("Sobre os dados", className="titulo-secao-espacado"),
            html.P(
                "Nenhuma pessoa real está representada: todos os utentes, profissionais e dados clínicos são "
                "gerados sinteticamente. Os valores usados para pré-preencher a avaliação de risco vêm de dois "
                "datasets públicos e anonimizados (Pima Indians Diabetes, UCI Heart Disease), usados só para "
                "manter distribuições realistas — nunca de pacientes reais.",
                className="texto-explicativo",
            ),
            _aviso_medico(),
            html.H3("Stack técnica", className="titulo-secao-espacado"),
            html.P(
                "Python, Dash + Plotly (interface e gráficos), scikit-learn (modelos de risco), pandas "
                "(dados), reportlab (exportação em PDF), pytest (testes automatizados) e deploy no Render.",
                className="texto-explicativo",
            ),
        ]
    )


# --- Página: Lista de utentes -----------------------------------------------


def _tabela_utentes(df):
    if df.empty:
        return html.P("Nenhum utente encontrado com estes filtros.", className="texto-explicativo")
    linhas = []
    for _idx, u in df.iterrows():
        linhas.append(
            html.Tr(
                [
                    html.Td(dcc.Link(u["nome"], href=f"/utentes/{u['id_utente']}", className="ligacao-tabela")),
                    html.Td(u["genero"]),
                    html.Td(str(_idade_utente(u["data_nascimento"]))),
                    html.Td(_etiqueta_tipo_cuidado(u["tipo_cuidado"])),
                    html.Td(u["quarto"]),
                    html.Td(html.Span(u["estado"], className=f"etiqueta-estado etiqueta-estado--{u['estado'].lower().replace(' ', '-')}")),
                ]
            )
        )
    return html.Table(
        [
            html.Thead(html.Tr([html.Th(c) for c in ["Nome", "Género", "Idade", "Tipo de cuidado", "Quarto", "Estado"]])),
            html.Tbody(linhas),
        ],
        className="tabela-utentes",
    )


def _pagina_utentes():
    df = DADOS["utentes"]
    total = len(df)
    ativos = int(df["estado"].isin(["Internado", "Em acompanhamento"]).sum())
    em_espera = int((df["estado"] == "Em espera").sum())
    altas_mes = len(DADOS["altas"])

    return html.Div(
        [
            html.H1("Utentes"),
            html.P(
                "Registo único para todos os tipos de unidade — cuidados continuados (UCC/ERPI/SAD) e "
                "ambulatório clínico/hospitalar.",
                className="texto-explicativo",
            ),
            html.Div(
                [
                    _cartao_kpi("Total de utentes", total),
                    _cartao_kpi("Internados / em acompanhamento", ativos, tom="primaria"),
                    _cartao_kpi("Em espera", em_espera, tom="risco_moderado" if em_espera else ""),
                    _cartao_kpi("Altas registadas", altas_mes),
                ],
                className="kpis-linha",
            ),
            html.Div(
                [
                    dcc.Input(id="pesquisa-utente", type="text", placeholder="Pesquisar por nome...", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="filtro-tipo-cuidado",
                        options=[{"label": t, "value": t} for t in TIPOS_CUIDADO],
                        placeholder="Tipo de cuidado",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(
                        id="filtro-estado",
                        options=[{"label": e, "value": e} for e in ESTADOS_UTENTE],
                        placeholder="Estado",
                        className="filtro-dropdown",
                    ),
                ],
                className="filtros-utentes",
            ),
            html.Div(id="corpo-tabela-utentes"),
        ]
    )


# --- Página: Ficha do utente -------------------------------------------------


def _aba_resumo(id_utente, utente):
    idade = _idade_utente(utente["data_nascimento"])
    ultimos_vitais = DADOS["vitais"][DADOS["vitais"]["id_utente"] == id_utente].sort_values("data_hora").tail(1)
    ultima_glicemia = f"{int(ultimos_vitais['glicemia'].iloc[0])} mg/dL" if len(ultimos_vitais) else "—"
    ultimo_peso = f"{ultimos_vitais['peso_kg'].iloc[0]:.1f} kg" if len(ultimos_vitais) else "—"
    return html.Div(
        [
            html.Div(
                [
                    _cartao_kpi("Idade", f"{idade} anos"),
                    _cartao_kpi("Processo", utente["processo"]),
                    _cartao_kpi("Admissão", utente["data_admissao"]),
                    _cartao_kpi("Última glicemia registada", ultima_glicemia),
                    _cartao_kpi("Último peso registado", ultimo_peso),
                ],
                className="kpis-linha",
            ),
        ]
    )


def _aba_vitais(id_utente):
    return html.Div(
        [
            dcc.Dropdown(
                id="seletor-sinal-vital",
                options=[
                    {"label": "Glicemia (mg/dL)", "value": "glicemia"},
                    {"label": "Peso (kg)", "value": "peso_kg"},
                    {"label": "Tensão sistólica (mmHg)", "value": "tensao_sistolica"},
                    {"label": "Temperatura (°C)", "value": "temperatura"},
                    {"label": "Dor (0-10)", "value": "dor"},
                ],
                value="glicemia",
                clearable=False,
                className="filtro-dropdown",
            ),
            dcc.Graph(id="grafico-sinais-vitais", config={"displayModeBar": False}),
        ]
    )


def _aba_alergias_diagnosticos(id_utente):
    alergias = DADOS["alergias"][DADOS["alergias"]["id_utente"] == id_utente]["alergia"].tolist()
    diagnosticos = DADOS["diagnosticos"][DADOS["diagnosticos"]["id_utente"] == id_utente].sort_values("data", ascending=False)
    return html.Div(
        [
            html.H3("Alergias"),
            html.Div([html.Span(a, className="etiqueta-alergia") for a in alergias]) if alergias else html.P("Sem alergias registadas."),
            html.H3("Diagnósticos", className="titulo-secao-espacado"),
            dash_table.DataTable(
                columns=[{"name": "Data", "id": "data"}, {"name": "Profissional", "id": "profissional"}, {"name": "Diagnóstico", "id": "diagnostico"}],
                data=diagnosticos.to_dict("records"),
                style_table={"overflowX": "auto"},
                style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
                style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
                page_size=8,
            ),
        ]
    )


def _aba_prescricoes(id_utente):
    prescricoes = DADOS["prescricoes"][DADOS["prescricoes"]["id_utente"] == id_utente].sort_values("data", ascending=False)
    return dash_table.DataTable(
        columns=[
            {"name": "Data", "id": "data"},
            {"name": "Profissional", "id": "profissional"},
            {"name": "Medicamento", "id": "medicamento"},
            {"name": "Posologia", "id": "posologia"},
        ],
        data=prescricoes.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        page_size=10,
    )


def _aba_visitas(id_utente):
    visitas = DADOS["visitas"][DADOS["visitas"]["id_utente"] == id_utente]
    return dash_table.DataTable(
        columns=[{"name": "Data/Hora", "id": "data_hora"}, {"name": "Tipo", "id": "tipo"}, {"name": "Registado por", "id": "registado_por"}],
        data=visitas.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        page_size=10,
    )


def _aba_documentos(id_utente):
    documentos = DADOS["documentos"][DADOS["documentos"]["id_utente"] == id_utente]
    return html.Div(
        [
            html.Div([html.Span("📄", className="icone-documento"), html.Span(d["nome_documento"]), html.Span(d["data_upload"], className="data-documento")], className="linha-documento")
            for _idx, d in documentos.iterrows()
        ]
    )


def _aba_exames(id_utente):
    exames = DADOS["exames"][DADOS["exames"]["id_utente"] == id_utente].sort_values("data", ascending=False)
    if exames.empty:
        return html.P("Sem exames registados.", className="texto-explicativo")
    return dash_table.DataTable(
        columns=[
            {"name": "Data", "id": "data"},
            {"name": "Categoria", "id": "categoria"},
            {"name": "Exame", "id": "tipo_exame"},
            {"name": "Estado", "id": "estado"},
            {"name": "Resumo", "id": "resumo_resultado"},
            {"name": "Pedido por", "id": "profissional_pedido"},
        ],
        data=exames.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        style_data_conditional=[
            {"if": {"filter_query": '{estado} = "Alterado"'}, "backgroundColor": CORES["risco_elevado_suave"]},
            {"if": {"filter_query": '{estado} = "Pendente"'}, "backgroundColor": CORES["risco_moderado_suave"]},
        ],
        page_size=10,
    )


def _aba_plano_cuidados(id_utente):
    plano = DADOS["plano_cuidados"][DADOS["plano_cuidados"]["id_utente"] == id_utente].sort_values("area_profissional")
    if plano.empty:
        return html.P("Sem plano de cuidados registado.", className="texto-explicativo")
    itens = []
    for _idx, item in plano.iterrows():
        tom = TOM_PLANO.get(item["estado"], "primaria")
        itens.append(
            html.Div(
                [
                    html.Div(
                        [html.Span(item["area_profissional"], className="etiqueta-area-plano"), html.Strong(item["objetivo"])],
                        className="cabecalho-item-plano",
                    ),
                    html.P(
                        f"Responsável: {item['profissional_responsavel']} · Início: {item['data_inicio']} · "
                        f"Próxima revisão: {item['data_revisao']}",
                        className="texto-explicativo",
                    ),
                    html.Div(html.Div(className="barra-progresso-preenchida", style={"width": f"{item['progresso_percent']}%"}), className="barra-progresso"),
                    _etiqueta_tom(f"{item['estado']} — {item['progresso_percent']}%", tom),
                ],
                className="item-plano-cuidados",
            )
        )
    return html.Div(itens, className="lista-plano-cuidados")


def _aba_historico(id_utente):
    historico = DADOS["historico"][DADOS["historico"]["id_utente"] == id_utente].sort_values("data_hora", ascending=False)
    if historico.empty:
        return html.P("Sem histórico registado.", className="texto-explicativo")
    tabela = historico.copy()
    tabela["data_hora"] = tabela["data_hora"].dt.strftime("%Y-%m-%d %H:%M")
    return dash_table.DataTable(
        columns=[
            {"name": "Data/Hora", "id": "data_hora"},
            {"name": "Profissional", "id": "profissional"},
            {"name": "Ação", "id": "acao"},
        ],
        data=tabela.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        sort_action="native",
        page_size=12,
    )


def _campo_numerico(id_campo, rotulo, minimo, maximo, valor, passo=1):
    return html.Div(
        [html.Label(rotulo), dcc.Input(id=id_campo, type="number", min=minimo, max=maximo, step=passo, value=valor)],
        className="campo-formulario",
    )


def _campo_dropdown(id_campo, rotulo, opcoes, valor):
    return html.Div(
        [html.Label(rotulo), dcc.Dropdown(id=id_campo, options=[{"label": k, "value": k} for k in opcoes], value=valor, clearable=False)],
        className="campo-formulario",
    )


def _sub_cartao_diabetes(id_utente):
    valores = DADOS["avaliacao_diabetes"].loc[id_utente]
    campos = [
        _campo_numerico(f"input-fx-diabetes-{c}", r, *LIMITES_PLAUSIVEIS[c], valor=float(valores[c]), passo=0.1 if c in ("imc", "pedigree_diabetes") else 1)
        for c, r in RES_DIABETES.items()
    ]
    return html.Div(
        [
            html.H4("Risco de diabetes"),
            html.Div(campos, className="grelha-formulario"),
            html.Button("Calcular", id="botao-calcular-diabetes", className="botao-secundario"),
            html.Div(id="resultado-diabetes-tab", className="resultado-mini"),
        ],
        className="sub-cartao-risco",
    )


def _sub_cartao_cardio(id_utente):
    valores = DADOS["avaliacao_cardio"].loc[id_utente]
    inverso_sexo = {v: k for k, v in OPCOES_SEXO.items()}
    inverso_dor = {v: k for k, v in OPCOES_TIPO_DOR_PEITO.items()}
    inverso_simnao = {v: k for k, v in OPCOES_SIM_NAO.items()}
    inverso_ecg = {v: k for k, v in OPCOES_ECG_REPOUSO.items()}
    inverso_slope = {v: k for k, v in OPCOES_INCLINACAO_ST.items()}
    inverso_thal = {v: k for k, v in OPCOES_TALASSEMIA.items()}
    campos = [
        _campo_numerico("input-fx-cardio-idade", "Idade (anos)", 18, 110, float(valores["idade"])),
        _campo_dropdown("input-fx-cardio-sexo", "Sexo", OPCOES_SEXO, inverso_sexo[int(valores["sexo"])]),
        _campo_dropdown("input-fx-cardio-tipo_dor_peito", "Tipo de dor no peito", OPCOES_TIPO_DOR_PEITO, inverso_dor[int(valores["tipo_dor_peito"])]),
        _campo_numerico("input-fx-cardio-pressao_repouso", "Pressão arterial em repouso (mmHg)", 60, 250, float(valores["pressao_repouso"])),
        _campo_numerico("input-fx-cardio-colesterol", "Colesterol (mg/dL)", 100, 600, float(valores["colesterol"])),
        _campo_dropdown("input-fx-cardio-glicemia_jejum_elevada", "Glicemia em jejum > 120mg/dL", OPCOES_SIM_NAO, inverso_simnao[int(valores["glicemia_jejum_elevada"])]),
        _campo_dropdown("input-fx-cardio-ecg_repouso", "ECG em repouso", OPCOES_ECG_REPOUSO, inverso_ecg[int(valores["ecg_repouso"])]),
        _campo_numerico("input-fx-cardio-freq_cardiaca_maxima", "Frequência cardíaca máxima", 60, 220, float(valores["freq_cardiaca_maxima"])),
        _campo_dropdown("input-fx-cardio-angina_exercicio", "Angina induzida por exercício", OPCOES_SIM_NAO, inverso_simnao[int(valores["angina_exercicio"])]),
        _campo_numerico("input-fx-cardio-depressao_st", "Depressão ST induzida por exercício", 0, 7, float(valores["depressao_st"]), passo=0.1),
        _campo_dropdown("input-fx-cardio-inclinacao_st", "Inclinação do segmento ST", OPCOES_INCLINACAO_ST, inverso_slope[int(valores["inclinacao_st"])]),
        _campo_numerico("input-fx-cardio-n_vasos_principais", "Nº de vasos principais (fluoroscopia)", 0, 4, float(valores["n_vasos_principais"])),
        _campo_dropdown("input-fx-cardio-talassemia", "Talassemia", OPCOES_TALASSEMIA, inverso_thal[int(valores["talassemia"])]),
    ]
    return html.Div(
        [
            html.H4("Risco cardiovascular"),
            html.Div(campos, className="grelha-formulario"),
            html.Button("Calcular", id="botao-calcular-cardio", className="botao-secundario"),
            html.Div(id="resultado-cardio-tab", className="resultado-mini"),
        ],
        className="sub-cartao-risco",
    )


def _sub_cartao_queda(id_utente):
    valores = DADOS["avaliacao_queda"].loc[id_utente]
    campos = [
        _campo_dropdown("input-fx-queda-historico", "Histórico de quedas", OPCOES_HISTORICO_QUEDAS, valores["historico_quedas"]),
        _campo_dropdown("input-fx-queda-secundario", "Diagnóstico secundário", OPCOES_DIAGNOSTICO_SECUNDARIO, valores["diagnostico_secundario"]),
        _campo_dropdown("input-fx-queda-apoio", "Apoio para caminhar", OPCOES_APOIO_MARCHA, valores["apoio_marcha"]),
        _campo_dropdown("input-fx-queda-soro", "Soro/Heparin lock IV", OPCOES_SORO_IV, valores["soro_iv"]),
        _campo_dropdown("input-fx-queda-marcha", "Marcha", OPCOES_MARCHA, valores["marcha"]),
        _campo_dropdown("input-fx-queda-mental", "Estado mental", OPCOES_ESTADO_MENTAL, valores["estado_mental"]),
    ]
    return html.Div(
        [
            html.H4("Risco de queda (Morse Fall Scale)"),
            html.Div(campos, className="grelha-formulario"),
            html.Button("Calcular", id="botao-calcular-queda", className="botao-secundario"),
            html.Div(id="resultado-queda-tab", className="resultado-mini"),
        ],
        className="sub-cartao-risco",
    )


def _aba_avaliacao_risco(id_utente):
    return html.Div(
        [
            _aviso_medico(),
            _sub_cartao_diabetes(id_utente),
            _sub_cartao_cardio(id_utente),
            _sub_cartao_queda(id_utente),
            html.Div(
                [
                    html.H4("Resumo automático"),
                    html.P(
                        "Calcula pelo menos um dos riscos acima e depois gera o resumo — motor de "
                        "regras local, sem chamadas a APIs externas de IA generativa.",
                        className="texto-explicativo",
                    ),
                    html.Button("Gerar resumo automático", id="botao-gerar-resumo", className="botao-primario"),
                    html.Div(id="resultado-resumo-ia", className="cartao-resumo-ia"),
                ],
                className="sub-cartao-risco",
            ),
            dcc.Store(id="resultado-diabetes-armazenado"),
            dcc.Store(id="resultado-cardio-armazenado"),
            dcc.Store(id="resultado-queda-armazenado"),
        ]
    )


def _pagina_ficha_utente(id_utente):
    linha = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == id_utente]
    if linha.empty:
        return html.Div([html.H2("Utente não encontrado"), dcc.Link("Voltar à lista", href="/utentes")])
    utente = linha.iloc[0]

    return html.Div(
        [
            html.Div(
                [
                    dcc.Link("← Voltar à lista de utentes", href="/utentes", className="ligacao-voltar"),
                    html.Button("Descarregar PDF", id="botao-pdf-ficha", className="botao-secundario"),
                    dcc.Download(id="descarregar-pdf-ficha"),
                ],
                className="cabecalho-ficha-utente",
            ),
            html.Div(
                [
                    html.H1(utente["nome"]),
                    html.P(
                        f"{utente['genero']} · {_idade_utente(utente['data_nascimento'])} anos · "
                        f"{utente['tipo_cuidado']} · Processo {utente['processo']} · Estado: {utente['estado']}",
                        className="subtitulo-ficha",
                    ),
                ]
            ),
            dcc.Tabs(
                id="abas-ficha-utente",
                value="resumo",
                children=[
                    dcc.Tab(label="Resumo", value="resumo", children=[_aba_resumo(id_utente, utente)]),
                    dcc.Tab(label="Sinais vitais", value="vitais", children=[_aba_vitais(id_utente)]),
                    dcc.Tab(label="Alergias & Diagnósticos", value="alergias", children=[_aba_alergias_diagnosticos(id_utente)]),
                    dcc.Tab(label="Exames", value="exames", children=[_aba_exames(id_utente)]),
                    dcc.Tab(label="Prescrições", value="prescricoes", children=[_aba_prescricoes(id_utente)]),
                    dcc.Tab(label="Plano de Cuidados", value="plano_cuidados", children=[_aba_plano_cuidados(id_utente)]),
                    dcc.Tab(label="Visitas", value="visitas", children=[_aba_visitas(id_utente)]),
                    dcc.Tab(label="Documentos", value="documentos", children=[_aba_documentos(id_utente)]),
                    dcc.Tab(label="Histórico", value="historico", children=[_aba_historico(id_utente)]),
                    dcc.Tab(label="Avaliação de risco", value="risco", children=[_aba_avaliacao_risco(id_utente)]),
                ],
            ),
            dcc.Store(id="utente-atual-id", data=id_utente),
            dcc.Store(id="utente-atual-nome", data=utente["nome"]),
        ]
    )


# --- Página: Mapa de ocupação ------------------------------------------------


def _pagina_ocupacao():
    with open(PASTA_DADOS / "capacidade.json", encoding="utf-8") as f:
        capacidade = json.load(f)

    utentes = DADOS["utentes"]
    internados_por_tipo = utentes[utentes["estado"] == "Internado"].groupby("tipo_cuidado").size()

    kpis = []
    for tipo, cap in capacidade.items():
        ocupados = int(internados_por_tipo.get(tipo, 0))
        taxa = ocupados / cap * 100 if cap else 0
        tom = "risco_elevado" if taxa >= 90 else ("risco_moderado" if taxa >= 70 else "risco_baixo")
        kpis.append(_cartao_kpi(f"Ocupação {tipo}", f"{ocupados} / {cap}", nota=f"{taxa:.0f}% ocupado", tom=tom))

    fig_ocupacao = go.Figure()
    tipos = list(capacidade.keys())
    fig_ocupacao.add_trace(go.Bar(x=tipos, y=[capacidade[t] for t in tipos], name="Capacidade total", marker_color=CORES["borda"]))
    fig_ocupacao.add_trace(
        go.Bar(x=tipos, y=[int(internados_por_tipo.get(t, 0)) for t in tipos], name="Ocupados", marker_color=CORES["primaria"])
    )
    fig_ocupacao.update_layout(
        barmode="overlay", template="plotly_white", height=340, margin=dict(t=30, l=40, r=20, b=40),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
    )

    altas = DADOS["altas"]
    contagem_motivos = altas["motivo"].value_counts()
    fig_altas = go.Figure(
        go.Bar(
            x=contagem_motivos.values, y=contagem_motivos.index, orientation="h",
            marker_color=CORES["primaria"],
        )
    )
    fig_altas.update_layout(
        title="Altas por motivo", template="plotly_white", height=280, margin=dict(t=40, l=180, r=20, b=30),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
    )

    return html.Div(
        [
            html.H1("Mapa de Ocupação"),
            html.Div(kpis, className="kpis-linha"),
            html.Div(
                [html.H3("Capacidade vs. ocupação atual"), dcc.Graph(figure=fig_ocupacao, config={"displayModeBar": False})],
                className="cartao-secao",
            ),
            html.Div(
                [html.H3("Altas registadas"), dcc.Graph(figure=fig_altas, config={"displayModeBar": False})],
                className="cartao-secao",
            ),
            html.Div(
                [
                    "O módulo ",
                    html.Strong("Clínica/Hospital"),
                    " não usa mapa de camas — é ambulatório, organizado por marcação. Ver ",
                    dcc.Link("Consultas", href="/consultas"),
                    ".",
                ],
                className="texto-explicativo nota-modulo-cruzado",
            ),
        ]
    )


# --- Página: Consultas (módulo Clínica/Hospital) ------------------------------


def _tabela_consultas(df):
    if df.empty:
        return html.P("Nenhuma consulta encontrada com estes filtros.", className="texto-explicativo")
    tabela = df.merge(DADOS["utentes"][["id_utente", "nome"]], on="id_utente").sort_values("data_hora")
    tabela["data_hora"] = tabela["data_hora"].dt.strftime("%Y-%m-%d %H:%M")
    return dash_table.DataTable(
        columns=[
            {"name": "Data/Hora", "id": "data_hora"},
            {"name": "Utente", "id": "nome"},
            {"name": "Especialidade", "id": "especialidade"},
            {"name": "Profissional", "id": "profissional"},
            {"name": "Sala", "id": "sala"},
            {"name": "Estado", "id": "estado"},
        ],
        data=tabela.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.85rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        style_data_conditional=[
            {"if": {"filter_query": '{estado} = "Agendada"'}, "backgroundColor": CORES["primaria_suave"]},
            {"if": {"filter_query": '{estado} = "Falta"'}, "backgroundColor": CORES["risco_elevado_suave"]},
            {"if": {"filter_query": '{estado} = "Cancelada"'}, "backgroundColor": CORES["borda"]},
        ],
        sort_action="native",
        page_size=14,
    )


def _inicio_semana_atual():
    hoje = pd.Timestamp.now().normalize()
    return hoje - pd.Timedelta(days=hoje.dayofweek)


def _vista_calendario_consultas(df, inicio):
    fim = inicio + pd.Timedelta(days=7)
    semana = df[(df["data_hora"] >= inicio) & (df["data_hora"] < fim)].merge(DADOS["utentes"][["id_utente", "nome"]], on="id_utente")
    dias_rotulos = [(inicio + pd.Timedelta(days=i)).strftime("%a %d/%m") for i in range(7)]

    cores_estado = {
        "Agendada": CORES["primaria"],
        "Realizada": CORES["risco_baixo"],
        "Cancelada": CORES["texto_suave"],
        "Falta": CORES["risco_elevado"],
    }
    fig = go.Figure()
    for estado_c, cor in cores_estado.items():
        subset = semana[semana["estado"] == estado_c]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["data_hora"].dt.strftime("%a %d/%m"),
                y=subset["data_hora"].dt.hour + subset["data_hora"].dt.minute / 60,
                mode="markers",
                marker=dict(size=14, color=cor, symbol="square"),
                name=estado_c,
                text=[
                    f"{n} · {e} · {h}"
                    for n, e, h in zip(subset["nome"], subset["especialidade"], subset["data_hora"].dt.strftime("%H:%M"), strict=True)
                ],
                hovertemplate="%{text}<extra></extra>",
            )
        )
    fig.update_xaxes(categoryorder="array", categoryarray=dias_rotulos, title="")
    fig.update_yaxes(title="Hora", dtick=1, range=[19, 7])
    fig.update_layout(
        template="plotly_white", height=460, margin=dict(t=20, l=50, r=20, b=40),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
        legend=dict(orientation="h", y=-0.15),
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Button("‹ Semana anterior", id="botao-semana-anterior", className="botao-secundario", n_clicks=0),
                    html.Span(
                        f"{inicio.strftime('%d/%m/%Y')} – {(fim - pd.Timedelta(days=1)).strftime('%d/%m/%Y')}",
                        className="rotulo-semana",
                    ),
                    html.Button("Semana seguinte ›", id="botao-semana-seguinte", className="botao-secundario", n_clicks=0),
                ],
                className="navegacao-semana",
            ),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]
    )


def _pagina_consultas():
    consultas = DADOS["consultas"]
    hoje = pd.Timestamp.now().normalize()
    daqui_7_dias = hoje + pd.Timedelta(days=7)

    consultas_hoje = int((consultas["data_hora"].dt.normalize() == hoje).sum())
    agendadas_semana = int(
        ((consultas["estado"] == "Agendada") & (consultas["data_hora"] >= hoje) & (consultas["data_hora"] < daqui_7_dias)).sum()
    )
    passadas = consultas[consultas["estado"].isin(["Realizada", "Falta"])]
    taxa_comparencia = (passadas["estado"] == "Realizada").mean() * 100 if len(passadas) else 100.0
    faltas = int((consultas["estado"] == "Falta").sum())

    kpis = html.Div(
        [
            _cartao_kpi("Consultas hoje", consultas_hoje, tom="primaria"),
            _cartao_kpi("Agendadas (próximos 7 dias)", agendadas_semana),
            _cartao_kpi("Taxa de comparência", f"{taxa_comparencia:.0f}%", tom="risco_baixo" if taxa_comparencia >= 85 else "risco_moderado"),
            _cartao_kpi("Faltas registadas", faltas, tom="risco_elevado" if faltas else "risco_baixo"),
        ],
        className="kpis-linha",
    )

    contagem_especialidade = consultas["especialidade"].value_counts()
    fig_especialidade = go.Figure(
        go.Bar(x=contagem_especialidade.values, y=contagem_especialidade.index, orientation="h", marker_color=CORES["primaria"])
    )
    fig_especialidade.update_layout(
        title="Consultas por especialidade", template="plotly_white", height=300, margin=dict(t=40, l=140, r=20, b=30),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
    )

    return html.Div(
        [
            html.H1("Consultas"),
            html.P("Agendamento do módulo Clínica/Hospital — ambulatório, organizado por especialidade e profissional.", className="texto-explicativo"),
            kpis,
            html.Div([html.H3("Consultas por especialidade"), dcc.Graph(figure=fig_especialidade, config={"displayModeBar": False})], className="cartao-secao"),
            html.Div(
                [
                    dcc.Input(id="pesquisa-consulta", type="text", placeholder="Pesquisar por nome do utente...", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="filtro-especialidade",
                        options=[{"label": e, "value": e} for e in ESPECIALIDADES],
                        placeholder="Especialidade",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(
                        id="filtro-estado-consulta",
                        options=[{"label": e, "value": e} for e in ["Agendada", "Realizada", "Cancelada", "Falta"]],
                        placeholder="Estado",
                        className="filtro-dropdown",
                    ),
                    dcc.RadioItems(
                        id="modo-vista-consultas",
                        options=[{"label": "Vista em lista", "value": "lista"}, {"label": "Vista de calendário", "value": "calendario"}],
                        value="lista",
                        className="alternador-vista-consultas",
                        inline=True,
                    ),
                ],
                className="filtros-utentes",
            ),
            dcc.Store(id="semana-consultas-inicio"),
            html.Div(id="corpo-tabela-consultas"),
        ]
    )


# --- Página: Faturação --------------------------------------------------------


def _formatar_euros(valor, casas_decimais=0):
    texto = f"{valor:,.{casas_decimais}f}"
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{texto} €"


def _pagina_faturacao():
    fat = DADOS["faturacao"].merge(DADOS["utentes"][["id_utente", "nome", "tipo_cuidado"]], on="id_utente")

    total_a_pagar = fat["valor_a_pagar_utente"].sum()
    total_comparticipacao = fat["comparticipacao_ss"].sum()
    total_ars = (fat["ars_diarias_internamento"] + fat["ars_pacote_medicamentos"] + fat["ars_remuneracao_adicional"]).sum()
    total_seguradoras = fat["valor_seguradora"].sum()
    utentes_com_seguro = int((fat["seguradora"] != "—").sum())
    erros = int(fat["erro_fatura"].sum())

    kpis = html.Div(
        [
            _cartao_kpi("Valor a pagar pelos utentes", _formatar_euros(total_a_pagar, 2)),
            _cartao_kpi("Comparticipação Segurança Social", _formatar_euros(total_comparticipacao)),
            _cartao_kpi("Total ARS (diárias + medicamentos + remuneração)", _formatar_euros(total_ars), tom="primaria"),
            _cartao_kpi("Faturado a seguradoras privadas", _formatar_euros(total_seguradoras, 2), nota=f"{utentes_com_seguro} utentes com seguro"),
            _cartao_kpi("Erros de fatura", erros, tom="risco_elevado" if erros else "risco_baixo"),
        ],
        className="kpis-linha",
    )

    botao_exportar = html.Div(
        [
            html.Button("Descarregar CSV", id="botao-csv-faturacao", className="botao-secundario"),
            dcc.Download(id="descarregar-csv-faturacao"),
        ],
        className="botoes-exportar",
    )

    tabela = dash_table.DataTable(
        columns=[
            {"name": "Utente", "id": "nome"},
            {"name": "Tipo", "id": "tipo_cuidado"},
            {"name": "Valor a pagar (€)", "id": "valor_a_pagar_utente"},
            {"name": "Comparticipação SS (€)", "id": "comparticipacao_ss"},
            {"name": "ARS diárias (€)", "id": "ars_diarias_internamento"},
            {"name": "ARS medicamentos (€)", "id": "ars_pacote_medicamentos"},
            {"name": "Seguradora", "id": "seguradora"},
            {"name": "Cobertura (%)", "id": "cobertura_percentual_seguro"},
            {"name": "Valor seguradora (€)", "id": "valor_seguradora"},
            {"name": "Copagamento (€)", "id": "copagamento_utente"},
            {"name": "Saldo CC (€)", "id": "saldo_cc"},
            {"name": "Erro?", "id": "erro_fatura"},
        ],
        data=fat.round(2).to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontFamily": "inherit", "fontSize": "0.82rem"},
        style_header={"fontWeight": "600", "backgroundColor": CORES["primaria_suave"]},
        style_data_conditional=[{"if": {"filter_query": "{erro_fatura} = true"}, "backgroundColor": CORES["risco_elevado_suave"]}],
        sort_action="native",
        filter_action="native",
        page_size=12,
    )

    return html.Div(
        [
            html.H1("Faturação"),
            kpis,
            html.Div([html.Div([html.H3("Detalhe por utente"), botao_exportar], className="cabecalho-secao"), tabela], className="cartao-secao"),
        ]
    )


# --- App -----------------------------------------------------------------------

app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Sistema de Gestão de Utentes"
server = app.server


def _construir_layout():
    return html.Div(
        [
            dcc.Location(id="url"),
            dcc.Store(id="perfil-sessao", storage_type="session"),
            html.Div(id="barra-lateral-app"),
            html.Div(html.Div(id="conteudo-pagina", className="pagina"), className="area-principal"),
        ],
        className="app-raiz",
    )


app.layout = _construir_layout


# --- Callbacks: sessão (login/logout, mock — sem autenticação real) ----------


@app.callback(
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input({"type": "botao-login-perfil", "perfil": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _entrar_com_perfil(cliques):
    if not ctx.triggered_id or not any(cliques):
        return dash.no_update, dash.no_update
    return ctx.triggered_id["perfil"], "/"


@app.callback(
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input("botao-sair-sessao", "n_clicks"),
    prevent_initial_call=True,
)
def _sair_sessao(n_clicks):
    if not n_clicks:
        return dash.no_update, dash.no_update
    return None, "/login"


# --- Callbacks: navegação ----------------------------------------------------


@app.callback(Output("barra-lateral-app", "children"), Input("url", "pathname"), Input("perfil-sessao", "data"))
def _atualizar_barra_lateral(caminho, perfil):
    if not perfil:
        return None
    return _barra_lateral(caminho or "/", perfil)


@app.callback(Output("conteudo-pagina", "children"), Input("url", "pathname"), Input("perfil-sessao", "data"))
def _rotear_pagina(caminho, perfil):
    caminho = caminho or "/"
    if caminho != "/login" and not perfil:
        return _pagina_login()
    if caminho == "/login":
        return _pagina_login()
    if caminho == "/":
        return _pagina_visao_geral()
    if caminho == "/utentes":
        return _pagina_utentes()
    if caminho.startswith("/utentes/"):
        id_utente = caminho.split("/utentes/")[-1]
        return _pagina_ficha_utente(id_utente)
    if caminho == "/ocupacao":
        return _pagina_ocupacao()
    if caminho == "/consultas":
        return _pagina_consultas()
    if caminho == "/faturacao":
        return _pagina_faturacao()
    if caminho == "/sobre":
        return _pagina_sobre()
    return html.Div([html.H2("Página não encontrada"), dcc.Link("Voltar ao início", href="/")])


@app.callback(
    Output("corpo-tabela-utentes", "children"),
    Input("pesquisa-utente", "value"),
    Input("filtro-tipo-cuidado", "value"),
    Input("filtro-estado", "value"),
)
def _filtrar_utentes(texto_pesquisa, tipo_cuidado, estado):
    df = DADOS["utentes"]
    if texto_pesquisa:
        df = df[df["nome"].str.contains(texto_pesquisa, case=False, na=False)]
    if tipo_cuidado:
        df = df[df["tipo_cuidado"] == tipo_cuidado]
    if estado:
        df = df[df["estado"] == estado]
    return _tabela_utentes(df)


@app.callback(
    Output("corpo-tabela-consultas", "children"),
    Input("pesquisa-consulta", "value"),
    Input("filtro-especialidade", "value"),
    Input("filtro-estado-consulta", "value"),
    Input("modo-vista-consultas", "value"),
    Input("semana-consultas-inicio", "data"),
)
def _filtrar_consultas(texto_pesquisa, especialidade, estado, modo="lista", semana_inicio_iso=None):
    df = DADOS["consultas"]
    if texto_pesquisa:
        ids_correspondentes = DADOS["utentes"][DADOS["utentes"]["nome"].str.contains(texto_pesquisa, case=False, na=False)]["id_utente"]
        df = df[df["id_utente"].isin(ids_correspondentes)]
    if especialidade:
        df = df[df["especialidade"] == especialidade]
    if estado:
        df = df[df["estado"] == estado]
    if modo == "calendario":
        inicio = pd.Timestamp(semana_inicio_iso) if semana_inicio_iso else _inicio_semana_atual()
        return _vista_calendario_consultas(df, inicio)
    return _tabela_consultas(df)


@app.callback(
    Output("semana-consultas-inicio", "data"),
    Input("botao-semana-anterior", "n_clicks"),
    Input("botao-semana-seguinte", "n_clicks"),
    State("semana-consultas-inicio", "data"),
    prevent_initial_call=True,
)
def _navegar_semana_consultas(n_anterior, n_seguinte, semana_atual_iso):
    inicio = pd.Timestamp(semana_atual_iso) if semana_atual_iso else _inicio_semana_atual()
    if ctx.triggered_id == "botao-semana-anterior":
        inicio -= pd.Timedelta(days=7)
    elif ctx.triggered_id == "botao-semana-seguinte":
        inicio += pd.Timedelta(days=7)
    return inicio.date().isoformat()


# --- Callbacks: ficha do utente — sinais vitais -------------------------------


@app.callback(Output("grafico-sinais-vitais", "figure"), Input("seletor-sinal-vital", "value"), Input("url", "pathname"))
def _atualizar_grafico_vitais(sinal, caminho):
    if not caminho or not caminho.startswith("/utentes/"):
        return go.Figure()
    id_utente = caminho.split("/utentes/")[-1]
    df = DADOS["vitais"][DADOS["vitais"]["id_utente"] == id_utente].sort_values("data_hora")
    fig = go.Figure(go.Scatter(x=df["data_hora"], y=df[sinal], mode="lines+markers", line=dict(color=CORES["primaria"])))
    fig.update_layout(
        template="plotly_white", height=320, margin=dict(t=20, l=50, r=20, b=40),
        paper_bgcolor=CORES["cartao"], plot_bgcolor=CORES["cartao"], font_color=CORES["texto"],
    )
    return fig


# --- Callbacks: avaliação de risco --------------------------------------------


@app.callback(
    Output("resultado-diabetes-tab", "children"),
    Output("resultado-diabetes-armazenado", "data"),
    Input("botao-calcular-diabetes", "n_clicks"),
    [State(f"input-fx-diabetes-{c}", "value") for c in RES_DIABETES],
    prevent_initial_call=True,
)
def _calcular_diabetes_tab(n_clicks, *valores):
    if not n_clicks:
        return "", None
    linha = pd.DataFrame([dict(zip(RES_DIABETES.keys(), valores, strict=True))])
    probabilidade = float(MODELO_DIABETES.predict_proba(linha)[0, 1])
    classificacao, tom = classificar_risco(probabilidade)
    resultado = html.Div([html.Strong(classificacao), f" — {probabilidade:.0%}"], className=f"resultado-inline resultado-inline--{tom}")
    fatores = principais_fatores(METRICAS_DIABETES["importancia_features"], RES_DIABETES)
    return resultado, [probabilidade, classificacao, fatores]


@app.callback(
    Output("resultado-cardio-tab", "children"),
    Output("resultado-cardio-armazenado", "data"),
    Input("botao-calcular-cardio", "n_clicks"),
    [State(f"input-fx-cardio-{c}", "value") for c in COLUNAS_CARDIO],
    prevent_initial_call=True,
)
def _calcular_cardio_tab(n_clicks, *valores):
    if not n_clicks:
        return "", None
    bruto = dict(zip(COLUNAS_CARDIO, valores, strict=True))
    mapeado = dict(bruto)
    mapeado["sexo"] = OPCOES_SEXO[bruto["sexo"]]
    mapeado["tipo_dor_peito"] = OPCOES_TIPO_DOR_PEITO[bruto["tipo_dor_peito"]]
    mapeado["glicemia_jejum_elevada"] = OPCOES_SIM_NAO[bruto["glicemia_jejum_elevada"]]
    mapeado["ecg_repouso"] = OPCOES_ECG_REPOUSO[bruto["ecg_repouso"]]
    mapeado["angina_exercicio"] = OPCOES_SIM_NAO[bruto["angina_exercicio"]]
    mapeado["inclinacao_st"] = OPCOES_INCLINACAO_ST[bruto["inclinacao_st"]]
    mapeado["talassemia"] = OPCOES_TALASSEMIA[bruto["talassemia"]]

    linha = pd.DataFrame([mapeado])[COLUNAS_CARDIO]
    probabilidade = float(MODELO_CARDIO.predict_proba(linha)[0, 1])
    classificacao, tom = classificar_risco(probabilidade)
    resultado = html.Div([html.Strong(classificacao), f" — {probabilidade:.0%}"], className=f"resultado-inline resultado-inline--{tom}")
    fatores = principais_fatores(METRICAS_CARDIO["importancia_features"], RES_CARDIO)
    return resultado, [probabilidade, classificacao, fatores]


@app.callback(
    Output("resultado-queda-tab", "children"),
    Output("resultado-queda-armazenado", "data"),
    Input("botao-calcular-queda", "n_clicks"),
    State("input-fx-queda-historico", "value"),
    State("input-fx-queda-secundario", "value"),
    State("input-fx-queda-apoio", "value"),
    State("input-fx-queda-soro", "value"),
    State("input-fx-queda-marcha", "value"),
    State("input-fx-queda-mental", "value"),
    prevent_initial_call=True,
)
def _calcular_queda_tab(n_clicks, historico, secundario, apoio, soro, marcha, mental):
    if not n_clicks:
        return "", None
    pontuacao, classificacao, tom = calcular_risco_queda(historico, secundario, apoio, soro, marcha, mental)
    resultado = html.Div([html.Strong(classificacao), f" — Morse {pontuacao}/125"], className=f"resultado-inline resultado-inline--{tom}")
    return resultado, [pontuacao, classificacao, tom]


@app.callback(
    Output("descarregar-csv-faturacao", "data"),
    Input("botao-csv-faturacao", "n_clicks"),
    prevent_initial_call=True,
)
def _descarregar_csv_faturacao(n_clicks):
    fat = DADOS["faturacao"].merge(DADOS["utentes"][["id_utente", "nome", "tipo_cuidado"]], on="id_utente")
    fat = fat.rename(
        columns={
            "nome": "Utente",
            "tipo_cuidado": "Tipo",
            "valor_a_pagar_utente": "Valor a pagar (€)",
            "comparticipacao_ss": "Comparticipação SS (€)",
            "ars_diarias_internamento": "ARS diárias (€)",
            "ars_pacote_medicamentos": "ARS medicamentos (€)",
            "ars_remuneracao_adicional": "ARS remuneração adicional (€)",
            "seguradora": "Seguradora",
            "numero_apolice": "Nº apólice",
            "cobertura_percentual_seguro": "Cobertura seguro (%)",
            "valor_seguradora": "Valor seguradora (€)",
            "copagamento_utente": "Copagamento utente (€)",
            "saldo_cc": "Saldo CC (€)",
            "erro_fatura": "Erro de fatura",
        }
    )
    # sep=";" e encoding="utf-8-sig": o Excel em português usa a vírgula como
    # separador decimal, por isso espera ";" a separar colunas num CSV — com
    # sep="," (o padrão do pandas) o ficheiro abre tudo numa única coluna. O
    # "utf-8-sig" garante que os acentos (é, ç, ã...) aparecem corretos.
    return dcc.send_data_frame(fat.to_csv, "faturacao.csv", index=False, sep=";", encoding="utf-8-sig")


@app.callback(
    Output("resultado-resumo-ia", "children"),
    Input("botao-gerar-resumo", "n_clicks"),
    State("resultado-diabetes-armazenado", "data"),
    State("resultado-cardio-armazenado", "data"),
    State("resultado-queda-armazenado", "data"),
    State("utente-atual-nome", "data"),
    prevent_initial_call=True,
)
def _gerar_resumo(n_clicks, res_diabetes, res_cardio, res_queda, nome_utente):
    if not n_clicks:
        return ""
    resumo = gerar_resumo_ia(
        nome_utente,
        resultado_diabetes=tuple(res_diabetes) if res_diabetes else None,
        resultado_cardio=tuple(res_cardio) if res_cardio else None,
        resultado_queda=tuple(res_queda) if res_queda else None,
    )
    return resumo


# --- Exportação em PDF da ficha do utente -------------------------------------


def _gerar_pdf_ficha(id_utente):
    utente = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == id_utente].iloc[0]
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    margem_esquerda = 20 * mm
    posicao_y = altura - 20 * mm

    def escrever(texto, tamanho=10, negrito=False, espaco=6 * mm):
        nonlocal posicao_y
        if posicao_y < 25 * mm:
            c.showPage()
            posicao_y = altura - 20 * mm
        c.setFont("Helvetica-Bold" if negrito else "Helvetica", tamanho)
        c.drawString(margem_esquerda, posicao_y, texto)
        posicao_y -= espaco

    escrever(f"Ficha clínica — {utente['nome']}", 16, negrito=True, espaco=10 * mm)
    escrever(
        f"{utente['genero']} · {_idade_utente(utente['data_nascimento'])} anos · "
        f"{utente['tipo_cuidado']} · Processo {utente['processo']}",
        10,
    )
    escrever(f"Estado: {utente['estado']}   Admissão: {utente['data_admissao']}", 10, espaco=10 * mm)

    alergias = DADOS["alergias"][DADOS["alergias"]["id_utente"] == id_utente]["alergia"].tolist()
    escrever("Alergias", 12, negrito=True)
    escrever(", ".join(alergias) if alergias else "Nenhuma conhecida", 10, espaco=10 * mm)

    diagnosticos = DADOS["diagnosticos"][DADOS["diagnosticos"]["id_utente"] == id_utente].sort_values("data", ascending=False)
    escrever("Diagnósticos", 12, negrito=True)
    if diagnosticos.empty:
        escrever("Sem diagnósticos registados.", 10)
    for _idx, d in diagnosticos.iterrows():
        escrever(f"- {d['data']}: {d['diagnostico']} ({d['profissional']})", 9, espaco=5 * mm)
    posicao_y -= 4 * mm

    plano = DADOS["plano_cuidados"][DADOS["plano_cuidados"]["id_utente"] == id_utente]
    escrever("Plano de cuidados multidisciplinar", 12, negrito=True)
    if plano.empty:
        escrever("Sem plano de cuidados registado.", 10)
    for _idx, p in plano.iterrows():
        escrever(
            f"- [{p['area_profissional']}] {p['objetivo']} — {p['estado']} ({p['progresso_percent']}%) · "
            f"Resp.: {p['profissional_responsavel']}",
            9,
            espaco=5 * mm,
        )
    posicao_y -= 4 * mm

    ultimos_vitais = DADOS["vitais"][DADOS["vitais"]["id_utente"] == id_utente].sort_values("data_hora").tail(1)
    escrever("Últimos sinais vitais", 12, negrito=True)
    if len(ultimos_vitais):
        v = ultimos_vitais.iloc[0]
        escrever(
            f"Glicemia: {v['glicemia']} mg/dL · Peso: {v['peso_kg']} kg · "
            f"Tensão: {v['tensao_sistolica']}/{v['tensao_diastolica']} mmHg · Temp.: {v['temperatura']}°C",
            10,
        )
    else:
        escrever("Sem sinais vitais registados.", 10)

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        margem_esquerda, 15 * mm,
        "Documento gerado automaticamente — demonstração técnica de portfólio, dados sintéticos, não usar com pacientes reais.",
    )

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


@app.callback(
    Output("descarregar-pdf-ficha", "data"),
    Input("botao-pdf-ficha", "n_clicks"),
    State("utente-atual-id", "data"),
    prevent_initial_call=True,
)
def _descarregar_pdf_ficha(n_clicks, id_utente):
    if not n_clicks or not id_utente:
        return dash.no_update
    pdf_bytes = _gerar_pdf_ficha(id_utente)
    return dcc.send_bytes(lambda b: b.write(pdf_bytes), f"ficha_{id_utente}.pdf")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8051)