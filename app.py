"""Sistema de Gestão de Utentes e Cuidados de Saúde — projeto de portfólio.

Inspirado (só na ideia funcional, nunca na marca/design) em dois produtos
reais pesquisados antes de construir isto: hitCare (hitEcosystem), software
português para UCC/ERPI/SAD com mapas de ocupação/altas e faturação com a
Segurança Social, e LinkHMS, um sistema hospitalar com ficha clínica por
paciente (EMR). Nada aqui reproduz o logótipo, as cores de marca ou o
layout exato de nenhum dos dois — é uma implementação original, com os
mesmos tipos de módulo.

Quatro módulos, navegação lateral:
  /utentes           — lista de utentes (pesquisa/filtro)
  /utentes/<id>       — ficha do utente: resumo, sinais vitais, alergias &
                         diagnósticos, prescrições, visitas, documentos, e
                         avaliação de risco (diabetes + cardiovascular, por
                         machine learning, + risco de queda pela Morse Fall
                         Scale — instrumento clínico publicado), com um
                         resumo automático em linguagem natural (motor de
                         regras local, sem API externa) para o profissional
                         ler em segundos antes de decidir.
  /ocupacao           — capacidade, ocupação e altas por tipo de cuidado
  /faturacao          — valores a pagar, comparticipação, ARS, saldos

Dados: tudo sintético (ver scripts/gerar_dados_utentes.py). Os modelos de
risco são treinados em datasets públicos e anonimizados (Pima Diabetes, UCI
Heart Disease) — nenhuma pessoa real, utente ou paciente está representada
em nenhum ficheiro deste projeto. Esta ferramenta é uma demonstração
técnica de portfólio, não um sistema clínico certificado.
"""
import datetime
import json
import pathlib

import dash
import joblib
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dash_table, dcc, html

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
    dados["faturacao"] = pd.read_csv(PASTA_DADOS / "faturacao.csv")
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


def _barra_lateral(caminho_atual):
    itens = [("/utentes", "Utentes"), ("/ocupacao", "Mapa de Ocupação"), ("/faturacao", "Faturação")]
    ligacoes = []
    for destino, rotulo in itens:
        ativa = caminho_atual == destino or (destino == "/utentes" and caminho_atual.startswith("/utentes"))
        classe = "ligacao-lateral" + (" ligacao-lateral--ativa" if ativa else "")
        ligacoes.append(dcc.Link(rotulo, href=destino, className=classe))
    return html.Div(
        [
            html.Div("Gestão de Saúde", className="logotipo-lateral"),
            html.Nav(ligacoes, className="nav-lateral"),
        ],
        className="barra-lateral",
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
                    html.Td(u["tipo_cuidado"]),
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
    internados = int((df["estado"] == "Internado").sum())
    em_espera = int((df["estado"] == "Em espera").sum())
    altas_mes = len(DADOS["altas"])

    return html.Div(
        [
            html.H1("Utentes"),
            html.Div(
                [
                    _cartao_kpi("Total de utentes", total),
                    _cartao_kpi("Internados", internados, tom="primaria"),
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
                        options=[{"label": t, "value": t} for t in ["UCC", "ERPI", "SAD"]],
                        placeholder="Tipo de cuidado",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(
                        id="filtro-estado",
                        options=[{"label": e, "value": e} for e in ["Internado", "Alta", "Em espera"]],
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
            dcc.Link("← Voltar à lista de utentes", href="/utentes", className="ligacao-voltar"),
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
                    dcc.Tab(label="Prescrições", value="prescricoes", children=[_aba_prescricoes(id_utente)]),
                    dcc.Tab(label="Visitas", value="visitas", children=[_aba_visitas(id_utente)]),
                    dcc.Tab(label="Documentos", value="documentos", children=[_aba_documentos(id_utente)]),
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
    erros = int(fat["erro_fatura"].sum())

    kpis = html.Div(
        [
            _cartao_kpi("Valor a pagar pelos utentes", _formatar_euros(total_a_pagar, 2)),
            _cartao_kpi("Comparticipação Segurança Social", _formatar_euros(total_comparticipacao)),
            _cartao_kpi("Total ARS (diárias + medicamentos + remuneração)", _formatar_euros(total_ars), tom="primaria"),
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
            html.Div(id="barra-lateral-app"),
            html.Div(html.Div(id="conteudo-pagina", className="pagina"), className="area-principal"),
        ],
        className="app-raiz",
    )


app.layout = _construir_layout


# --- Callbacks: navegação ----------------------------------------------------


@app.callback(Output("barra-lateral-app", "children"), Input("url", "pathname"))
def _atualizar_barra_lateral(caminho):
    return _barra_lateral(caminho or "/utentes")


@app.callback(Output("conteudo-pagina", "children"), Input("url", "pathname"))
def _rotear_pagina(caminho):
    caminho = caminho or "/utentes"
    if caminho in ("/", "/utentes"):
        return _pagina_utentes()
    if caminho.startswith("/utentes/"):
        id_utente = caminho.split("/utentes/")[-1]
        return _pagina_ficha_utente(id_utente)
    if caminho == "/ocupacao":
        return _pagina_ocupacao()
    if caminho == "/faturacao":
        return _pagina_faturacao()
    return html.Div([html.H2("Página não encontrada"), dcc.Link("Voltar ao início", href="/utentes")])


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
            "saldo_cc": "Saldo CC (€)",
            "erro_fatura": "Erro de fatura",
        }
    )
    return dcc.send_data_frame(fat.to_csv, "faturacao.csv", index=False)


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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8051)
