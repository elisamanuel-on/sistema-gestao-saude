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
o perfil de acesso escolhido no login — Enfermeiro, Médico, Receção ou
Admin, uma simulação sem autenticação real):
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
  /faturacao          — valores a pagar, comparticipação, ARS, seguros,
                         saldos, exportação em Excel (.xlsx) ou CSV
  /profissionais      — cadastro de profissionais (médicos + equipa de
                         apoio): adicionar, editar, marcar inativo/ativo,
                         remover (bloqueado se houver histórico associado)
  /sobre              — sobre este projeto (para quem abre o link direto)

Nota sobre persistência: não há base de dados — os dados vivem em memória,
carregados uma vez a partir dos CSV no arranque do servidor. Consultas
criadas/canceladas/reagendadas e profissionais adicionados/editados/
removidos pela própria aplicação ficam só nessa memória: refletem-se
imediatamente para quem estiver a usar o sistema, mas perdem-se se o
servidor reiniciar. Decisão de âmbito consciente para um projeto de
portfólio — ver README.

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
import urllib.parse

import dash
import joblib
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dash_table, dcc, html
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from constantes import (
    CATEGORIAS_PROFISSIONAL,
    ESPECIALIDADES,
    HORARIOS_CONSULTA,
    PERFIS_ACESSO,
    PERFIS_GESTAO_AGENDA,
    PERFIS_RELATORIO_QUALQUER_PROFISSIONAL,
    PERFIS_SEM_ATOS_CLINICOS,
    SALAS_CONSULTA,
    SECCOES_POR_PERFIL,
    TIPOS_CUIDADO,
)
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
    "tabela_zebra": "#f3f6f5",
}

# Estilo partilhado por todas as tabelas (dash_table.DataTable) — evita
# repetir o mesmo dicionário em cada uma das tabelas da app e mantém a
# densidade/leitura consistente: mais espaço vertical entre linhas do que
# o valor por omissão, cabeçalho bem demarcado, e zebra-striping subtil
# para acompanhar uma linha em tabelas mais longas sem ter de contar
# colunas.
ESTILO_CELULA_TABELA = {"padding": "10px 12px", "fontFamily": "inherit", "fontSize": "0.85rem", "lineHeight": "1.5"}
ESTILO_CABECALHO_TABELA = {
    "fontWeight": "600",
    "backgroundColor": CORES["primaria_suave"],
    "padding": "10px 12px",
    "borderBottom": f"2px solid {CORES['primaria']}",
}
ZEBRA_TABELA = [{"if": {"row_index": "odd"}, "backgroundColor": CORES["tabela_zebra"]}]


def _com_zebra(condicionais=None):
    """Antepõe o zebra-striping a uma lista de regras style_data_conditional
    já existente — as regras mais específicas (estado da consulta, exame
    alterado, fatura com erro, etc.) vêm a seguir e por isso continuam a
    ganhar sobre a cor de linha par/ímpar."""
    return ZEBRA_TABELA + (condicionais or [])


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
    dados["prescricoes"]["duracao"] = ""
    dados["prescricoes"]["id_prescricao"] = [f"RX{i + 1:05d}" for i in range(len(dados["prescricoes"]))]
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
    dados["profissionais"] = pd.read_csv(PASTA_DADOS / "profissionais.csv")
    dados["profissionais"]["especialidade"] = dados["profissionais"]["especialidade"].fillna("")
    dados["profissionais"]["contacto"] = dados["profissionais"]["contacto"].fillna("—")
    dados["profissionais"]["numero_cedula"] = dados["profissionais"]["numero_cedula"].fillna("—")
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


def _registar_historico(id_utente, profissional, acao):
    """Acrescenta uma linha ao histórico/auditoria do utente — chamado
    sempre que uma ação do módulo de agendamento (marcar/cancelar/reagendar
    consulta) altera algo. Só em memória, tal como o resto dos dados
    criados pela própria aplicação (ver nota de persistência no topo do
    ficheiro)."""
    novo_id = f"H{len(DADOS['historico']) + 1:05d}"
    nova_linha = pd.DataFrame(
        [{"id_evento": novo_id, "id_utente": id_utente, "data_hora": pd.Timestamp.now(), "profissional": profissional, "acao": acao}]
    )
    DADOS["historico"] = pd.concat([DADOS["historico"], nova_linha], ignore_index=True)


def _proximo_id_prescricao():
    if DADOS["prescricoes"].empty:
        return "RX00001"
    maior = DADOS["prescricoes"]["id_prescricao"].str.lstrip("RX").astype(int).max()
    return f"RX{maior + 1:05d}"


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
    ("Relatórios", [("/relatorios", "Relatórios")]),
    ("Faturação", [("/faturacao", "Faturação")]),
    ("Profissionais", [("/profissionais", "Profissionais")]),
]


def _barra_lateral(caminho_atual, perfil, profissional=None):
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
            html.Div(
                [
                    html.Img(src="/assets/icones/logo.svg", className="icone-logotipo-lateral"),
                    html.Span("Gestão de Saúde", className="logotipo-lateral-texto"),
                ],
                className="logotipo-lateral",
            ),
            html.Div(seccoes, className="grupo-nav-lateral"),
            html.Div(
                [
                    html.Div(
                        f"Perfil: {perfil}" + (f" — {profissional}" if profissional else ""),
                        className="perfil-atual-lateral",
                    ),
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

ICONES_PERFIL = {
    "Enfermeiro": "/assets/icones/enfermeiro.svg",
    "Médico": "/assets/icones/medico.svg",
    "Receção": "/assets/icones/recepcao.svg",
    "Admin": "/assets/icones/admin.svg",
}

# Enfermeiro e Médico exigem um segundo passo no login — escolher QUAL
# profissional (nome vindo de profissionais.csv) — porque a agenda própria,
# a receita assinada e o relatório de atividade só fazem sentido associados
# a uma pessoa concreta, não a um perfil genérico. Receção e Admin não
# precisam: não geram receitas nem relatórios de atividade pessoal, agem em
# nome do serviço como um todo.
PERFIS_COM_PROFISSIONAL = {"Médico", "Enfermeiro"}


def _dados_sessao(sessao):
    """Normaliza o valor guardado em perfil-sessao: {'perfil':..., 'profissional':...}.
    Aceita também o formato antigo (string simples, de sessões guardadas antes
    desta funcionalidade) para não partir sessões já abertas no browser."""
    if not sessao:
        return None, None
    if isinstance(sessao, str):
        return sessao, None
    return sessao.get("perfil"), sessao.get("profissional")


def _pagina_login():
    return html.Div(
        html.Div(
            [
                html.Img(src="/assets/icones/logo.svg", className="logotipo-login"),
                html.H1("Gestão de Saúde"),
                dcc.Store(id="perfil-provisorio-login", storage_type="memory"),
                html.Div(id="corpo-login"),
            ],
            className="cartao-login",
        ),
        className="ecra-login",
    )


def _corpo_login_escolha_perfil():
    botoes = [
        html.Button(
            [html.Img(src=ICONES_PERFIL.get(perfil, ""), className="icone-perfil-login"), html.Span(perfil)],
            id={"type": "botao-login-perfil", "perfil": perfil},
            n_clicks=0,
            className="botao-perfil-login",
        )
        for perfil in PERFIS_ACESSO
    ]
    return html.Div(
        [
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
        ]
    )


def _corpo_login_escolha_profissional(perfil):
    disponiveis = DADOS["profissionais"]
    disponiveis = disponiveis[(disponiveis["categoria"] == perfil) & (disponiveis["estado"] == "Ativo")].sort_values("nome")
    if disponiveis.empty:
        corpo_lista = html.P(f"Não há profissionais ativos na categoria {perfil}.", className="texto-explicativo")
    else:
        corpo_lista = html.Div(
            [
                html.Button(
                    html.Span(p["nome"]),
                    id={"type": "botao-login-profissional", "nome": p["nome"]},
                    n_clicks=0,
                    className="botao-perfil-login",
                )
                for _idx, p in disponiveis.iterrows()
            ],
            className="grupo-botoes-perfil-login",
        )
    return html.Div(
        [
            html.P(f"Perfil {perfil} — agora escolhe qual profissional és:", className="texto-explicativo"),
            corpo_lista,
            html.Button("‹ Voltar", id="botao-voltar-login", className="botao-secundario", n_clicks=0),
        ]
    )


# --- Página: Visão Geral (dashboard inicial) ---------------------------------


def _linha_alerta(tom, texto, href):
    return dcc.Link(
        html.Div([html.Span(className=f"ponto-alerta ponto-alerta--{tom}"), html.Span(texto)], className="linha-alerta"),
        href=href,
        className="ligacao-alerta",
    )


# Uma frase por perfil, para quem nunca viu o sistema perceber em segundos
# o que pode fazer aqui — mostrado uma vez (guardado em localStorage, por
# perfil, para reaparecer se entrar com outro perfil da próxima vez).
ORIENTACAO_POR_PERFIL = {
    "Enfermeiro": "Vês a ficha clínica dos utentes, registas sinais vitais e cuidados, e consultas a tua agenda — sem acesso a faturação nem à gestão de profissionais.",
    "Médico": "Além da ficha clínica, podes prescrever medicação e emitir receitas em PDF, e consultas o teu relatório de atividade — sem acesso a faturação nem à gestão de profissionais.",
    "Receção": "Marca, cancela e reagenda consultas, consultas a ocupação e emites faturação — sem acesso a atos clínicos (prescrições, avaliação de risco) nem à gestão de profissionais.",
    "Admin": "Acesso total: tudo o que a Receção faz, mais a gestão do cadastro de profissionais e os relatórios de atividade de qualquer um deles.",
}


def _banner_orientacao(perfil):
    texto = ORIENTACAO_POR_PERFIL.get(perfil)
    if not texto:
        return None
    return html.Div(
        [
            html.Div(
                [
                    html.Strong(f"Perfil {perfil}: "),
                    texto,
                ]
            ),
            html.Button("Entendi, não mostrar mais", id="botao-dispensar-orientacao", className="botao-secundario", n_clicks=0),
        ],
        className="banner-orientacao",
    )


def _pagina_visao_geral(perfil=None, dispensada=None):
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

    banner = None
    if perfil and not (dispensada or {}).get(perfil):
        banner = _banner_orientacao(perfil)

    return html.Div(
        [
            *([banner] if banner else []),
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
                    html.Li("Visão Geral com KPIs agregados e alertas, e acesso por perfil (Enfermeiro/Médico/Receção/Admin)."),
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
                style_cell=ESTILO_CELULA_TABELA,
                style_header=ESTILO_CABECALHO_TABELA,
                style_data_conditional=_com_zebra(),
                page_size=8,
            ),
        ]
    )


def _aba_prescricoes(id_utente, perfil=None, profissional=None):
    # O formulário "+ Nova Prescrição" (e a sua mensagem de confirmação) fica
    # fora do contentor dinâmico de baixo: se estivesse lá dentro, o próprio
    # re-render disparado pela criação apagava a mensagem antes de dar para
    # ler (o contentor é reconstruído do zero a cada atualização).
    mostrar_criar = perfil == "Médico" and profissional
    return html.Div(
        [
            dcc.Store(id="prescricoes-atualizacao", data=0),
            html.Div(id="corpo-prescricoes"),
            *([_formulario_nova_prescricao()] if mostrar_criar else []),
        ]
    )


def _formulario_nova_prescricao():
    return html.Details(
        [
            html.Summary("+ Nova Prescrição", className="resumo-details"),
            html.Div(
                [
                    dcc.Input(id="form-prescricao-medicamento", placeholder="Medicamento", type="text", className="campo-pesquisa"),
                    dcc.Input(id="form-prescricao-posologia", placeholder="Posologia (ex: 50mg, 1x/dia)", type="text", className="campo-pesquisa"),
                    dcc.Input(id="form-prescricao-duracao", placeholder="Duração (ex: 7 dias)", type="text", className="campo-pesquisa"),
                ],
                className="grelha-formulario",
            ),
            html.Button("Registar prescrição", id="botao-criar-prescricao", className="botao-primario", n_clicks=0),
            html.Div(id="mensagem-criar-prescricao", className="resultado-mini"),
        ],
        className="painel-details",
    )


def _corpo_prescricoes(id_utente, perfil=None, profissional=None):
    prescricoes = DADOS["prescricoes"][DADOS["prescricoes"]["id_utente"] == id_utente].sort_values("data", ascending=False)
    tabela = dash_table.DataTable(
        columns=[
            {"name": "Data", "id": "data"},
            {"name": "Profissional", "id": "profissional"},
            {"name": "Medicamento", "id": "medicamento"},
            {"name": "Posologia", "id": "posologia"},
            {"name": "Duração", "id": "duracao"},
        ],
        data=prescricoes.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell=ESTILO_CELULA_TABELA,
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra(),
        page_size=10,
    )

    # Emitir a receita em PDF é um ato clínico — só o Médico (autenticado
    # com a sua identidade própria) o pode fazer; ver também
    # _formulario_nova_prescricao, gerido separadamente em _aba_prescricoes.
    if perfil != "Médico" or not profissional:
        return html.Div([tabela])

    proprias = prescricoes[prescricoes["profissional"] == profissional]
    opcoes_receita = [
        {"label": f"{r['data']} · {r['medicamento']} ({r['posologia']})", "value": r["id_prescricao"]}
        for _idx, r in proprias.iterrows()
    ]

    painel_receita = html.Div(
        [
            html.H3("Gerar receita em PDF"),
            html.P("Só é possível emitir receita das prescrições registadas por ti.", className="texto-explicativo"),
            dcc.Dropdown(id="select-prescricao-receita", options=opcoes_receita, placeholder="Escolhe uma prescrição...", className="filtro-dropdown"),
            html.Div(
                [html.Button("Descarregar receita PDF", id="botao-gerar-receita", className="botao-secundario", n_clicks=0)],
                className="botoes-exportar",
            ),
            dcc.Download(id="descarregar-receita-pdf"),
            html.Div(id="mensagem-gerar-receita", className="resultado-mini"),
        ],
        className="cartao-secao",
    )

    return html.Div([tabela, painel_receita])


def _aba_visitas(id_utente):
    visitas = DADOS["visitas"][DADOS["visitas"]["id_utente"] == id_utente]
    return dash_table.DataTable(
        columns=[{"name": "Data/Hora", "id": "data_hora"}, {"name": "Tipo", "id": "tipo"}, {"name": "Registado por", "id": "registado_por"}],
        data=visitas.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell=ESTILO_CELULA_TABELA,
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra(),
        page_size=10,
    )


def _aba_documentos(id_utente):
    documentos = DADOS["documentos"][DADOS["documentos"]["id_utente"] == id_utente]
    return html.Div(
        [
            html.Div(
                [
                    html.Img(src="/assets/icones/documento.svg", className="icone-documento"),
                    html.Span(d["nome_documento"]),
                    html.Span(d["data_upload"], className="data-documento"),
                ],
                className="linha-documento",
            )
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
        style_cell=ESTILO_CELULA_TABELA,
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra(
            [
                {"if": {"filter_query": '{estado} = "Alterado"'}, "backgroundColor": CORES["risco_elevado_suave"]},
                {"if": {"filter_query": '{estado} = "Pendente"'}, "backgroundColor": CORES["risco_moderado_suave"]},
            ]
        ),
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
        style_cell=ESTILO_CELULA_TABELA,
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra(),
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


def _pagina_ficha_utente(id_utente, perfil=None, profissional=None):
    linha = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == id_utente]
    if linha.empty:
        return html.Div([html.H2("Utente não encontrado"), dcc.Link("Voltar à lista", href="/utentes")])
    utente = linha.iloc[0]

    abas = [
        dcc.Tab(label="Resumo", value="resumo", children=[_aba_resumo(id_utente, utente)]),
        dcc.Tab(label="Sinais vitais", value="vitais", children=[_aba_vitais(id_utente)]),
        dcc.Tab(label="Alergias & Diagnósticos", value="alergias", children=[_aba_alergias_diagnosticos(id_utente)]),
        dcc.Tab(label="Exames", value="exames", children=[_aba_exames(id_utente)]),
        dcc.Tab(label="Prescrições", value="prescricoes", children=[_aba_prescricoes(id_utente, perfil, profissional)]),
        dcc.Tab(label="Plano de Cuidados", value="plano_cuidados", children=[_aba_plano_cuidados(id_utente)]),
        dcc.Tab(label="Visitas", value="visitas", children=[_aba_visitas(id_utente)]),
        dcc.Tab(label="Documentos", value="documentos", children=[_aba_documentos(id_utente)]),
        dcc.Tab(label="Histórico", value="historico", children=[_aba_historico(id_utente)]),
    ]
    # Avaliação de risco é um ato clínico (calcular/registar um risco), não
    # uma simples consulta de dados — por isso fica de fora para a Receção,
    # que só tem acesso de leitura à ficha do utente. Admin vê tudo.
    if perfil not in PERFIS_SEM_ATOS_CLINICOS:
        abas.append(dcc.Tab(label="Avaliação de risco", value="risco", children=[_aba_avaliacao_risco(id_utente)]))

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
            dcc.Tabs(id="abas-ficha-utente", value="resumo", children=abas),
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
        style_cell=ESTILO_CELULA_TABELA,
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra(
            [
                {"if": {"filter_query": '{estado} = "Agendada"'}, "backgroundColor": CORES["primaria_suave"]},
                {"if": {"filter_query": '{estado} = "Falta"'}, "backgroundColor": CORES["risco_elevado_suave"]},
                {"if": {"filter_query": '{estado} = "Cancelada"'}, "backgroundColor": CORES["borda"]},
            ]
        ),
        sort_action="native",
        page_size=14,
    )


def _proximo_id_consulta():
    if DADOS["consultas"].empty:
        return "C00001"
    maior = DADOS["consultas"]["id_consulta"].str.lstrip("C").astype(int).max()
    return f"C{maior + 1:05d}"


def _conflito_consulta(profissional, sala, data_hora, excluir_id=None):
    """True se já existir uma consulta ativa (Agendada/Realizada) para o
    mesmo profissional ou a mesma sala, à mesma data/hora — usado ao criar
    ou reagendar, para não deixar marcar duas consultas em cima uma da
    outra."""
    ativas = DADOS["consultas"][DADOS["consultas"]["estado"].isin(["Agendada", "Realizada"])]
    if excluir_id:
        ativas = ativas[ativas["id_consulta"] != excluir_id]
    mesma_hora = ativas[ativas["data_hora"] == data_hora]
    return bool(((mesma_hora["profissional"] == profissional) | (mesma_hora["sala"] == sala)).any())


def _formulario_nova_consulta():
    opcoes_utente = [{"label": f"{u['nome']} ({u['id_utente']})", "value": u["id_utente"]} for _idx, u in DADOS["utentes"].iterrows()]
    return html.Details(
        [
            html.Summary("+ Nova Consulta", className="resumo-details"),
            html.Div(
                [
                    dcc.Dropdown(id="form-consulta-utente", options=opcoes_utente, placeholder="Utente", className="filtro-dropdown"),
                    dcc.Dropdown(
                        id="form-consulta-especialidade",
                        options=[{"label": e, "value": e} for e in ESPECIALIDADES],
                        placeholder="Especialidade",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(id="form-consulta-profissional", placeholder="Profissional (escolhe a especialidade primeiro)", className="filtro-dropdown"),
                    dcc.DatePickerSingle(
                        id="form-consulta-data",
                        placeholder="Data",
                        display_format="DD/MM/YYYY",
                        month_format="MM/YYYY",
                        first_day_of_week=1,
                        min_date_allowed=datetime.date.today(),
                    ),
                    dcc.Dropdown(
                        id="form-consulta-hora",
                        options=[{"label": h, "value": h} for h in HORARIOS_CONSULTA],
                        placeholder="Hora",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(id="form-consulta-sala", options=[{"label": s, "value": s} for s in SALAS_CONSULTA], placeholder="Sala", className="filtro-dropdown"),
                ],
                className="grelha-formulario",
            ),
            html.Button("Marcar consulta", id="botao-criar-consulta", className="botao-primario", n_clicks=0),
            html.Div(id="mensagem-criar-consulta", className="resultado-mini"),
        ],
        className="painel-details",
    )


def _painel_gerir_consulta():
    return html.Div(
        [
            html.H3("Gerir consulta existente"),
            html.P("Só é possível gerir consultas com estado Agendada.", className="texto-explicativo"),
            dcc.Dropdown(id="select-consulta-gerir", placeholder="Escolhe uma consulta agendada...", className="filtro-dropdown"),
            html.Div(
                [html.Button("Cancelar consulta", id="botao-cancelar-consulta", className="botao-secundario", n_clicks=0)],
                className="botoes-exportar",
            ),
            html.Details(
                [
                    html.Summary("Reagendar (nova data/hora/sala)", className="resumo-details"),
                    html.Div(
                        [
                            dcc.DatePickerSingle(
                                id="form-reagendar-data",
                                placeholder="Nova data",
                                display_format="DD/MM/YYYY",
                                month_format="MM/YYYY",
                                first_day_of_week=1,
                                min_date_allowed=datetime.date.today(),
                            ),
                            dcc.Dropdown(
                                id="form-reagendar-hora",
                                options=[{"label": h, "value": h} for h in HORARIOS_CONSULTA],
                                placeholder="Nova hora",
                                className="filtro-dropdown",
                            ),
                            dcc.Dropdown(id="form-reagendar-sala", options=[{"label": s, "value": s} for s in SALAS_CONSULTA], placeholder="Nova sala", className="filtro-dropdown"),
                        ],
                        className="grelha-formulario",
                    ),
                    html.Button("Confirmar novo horário", id="botao-reagendar-consulta", className="botao-primario", n_clicks=0),
                ],
                className="painel-details",
            ),
            html.Div(id="mensagem-gerir-consulta", className="resultado-mini"),
        ],
        className="cartao-secao",
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


def _pagina_consultas(perfil=None, profissional=None):
    # Enfermeiro e Médico só consultam a agenda (o Médico vê a sua própria,
    # filtrada — ver _filtrar_consultas); marcar/cancelar/reagendar é a
    # Receção (ou o Admin) que faz, tal como aconteceria com contas reais.
    mostrar_gestao_consulta = perfil in PERFIS_GESTAO_AGENDA
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
            *([_formulario_nova_consulta()] if mostrar_gestao_consulta else []),
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
            dcc.Store(id="consultas-atualizacao", data=0),
            html.Div(id="corpo-tabela-consultas"),
            *([_painel_gerir_consulta()] if mostrar_gestao_consulta else []),
        ]
    )


# --- Página: Faturação --------------------------------------------------------


def _formatar_euros(valor, casas_decimais=0):
    texto = f"{valor:,.{casas_decimais}f}"
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{texto} €"


COLUNAS_EXPORTACAO_FATURACAO = {
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


def _gerar_excel_faturacao():
    """Excel (.xlsx) a sério, não um CSV disfarçado — resolve de vez a
    ambiguidade da vírgula/ponto e vírgula (essa depende só da configuração
    regional do computador de quem abre o CSV, não do ficheiro em si), e de
    caminho já formata cabeçalhos e moeda."""
    fat = DADOS["faturacao"].merge(DADOS["utentes"][["id_utente", "nome", "tipo_cuidado"]], on="id_utente")
    fat = fat[list(COLUNAS_EXPORTACAO_FATURACAO.keys())].rename(columns=COLUNAS_EXPORTACAO_FATURACAO)
    colunas_euro = {c for c in fat.columns if "€" in c}

    livro = Workbook()
    folha = livro.active
    folha.title = "Faturação"
    folha.append(list(fat.columns))
    for celula in folha[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="0F7A6C")
    for _idx, linha in fat.iterrows():
        folha.append(list(linha))

    for i, coluna in enumerate(fat.columns, start=1):
        letra = get_column_letter(i)
        largura = max(len(coluna), int(fat[coluna].astype(str).map(len).max())) + 3
        folha.column_dimensions[letra].width = min(34, max(11, largura))
        if coluna in colunas_euro:
            for linha_celulas in folha.iter_rows(min_row=2, min_col=i, max_col=i):
                linha_celulas[0].number_format = "#,##0.00 €"
    folha.freeze_panes = "A2"

    buffer = io.BytesIO()
    livro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


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
            html.Button("Descarregar Excel", id="botao-excel-faturacao", className="botao-primario"),
            dcc.Download(id="descarregar-excel-faturacao"),
            html.Button("CSV", id="botao-csv-faturacao", className="botao-secundario"),
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
        style_cell={**ESTILO_CELULA_TABELA, "fontSize": "0.82rem"},
        style_header=ESTILO_CABECALHO_TABELA,
        style_data_conditional=_com_zebra([{"if": {"filter_query": "{erro_fatura} = true"}, "backgroundColor": CORES["risco_elevado_suave"]}]),
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


# --- Página: Profissionais (cadastro, CRUD) -----------------------------------

COLUNAS_COM_PROFISSIONAL = [
    ("consultas", "profissional"),
    ("diagnosticos", "profissional"),
    ("prescricoes", "profissional"),
    ("visitas", "registado_por"),
    ("exames", "profissional_pedido"),
    ("plano_cuidados", "profissional_responsavel"),
    ("historico", "profissional"),
]


def _stats_profissional(nome):
    n_consultas = int((DADOS["consultas"]["profissional"] == nome).sum())
    n_plano = int((DADOS["plano_cuidados"]["profissional_responsavel"] == nome).sum())
    return n_consultas, n_plano


def _profissional_tem_historico(nome):
    return any((DADOS[tabela][coluna] == nome).any() for tabela, coluna in COLUNAS_COM_PROFISSIONAL)


# --- Relatórios ----------------------------------------------------------------


def _estatisticas_atividade_profissional(nome, data_inicio=None, data_fim=None):
    """Agrega as consultas de um profissional (opcionalmente num período) —
    base tanto do relatório em PDF/Excel como do resumo mostrado na página."""
    df = DADOS["consultas"][DADOS["consultas"]["profissional"] == nome]
    if data_inicio:
        df = df[df["data_hora"] >= pd.Timestamp(data_inicio)]
    if data_fim:
        df = df[df["data_hora"] < pd.Timestamp(data_fim) + pd.Timedelta(days=1)]

    por_estado = df["estado"].value_counts().to_dict()
    realizadas = por_estado.get("Realizada", 0)
    faltas = por_estado.get("Falta", 0)
    taxa_comparencia = (realizadas / (realizadas + faltas) * 100) if (realizadas + faltas) else None

    return {
        "nome": nome,
        "total": len(df),
        "por_estado": por_estado,
        "taxa_comparencia": taxa_comparencia,
        "por_especialidade": df["especialidade"].value_counts().to_dict(),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
    }


def _opcoes_relatorio_consulta(perfil, profissional):
    """Lista de consultas para o relatório de consulta — um Médico só pode
    gerar relatório das suas próprias consultas (agenda própria), tal como
    já acontece na página de Consultas."""
    df = DADOS["consultas"]
    if perfil == "Médico" and profissional:
        df = df[df["profissional"] == profissional]
    df = df.merge(DADOS["utentes"][["id_utente", "nome"]], on="id_utente").sort_values("data_hora", ascending=False)
    return [
        {
            "label": f"{r['data_hora'].strftime('%d/%m/%Y %H:%M')} · {r['nome']} · {r['especialidade']} · {r['estado']}",
            "value": r["id_consulta"],
        }
        for _idx, r in df.iterrows()
    ]


def _corpo_relatorio_atividade(nome, data_inicio=None, data_fim=None):
    if not nome:
        return html.P("Escolhe um profissional para ver o relatório de atividade.", className="texto-explicativo")

    stats = _estatisticas_atividade_profissional(nome, data_inicio, data_fim)
    faltas = stats["por_estado"].get("Falta", 0)
    kpis = html.Div(
        [
            _cartao_kpi("Total de consultas", stats["total"]),
            _cartao_kpi("Realizadas", stats["por_estado"].get("Realizada", 0), tom="risco_baixo"),
            _cartao_kpi("Faltas", faltas, tom="risco_elevado" if faltas else "risco_baixo"),
            _cartao_kpi(
                "Taxa de comparência",
                f"{stats['taxa_comparencia']:.0f}%" if stats["taxa_comparencia"] is not None else "—",
            ),
        ],
        className="kpis-linha",
    )

    especialidades_ordenadas = sorted(stats["por_especialidade"].items(), key=lambda item: -item[1])
    if especialidades_ordenadas:
        tabela_especialidade = html.Table(
            [
                html.Thead(html.Tr([html.Th("Especialidade"), html.Th("Consultas")])),
                html.Tbody([html.Tr([html.Td(especialidade), html.Td(str(qtd))]) for especialidade, qtd in especialidades_ordenadas]),
            ],
            className="tabela-utentes",
        )
    else:
        tabela_especialidade = html.P("Sem consultas registadas no período.", className="texto-explicativo")

    return html.Div([kpis, tabela_especialidade])


def _tabela_profissionais():
    prof = DADOS["profissionais"].sort_values("nome")
    if prof.empty:
        return html.P("Sem profissionais cadastrados.", className="texto-explicativo")
    linhas = []
    for _idx, p in prof.iterrows():
        n_consultas, n_plano = _stats_profissional(p["nome"])
        linhas.append(
            html.Tr(
                [
                    html.Td(p["nome"]),
                    html.Td(p["categoria"]),
                    html.Td(p["especialidade"] or "—"),
                    html.Td(p["contacto"]),
                    html.Td(p["numero_cedula"]),
                    html.Td(p["data_admissao"]),
                    html.Td(html.Span(p["estado"], className=f"etiqueta-estado etiqueta-estado--{_slug(p['estado'])}")),
                    html.Td(str(n_consultas)),
                    html.Td(str(n_plano)),
                    html.Td(dcc.Link("Ver relatório", href=f"/relatorios?profissional={urllib.parse.quote(p['nome'])}", className="ligacao-voltar")),
                ]
            )
        )
    cabecalhos = ["Nome", "Categoria", "Especialidade", "Contacto", "Nº cédula", "Admissão", "Estado", "Consultas", "Plano de cuidados", ""]
    return html.Table(
        [html.Thead(html.Tr([html.Th(c) for c in cabecalhos])), html.Tbody(linhas)],
        className="tabela-utentes",
    )


def _formulario_novo_profissional():
    return html.Details(
        [
            html.Summary("+ Novo Profissional", className="resumo-details"),
            html.Div(
                [
                    dcc.Input(id="form-prof-nome", type="text", placeholder="Nome (ex.: Dr. João Silva)", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="form-prof-categoria",
                        options=[{"label": c, "value": c} for c in CATEGORIAS_PROFISSIONAL],
                        placeholder="Categoria",
                        className="filtro-dropdown",
                    ),
                    dcc.Dropdown(
                        id="form-prof-especialidade",
                        options=[{"label": e, "value": e} for e in ESPECIALIDADES],
                        placeholder="Especialidade (só Médico)",
                        className="filtro-dropdown",
                    ),
                    dcc.Input(id="form-prof-contacto", type="text", placeholder="Contacto (email ou telefone)", className="campo-pesquisa"),
                    dcc.Input(id="form-prof-cedula", type="text", placeholder="Nº de cédula profissional", className="campo-pesquisa"),
                    dcc.DatePickerSingle(
                        id="form-prof-admissao",
                        placeholder="Data de admissão",
                        display_format="DD/MM/YYYY",
                        month_format="MM/YYYY",
                        first_day_of_week=1,
                        max_date_allowed=datetime.date.today(),
                    ),
                ],
                className="grelha-formulario",
            ),
            html.Button("Adicionar profissional", id="botao-criar-profissional", className="botao-primario", n_clicks=0),
            html.Div(id="mensagem-criar-profissional", className="resultado-mini"),
        ],
        className="painel-details",
    )


def _painel_gerir_profissional():
    return html.Div(
        [
            html.H3("Gerir profissional"),
            dcc.Dropdown(id="select-profissional-gerir", placeholder="Escolhe um profissional...", className="filtro-dropdown"),
            html.Div(
                [
                    dcc.Input(id="form-prof-editar-contacto", type="text", placeholder="Novo contacto (deixa em branco para não alterar)", className="campo-pesquisa"),
                    dcc.Input(id="form-prof-editar-cedula", type="text", placeholder="Novo nº de cédula (deixa em branco para não alterar)", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="form-prof-editar-especialidade",
                        options=[{"label": e, "value": e} for e in ESPECIALIDADES],
                        placeholder="Nova especialidade (só Médico)",
                        className="filtro-dropdown",
                    ),
                ],
                className="grelha-formulario",
            ),
            html.Div(
                [
                    html.Button("Guardar alterações", id="botao-editar-profissional", className="botao-secundario", n_clicks=0),
                    html.Button("Alternar Ativo/Inativo", id="botao-alternar-estado-profissional", className="botao-secundario", n_clicks=0),
                    html.Button("Remover", id="botao-remover-profissional", className="botao-secundario", n_clicks=0),
                ],
                className="botoes-exportar",
            ),
            html.Div(id="mensagem-gerir-profissional", className="resultado-mini"),
        ],
        className="cartao-secao",
    )


def _pagina_profissionais():
    prof = DADOS["profissionais"]
    ativos = int((prof["estado"] == "Ativo").sum())
    inativos = int((prof["estado"] == "Inativo").sum())

    return html.Div(
        [
            html.H1("Profissionais"),
            html.P(
                "Cadastro da equipa — médicos (com especialidade, para as consultas) e a equipa de apoio "
                "(enfermagem, fisioterapia, nutrição, psicologia, serviço social, para o plano de cuidados).",
                className="texto-explicativo",
            ),
            html.Div(
                [
                    _cartao_kpi("Total", len(prof)),
                    _cartao_kpi("Ativos", ativos, tom="risco_baixo"),
                    _cartao_kpi("Inativos", inativos, tom="risco_moderado" if inativos else ""),
                ],
                className="kpis-linha",
            ),
            _formulario_novo_profissional(),
            dcc.Store(id="profissionais-atualizacao", data=0),
            html.Div(id="corpo-tabela-profissionais"),
            _painel_gerir_profissional(),
        ]
    )


def _pagina_relatorios(perfil=None, profissional=None, query_search=None):
    # A Receção não tem uma secção de "atividade profissional" (é um
    # relatório de gestão, não uma tarefa de front-desk) — vê só o
    # relatório de consulta, mais abaixo. Enfermeiro/Médico veem a sua
    # própria atividade; Admin escolhe qualquer profissional.
    mostrar_atividade = perfil != "Receção"

    if mostrar_atividade:
        if perfil in PERFIS_RELATORIO_QUALQUER_PROFISSIONAL:
            # Admin escolhe qualquer profissional — inclui o valor vindo do
            # atalho "Ver relatório" na página Profissionais (?profissional=...).
            profissional_pre = None
            if query_search:
                parametros = urllib.parse.parse_qs(query_search.lstrip("?"))
                valores = parametros.get("profissional")
                if valores:
                    profissional_pre = valores[0]
            opcoes_profissional = [{"label": n, "value": n} for n in DADOS["profissionais"].sort_values("nome")["nome"]]
            dropdown_profissional = dcc.Dropdown(
                id="select-relatorio-profissional",
                options=opcoes_profissional,
                value=profissional_pre,
                placeholder="Escolhe um profissional...",
                className="filtro-dropdown",
            )
        else:
            # Médico/Enfermeiro só veem a sua própria atividade — agenda
            # própria, tal como o resto do módulo de Consultas.
            dropdown_profissional = dcc.Dropdown(
                id="select-relatorio-profissional",
                options=[{"label": profissional, "value": profissional}] if profissional else [],
                value=profissional,
                disabled=True,
                className="filtro-dropdown",
            )

        secao_atividade = html.Div(
            [
                html.H2("Relatório de atividade profissional"),
                html.P(
                    "Número de consultas, taxa de comparência e distribuição por especialidade, num período à escolha.",
                    className="texto-explicativo",
                ),
                html.Div(
                    [
                        dropdown_profissional,
                        dcc.DatePickerSingle(
                            id="periodo-relatorio-inicio", placeholder="De", display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1
                        ),
                        dcc.DatePickerSingle(
                            id="periodo-relatorio-fim", placeholder="Até", display_format="DD/MM/YYYY", month_format="MM/YYYY", first_day_of_week=1
                        ),
                    ],
                    className="grelha-formulario",
                ),
                html.Div(id="corpo-relatorio-atividade"),
                html.Div(
                    [
                        html.Button("Descarregar PDF", id="botao-pdf-relatorio-atividade", className="botao-secundario", n_clicks=0),
                        html.Button("Descarregar Excel", id="botao-excel-relatorio-atividade", className="botao-secundario", n_clicks=0),
                    ],
                    className="botoes-exportar",
                ),
                dcc.Download(id="descarregar-pdf-relatorio-atividade"),
                dcc.Download(id="descarregar-excel-relatorio-atividade"),
                html.Div(id="mensagem-relatorio-atividade", className="resultado-mini"),
            ],
            className="cartao-secao",
        )
    else:
        secao_atividade = None

    secao_consulta = html.Div(
        [
            html.H2("Relatório de consulta"),
            html.P("Resumo de uma consulta específica, pronto a arquivar ou partilhar.", className="texto-explicativo"),
            dcc.Dropdown(
                id="select-relatorio-consulta",
                options=_opcoes_relatorio_consulta(perfil, profissional),
                placeholder="Escolhe uma consulta...",
                className="filtro-dropdown",
            ),
            html.Div(
                [
                    html.Button("Descarregar PDF", id="botao-pdf-relatorio-consulta", className="botao-secundario", n_clicks=0),
                    html.Button("Descarregar Excel", id="botao-excel-relatorio-consulta", className="botao-secundario", n_clicks=0),
                ],
                className="botoes-exportar",
            ),
            dcc.Download(id="descarregar-pdf-relatorio-consulta"),
            dcc.Download(id="descarregar-excel-relatorio-consulta"),
            html.Div(id="mensagem-relatorio-consulta", className="resultado-mini"),
        ],
        className="cartao-secao",
    )

    return html.Div(
        [
            html.H1("Relatórios"),
            html.P(
                "Documentação e exportação — atividade de um profissional (Médico/Enfermeiro veem só a sua, "
                "Admin escolhe qualquer um) ou o resumo de uma consulta específica.",
                className="texto-explicativo",
            ),
            *([secao_atividade] if mostrar_atividade else []),
            secao_consulta,
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
            dcc.Store(id="onboarding-dispensada", storage_type="local"),
            html.Div(id="barra-lateral-app"),
            html.Div(html.Div(id="conteudo-pagina", className="pagina"), className="area-principal"),
        ],
        className="app-raiz",
    )


app.layout = _construir_layout


# --- Callbacks: sessão (login/logout, mock — sem autenticação real) ----------


@app.callback(
    Output("perfil-provisorio-login", "data", allow_duplicate=True),
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input({"type": "botao-login-perfil", "perfil": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _escolher_perfil_login(cliques):
    if not ctx.triggered_id or not any(cliques):
        return dash.no_update, dash.no_update, dash.no_update
    perfil = ctx.triggered_id["perfil"]
    if perfil not in PERFIS_COM_PROFISSIONAL:
        # Receção/Admin não têm identidade de profissional — entram logo.
        return dash.no_update, {"perfil": perfil, "profissional": None}, "/"
    # Médico/Enfermeiro: fica à espera da escolha do profissional (2º passo).
    return perfil, dash.no_update, dash.no_update


@app.callback(
    Output("perfil-provisorio-login", "data", allow_duplicate=True),
    Input("botao-voltar-login", "n_clicks"),
    prevent_initial_call=True,
)
def _voltar_login(n_clicks):
    if not n_clicks:
        return dash.no_update
    return None


@app.callback(
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input({"type": "botao-login-profissional", "nome": ALL}, "n_clicks"),
    State("perfil-provisorio-login", "data"),
    prevent_initial_call=True,
)
def _escolher_profissional_login(cliques, perfil_provisorio):
    if not ctx.triggered_id or not any(cliques) or not perfil_provisorio:
        return dash.no_update, dash.no_update
    return {"perfil": perfil_provisorio, "profissional": ctx.triggered_id["nome"]}, "/"


@app.callback(Output("corpo-login", "children"), Input("perfil-provisorio-login", "data"))
def _renderizar_corpo_login(perfil_provisorio):
    if perfil_provisorio:
        return _corpo_login_escolha_profissional(perfil_provisorio)
    return _corpo_login_escolha_perfil()


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


@app.callback(
    Output("onboarding-dispensada", "data"),
    Input("botao-dispensar-orientacao", "n_clicks"),
    State("perfil-sessao", "data"),
    State("onboarding-dispensada", "data"),
    prevent_initial_call=True,
)
def _dispensar_orientacao(n_clicks, sessao, dispensada):
    if not n_clicks:
        return dash.no_update
    perfil, _profissional = _dados_sessao(sessao)
    if not perfil:
        return dash.no_update
    atualizado = dict(dispensada or {})
    atualizado[perfil] = True
    return atualizado


# --- Callbacks: navegação ----------------------------------------------------


@app.callback(Output("barra-lateral-app", "children"), Input("url", "pathname"), Input("perfil-sessao", "data"))
def _atualizar_barra_lateral(caminho, sessao):
    perfil, profissional = _dados_sessao(sessao)
    if not perfil:
        return None
    return _barra_lateral(caminho or "/", perfil, profissional)


@app.callback(
    Output("conteudo-pagina", "children"),
    Input("url", "pathname"),
    Input("url", "search"),
    Input("perfil-sessao", "data"),
    Input("onboarding-dispensada", "data"),
)
def _rotear_pagina(caminho, query_search, sessao, onboarding_dispensada):
    perfil, profissional = _dados_sessao(sessao)
    caminho = caminho or "/"
    if caminho != "/login" and not perfil:
        return _pagina_login()
    if caminho == "/login":
        return _pagina_login()
    if caminho == "/":
        return _pagina_visao_geral(perfil, onboarding_dispensada)
    if caminho == "/utentes":
        return _pagina_utentes()
    if caminho.startswith("/utentes/"):
        id_utente = caminho.split("/utentes/")[-1]
        return _pagina_ficha_utente(id_utente, perfil, profissional)
    if caminho == "/ocupacao":
        return _pagina_ocupacao()
    if caminho == "/consultas":
        return _pagina_consultas(perfil, profissional)
    if caminho == "/relatorios":
        return _pagina_relatorios(perfil, profissional, query_search)
    if caminho == "/faturacao":
        return _pagina_faturacao()
    if caminho == "/profissionais":
        if perfil != "Admin":
            # Gestão do cadastro de profissionais é reservada ao Admin.
            return html.Div(
                [
                    html.H2("Acesso não disponível"),
                    html.P("Este perfil não tem acesso à gestão de profissionais.", className="texto-explicativo"),
                    dcc.Link("Voltar ao início", href="/", className="ligacao-voltar"),
                ]
            )
        return _pagina_profissionais()
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
    Input("consultas-atualizacao", "data"),
    Input("perfil-sessao", "data"),
)
def _filtrar_consultas(texto_pesquisa, especialidade, estado, modo="lista", semana_inicio_iso=None, _versao=None, sessao=None):
    df = DADOS["consultas"]
    perfil, profissional = _dados_sessao(sessao)
    if perfil == "Médico" and profissional:
        # Agenda própria: um médico só vê (e só gere) as suas consultas.
        df = df[df["profissional"] == profissional]
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


# --- Callbacks: agendamento — criar, cancelar, reagendar consulta ------------


@app.callback(Output("form-consulta-profissional", "options"), Input("form-consulta-especialidade", "value"))
def _profissionais_disponiveis_para_especialidade(especialidade):
    if not especialidade:
        return []
    prof = DADOS["profissionais"]
    disponiveis = prof[(prof["categoria"] == "Médico") & (prof["especialidade"] == especialidade) & (prof["estado"] == "Ativo")]
    return [{"label": n, "value": n} for n in disponiveis["nome"]]


@app.callback(
    Output("mensagem-criar-consulta", "children"),
    Output("consultas-atualizacao", "data", allow_duplicate=True),
    Input("botao-criar-consulta", "n_clicks"),
    State("form-consulta-utente", "value"),
    State("form-consulta-especialidade", "value"),
    State("form-consulta-profissional", "value"),
    State("form-consulta-data", "date"),
    State("form-consulta-hora", "value"),
    State("form-consulta-sala", "value"),
    State("consultas-atualizacao", "data"),
    prevent_initial_call=True,
)
def _criar_consulta(n_clicks, id_utente, especialidade, profissional, data, hora, sala, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not all([id_utente, especialidade, profissional, data, hora, sala]):
        return html.Div("Preenche todos os campos antes de marcar a consulta.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update

    data_hora = pd.Timestamp(f"{data} {hora}")
    if _conflito_consulta(profissional, sala, data_hora):
        return (
            html.Div("Já existe uma consulta marcada para este profissional ou esta sala a essa hora.", className="resultado-inline resultado-inline--risco_elevado"),
            dash.no_update,
        )

    nova_linha = pd.DataFrame(
        [
            {
                "id_consulta": _proximo_id_consulta(),
                "id_utente": id_utente,
                "data_hora": data_hora,
                "especialidade": especialidade,
                "profissional": profissional,
                "sala": sala,
                "estado": "Agendada",
            }
        ]
    )
    DADOS["consultas"] = pd.concat([DADOS["consultas"], nova_linha], ignore_index=True)
    _registar_historico(id_utente, profissional, "Agendou consulta")

    mensagem = f"Consulta marcada para {_nome_utente(id_utente)} em {data_hora.strftime('%d/%m/%Y %H:%M')}."
    return html.Div(mensagem, className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("select-consulta-gerir", "options"),
    Input("consultas-atualizacao", "data"),
    Input("perfil-sessao", "data"),
)
def _opcoes_consultas_para_gerir(_versao, sessao=None):
    perfil, profissional = _dados_sessao(sessao)
    agendadas = DADOS["consultas"][DADOS["consultas"]["estado"] == "Agendada"]
    if perfil == "Médico" and profissional:
        agendadas = agendadas[agendadas["profissional"] == profissional]
    agendadas = agendadas.merge(DADOS["utentes"][["id_utente", "nome"]], on="id_utente").sort_values("data_hora")
    return [
        {"label": f"{r['data_hora'].strftime('%d/%m %H:%M')} · {r['nome']} · {r['especialidade']}", "value": r["id_consulta"]}
        for _idx, r in agendadas.iterrows()
    ]


@app.callback(
    Output("mensagem-gerir-consulta", "children"),
    Output("consultas-atualizacao", "data", allow_duplicate=True),
    Input("botao-cancelar-consulta", "n_clicks"),
    State("select-consulta-gerir", "value"),
    State("consultas-atualizacao", "data"),
    prevent_initial_call=True,
)
def _cancelar_consulta(n_clicks, id_consulta, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_consulta:
        return html.Div("Escolhe primeiro uma consulta.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    linha = DADOS["consultas"][DADOS["consultas"]["id_consulta"] == id_consulta]
    if linha.empty:
        return html.Div("Consulta não encontrada — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta, "estado"] = "Cancelada"
    _registar_historico(linha.iloc[0]["id_utente"], linha.iloc[0]["profissional"], "Alterou estado da consulta")
    return html.Div("Consulta cancelada.", className="resultado-inline resultado-inline--risco_moderado"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-consulta", "children", allow_duplicate=True),
    Output("consultas-atualizacao", "data", allow_duplicate=True),
    Input("botao-reagendar-consulta", "n_clicks"),
    State("select-consulta-gerir", "value"),
    State("form-reagendar-data", "date"),
    State("form-reagendar-hora", "value"),
    State("form-reagendar-sala", "value"),
    State("consultas-atualizacao", "data"),
    prevent_initial_call=True,
)
def _reagendar_consulta(n_clicks, id_consulta, data, hora, sala, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not all([id_consulta, data, hora, sala]):
        return html.Div("Escolhe a consulta e preenche a nova data, hora e sala.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    linha = DADOS["consultas"][DADOS["consultas"]["id_consulta"] == id_consulta]
    if linha.empty:
        return html.Div("Consulta não encontrada — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update

    profissional = linha.iloc[0]["profissional"]
    nova_data_hora = pd.Timestamp(f"{data} {hora}")
    if _conflito_consulta(profissional, sala, nova_data_hora, excluir_id=id_consulta):
        return (
            html.Div("Já existe uma consulta marcada para este profissional ou esta sala a essa hora.", className="resultado-inline resultado-inline--risco_elevado"),
            dash.no_update,
        )

    DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta, ["data_hora", "sala"]] = [nova_data_hora, sala]
    _registar_historico(linha.iloc[0]["id_utente"], profissional, "Alterou estado da consulta")
    mensagem = f"Consulta reagendada para {nova_data_hora.strftime('%d/%m/%Y %H:%M')}."
    return html.Div(mensagem, className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


# --- Callbacks: prescrições e receita em PDF (só Médico) ---------------------


@app.callback(
    Output("corpo-prescricoes", "children"),
    Input("prescricoes-atualizacao", "data"),
    State("utente-atual-id", "data"),
    State("perfil-sessao", "data"),
)
def _renderizar_prescricoes(_versao, id_utente, sessao):
    if not id_utente:
        return dash.no_update
    perfil, profissional = _dados_sessao(sessao)
    return _corpo_prescricoes(id_utente, perfil, profissional)


@app.callback(
    Output("mensagem-criar-prescricao", "children"),
    Output("prescricoes-atualizacao", "data", allow_duplicate=True),
    Input("botao-criar-prescricao", "n_clicks"),
    State("utente-atual-id", "data"),
    State("form-prescricao-medicamento", "value"),
    State("form-prescricao-posologia", "value"),
    State("form-prescricao-duracao", "value"),
    State("perfil-sessao", "data"),
    State("prescricoes-atualizacao", "data"),
    prevent_initial_call=True,
)
def _criar_prescricao(n_clicks, id_utente, medicamento, posologia, duracao, sessao, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    perfil, profissional = _dados_sessao(sessao)
    if perfil != "Médico" or not profissional:
        return html.Div("Só o Médico autenticado pode registar uma prescrição.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    if not id_utente or not all([medicamento, posologia]):
        return html.Div("Preenche pelo menos o medicamento e a posologia.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update

    nova_linha = pd.DataFrame(
        [
            {
                "id_prescricao": _proximo_id_prescricao(),
                "id_utente": id_utente,
                "data": pd.Timestamp.now().date().isoformat(),
                "profissional": profissional,
                "medicamento": medicamento,
                "posologia": posologia,
                "duracao": duracao or "",
            }
        ]
    )
    DADOS["prescricoes"] = pd.concat([DADOS["prescricoes"], nova_linha], ignore_index=True)
    _registar_historico(id_utente, profissional, "Registou prescrição")

    return html.Div(f"Prescrição de {medicamento} registada.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("descarregar-receita-pdf", "data"),
    Output("mensagem-gerar-receita", "children"),
    Input("botao-gerar-receita", "n_clicks"),
    State("select-prescricao-receita", "value"),
    prevent_initial_call=True,
)
def _descarregar_receita_pdf(n_clicks, id_prescricao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_prescricao:
        return dash.no_update, html.Div("Escolhe primeiro uma prescrição.", className="resultado-inline resultado-inline--risco_moderado")
    pdf_bytes = _gerar_pdf_receita(id_prescricao)
    if pdf_bytes is None:
        return dash.no_update, html.Div("Prescrição não encontrada — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
    return dcc.send_bytes(lambda b: b.write(pdf_bytes), f"receita_{id_prescricao}.pdf"), ""


# --- Callbacks: relatórios ------------------------------------------------------


@app.callback(
    Output("corpo-relatorio-atividade", "children"),
    Input("select-relatorio-profissional", "value"),
    Input("periodo-relatorio-inicio", "date"),
    Input("periodo-relatorio-fim", "date"),
)
def _atualizar_corpo_relatorio_atividade(nome, data_inicio, data_fim):
    return _corpo_relatorio_atividade(nome, data_inicio, data_fim)


@app.callback(
    Output("descarregar-pdf-relatorio-atividade", "data"),
    Output("mensagem-relatorio-atividade", "children"),
    Input("botao-pdf-relatorio-atividade", "n_clicks"),
    State("select-relatorio-profissional", "value"),
    State("periodo-relatorio-inicio", "date"),
    State("periodo-relatorio-fim", "date"),
    prevent_initial_call=True,
)
def _descarregar_pdf_relatorio_atividade(n_clicks, nome, data_inicio, data_fim):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not nome:
        return dash.no_update, html.Div("Escolhe um profissional primeiro.", className="resultado-inline resultado-inline--risco_moderado")
    pdf_bytes = _gerar_pdf_relatorio_atividade(nome, data_inicio, data_fim)
    return dcc.send_bytes(lambda b: b.write(pdf_bytes), f"relatorio_atividade_{_slug(nome)}.pdf"), ""


@app.callback(
    Output("descarregar-excel-relatorio-atividade", "data"),
    Output("mensagem-relatorio-atividade", "children", allow_duplicate=True),
    Input("botao-excel-relatorio-atividade", "n_clicks"),
    State("select-relatorio-profissional", "value"),
    State("periodo-relatorio-inicio", "date"),
    State("periodo-relatorio-fim", "date"),
    prevent_initial_call=True,
)
def _descarregar_excel_relatorio_atividade(n_clicks, nome, data_inicio, data_fim):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not nome:
        return dash.no_update, html.Div("Escolhe um profissional primeiro.", className="resultado-inline resultado-inline--risco_moderado")
    conteudo = _gerar_excel_relatorio_atividade(nome, data_inicio, data_fim)
    return dcc.send_bytes(lambda b: b.write(conteudo), f"relatorio_atividade_{_slug(nome)}.xlsx"), ""


@app.callback(
    Output("descarregar-pdf-relatorio-consulta", "data"),
    Output("mensagem-relatorio-consulta", "children"),
    Input("botao-pdf-relatorio-consulta", "n_clicks"),
    State("select-relatorio-consulta", "value"),
    prevent_initial_call=True,
)
def _descarregar_pdf_relatorio_consulta(n_clicks, id_consulta):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_consulta:
        return dash.no_update, html.Div("Escolhe uma consulta primeiro.", className="resultado-inline resultado-inline--risco_moderado")
    pdf_bytes = _gerar_pdf_relatorio_consulta(id_consulta)
    if pdf_bytes is None:
        return dash.no_update, html.Div("Consulta não encontrada — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
    return dcc.send_bytes(lambda b: b.write(pdf_bytes), f"relatorio_{id_consulta}.pdf"), ""


@app.callback(
    Output("descarregar-excel-relatorio-consulta", "data"),
    Output("mensagem-relatorio-consulta", "children", allow_duplicate=True),
    Input("botao-excel-relatorio-consulta", "n_clicks"),
    State("select-relatorio-consulta", "value"),
    prevent_initial_call=True,
)
def _descarregar_excel_relatorio_consulta(n_clicks, id_consulta):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_consulta:
        return dash.no_update, html.Div("Escolhe uma consulta primeiro.", className="resultado-inline resultado-inline--risco_moderado")
    conteudo = _gerar_excel_relatorio_consulta(id_consulta)
    if conteudo is None:
        return dash.no_update, html.Div("Consulta não encontrada — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
    return dcc.send_bytes(lambda b: b.write(conteudo), f"relatorio_{id_consulta}.xlsx"), ""


# --- Callbacks: profissionais — CRUD ------------------------------------------


@app.callback(Output("corpo-tabela-profissionais", "children"), Input("profissionais-atualizacao", "data"))
def _atualizar_tabela_profissionais(_versao):
    return _tabela_profissionais()


@app.callback(Output("select-profissional-gerir", "options"), Input("profissionais-atualizacao", "data"))
def _opcoes_profissionais_para_gerir(_versao):
    prof = DADOS["profissionais"].sort_values("nome")
    return [{"label": f"{n} ({c})", "value": n} for n, c in zip(prof["nome"], prof["categoria"], strict=True)]


@app.callback(
    Output("mensagem-criar-profissional", "children"),
    Output("profissionais-atualizacao", "data", allow_duplicate=True),
    Input("botao-criar-profissional", "n_clicks"),
    State("form-prof-nome", "value"),
    State("form-prof-categoria", "value"),
    State("form-prof-especialidade", "value"),
    State("form-prof-contacto", "value"),
    State("form-prof-cedula", "value"),
    State("form-prof-admissao", "date"),
    State("profissionais-atualizacao", "data"),
    prevent_initial_call=True,
)
def _criar_profissional(n_clicks, nome, categoria, especialidade, contacto, cedula, admissao, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    nome = (nome or "").strip()
    if not nome or not categoria:
        return html.Div("Preenche pelo menos o nome e a categoria.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    if categoria == "Médico" and not especialidade:
        return (
            html.Div("Escolhe a especialidade — é obrigatória para a categoria Médico.", className="resultado-inline resultado-inline--risco_moderado"),
            dash.no_update,
        )
    if nome in DADOS["profissionais"]["nome"].values:
        return html.Div("Já existe um profissional com este nome.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update

    novo_id = f"P{len(DADOS['profissionais']) + 1:04d}"
    nova_linha = pd.DataFrame(
        [
            {
                "id_profissional": novo_id,
                "nome": nome,
                "categoria": categoria,
                "especialidade": especialidade if categoria == "Médico" else "",
                "contacto": contacto or "—",
                "numero_cedula": cedula or "—",
                "data_admissao": admissao or datetime.date.today().isoformat(),
                "estado": "Ativo",
            }
        ]
    )
    DADOS["profissionais"] = pd.concat([DADOS["profissionais"], nova_linha], ignore_index=True)
    return html.Div(f"Profissional {nome} adicionado.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-profissional", "children"),
    Output("profissionais-atualizacao", "data", allow_duplicate=True),
    Input("botao-editar-profissional", "n_clicks"),
    State("select-profissional-gerir", "value"),
    State("form-prof-editar-contacto", "value"),
    State("form-prof-editar-cedula", "value"),
    State("form-prof-editar-especialidade", "value"),
    State("profissionais-atualizacao", "data"),
    prevent_initial_call=True,
)
def _editar_profissional(n_clicks, nome, contacto, cedula, especialidade, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not nome:
        return html.Div("Escolhe primeiro um profissional.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    mascara = DADOS["profissionais"]["nome"] == nome
    if not mascara.any():
        return html.Div("Profissional não encontrado — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    if not any([contacto, cedula, especialidade]):
        return html.Div("Preenche pelo menos um campo para atualizar.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update

    if contacto:
        DADOS["profissionais"].loc[mascara, "contacto"] = contacto
    if cedula:
        DADOS["profissionais"].loc[mascara, "numero_cedula"] = cedula
    categoria = DADOS["profissionais"].loc[mascara, "categoria"].iloc[0]
    if especialidade and categoria == "Médico":
        DADOS["profissionais"].loc[mascara, "especialidade"] = especialidade
    elif especialidade:
        return (
            html.Div(f"{nome} não é Médico — a especialidade só se aplica a essa categoria; os outros campos foram guardados.", className="resultado-inline resultado-inline--risco_moderado"),
            (versao or 0) + 1,
        )
    return html.Div(f"Dados de {nome} atualizados.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-profissional", "children", allow_duplicate=True),
    Output("profissionais-atualizacao", "data", allow_duplicate=True),
    Input("botao-alternar-estado-profissional", "n_clicks"),
    State("select-profissional-gerir", "value"),
    State("profissionais-atualizacao", "data"),
    prevent_initial_call=True,
)
def _alternar_estado_profissional(n_clicks, nome, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not nome:
        return html.Div("Escolhe primeiro um profissional.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    mascara = DADOS["profissionais"]["nome"] == nome
    if not mascara.any():
        return html.Div("Profissional não encontrado — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    atual = DADOS["profissionais"].loc[mascara, "estado"].iloc[0]
    novo_estado = "Inativo" if atual == "Ativo" else "Ativo"
    DADOS["profissionais"].loc[mascara, "estado"] = novo_estado
    return html.Div(f"{nome} passou a {novo_estado}.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-profissional", "children", allow_duplicate=True),
    Output("profissionais-atualizacao", "data", allow_duplicate=True),
    Input("botao-remover-profissional", "n_clicks"),
    State("select-profissional-gerir", "value"),
    State("profissionais-atualizacao", "data"),
    prevent_initial_call=True,
)
def _remover_profissional(n_clicks, nome, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not nome:
        return html.Div("Escolhe primeiro um profissional.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    if _profissional_tem_historico(nome):
        mensagem = (
            f"{nome} tem consultas, plano de cuidados ou outro histórico associado — não pode ser removido "
            "para não partir esses registos. Marca como Inativo em vez de remover."
        )
        return html.Div(mensagem, className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    if nome not in DADOS["profissionais"]["nome"].values:
        return html.Div("Profissional não encontrado — a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    DADOS["profissionais"] = DADOS["profissionais"][DADOS["profissionais"]["nome"] != nome].reset_index(drop=True)
    return html.Div(f"{nome} removido.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


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
    fat = fat[list(COLUNAS_EXPORTACAO_FATURACAO.keys())].rename(columns=COLUNAS_EXPORTACAO_FATURACAO)
    # sep=";" + decimal="," + encoding="utf-8-sig": o Excel em português usa
    # a vírgula como separador decimal, por isso precisa de ";" a separar
    # colunas (com sep="," o ficheiro abria tudo numa única coluna) E de ","
    # nos números com casas decimais (com decimal="." — o padrão do pandas —
    # o Excel em PT lê "721.4" como texto, não como número, porque não
    # reconhece o ponto como separador decimal). O "utf-8-sig" garante que os
    # acentos (é, ç, ã...) aparecem corretos. O Excel (.xlsx) acima não tem
    # nenhuma destas ambiguidades — é o formato recomendado; este CSV fica
    # como alternativa para quem precisar de importar noutra ferramenta.
    return dcc.send_data_frame(fat.to_csv, "faturacao.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")


@app.callback(
    Output("descarregar-excel-faturacao", "data"),
    Input("botao-excel-faturacao", "n_clicks"),
    prevent_initial_call=True,
)
def _descarregar_excel_faturacao(n_clicks):
    if not n_clicks:
        return dash.no_update
    conteudo = _gerar_excel_faturacao()
    return dcc.send_bytes(lambda b: b.write(conteudo), "faturacao.xlsx")


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


# --- Receita em PDF (Médico) --------------------------------------------------


def _gerar_pdf_receita(id_prescricao):
    """Gera uma receita médica em PDF a partir de uma prescrição registada.
    Só é chamada para prescrições que pertencem ao médico autenticado (ver
    filtro em _corpo_prescricoes / _descarregar_receita_pdf)."""
    linha = DADOS["prescricoes"].loc[DADOS["prescricoes"]["id_prescricao"] == id_prescricao]
    if linha.empty:
        return None
    p = linha.iloc[0]
    utente = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == p["id_utente"]].iloc[0]
    prof = DADOS["profissionais"].loc[DADOS["profissionais"]["nome"] == p["profissional"]]
    especialidade = prof.iloc[0]["especialidade"] if len(prof) and prof.iloc[0]["especialidade"] else "Medicina Geral"
    numero_cedula = prof.iloc[0]["numero_cedula"] if len(prof) else "—"

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    margem_esquerda = 20 * mm
    posicao_y = altura - 20 * mm

    def escrever(texto, tamanho=10, negrito=False, espaco=6 * mm, centrado=False):
        nonlocal posicao_y
        c.setFont("Helvetica-Bold" if negrito else "Helvetica", tamanho)
        if centrado:
            c.drawCentredString(largura / 2, posicao_y, texto)
        else:
            c.drawString(margem_esquerda, posicao_y, texto)
        posicao_y -= espaco

    escrever("Receita Médica", 18, negrito=True, espaco=12 * mm, centrado=True)
    escrever(f"{p['profissional']} · {especialidade}", 11, negrito=True)
    escrever(f"Cédula profissional: {numero_cedula}", 9, espaco=10 * mm)

    escrever(f"Utente: {utente['nome']}", 11, negrito=True)
    escrever(
        f"{utente['genero']} · {_idade_utente(utente['data_nascimento'])} anos · Processo {utente['processo']}",
        9,
        espaco=12 * mm,
    )

    escrever("Prescrição", 12, negrito=True)
    escrever(p["medicamento"], 11, espaco=6 * mm)
    escrever(f"Posologia: {p['posologia']}", 10)
    if p.get("duracao"):
        escrever(f"Duração do tratamento: {p['duracao']}", 10)
    posicao_y -= 14 * mm

    escrever(f"Data de emissão: {p['data']}", 10, espaco=18 * mm)
    c.line(margem_esquerda, posicao_y, margem_esquerda + 70 * mm, posicao_y)
    posicao_y -= 5 * mm
    escrever("Assinatura e carimbo", 8)

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        margem_esquerda, 15 * mm,
        "Documento gerado automaticamente — demonstração técnica de portfólio, dados sintéticos, não usar com pacientes reais.",
    )

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# --- Relatório de atividade profissional e relatório de consulta (PDF/Excel) --


def _gerar_pdf_relatorio_atividade(nome, data_inicio=None, data_fim=None):
    stats = _estatisticas_atividade_profissional(nome, data_inicio, data_fim)
    prof = DADOS["profissionais"].loc[DADOS["profissionais"]["nome"] == nome]
    categoria = prof.iloc[0]["categoria"] if len(prof) else ""

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

    escrever("Relatório de Atividade Profissional", 16, negrito=True, espaco=10 * mm)
    escrever(f"{nome}" + (f" · {categoria}" if categoria else ""), 12, negrito=True)
    escrever(f"Período: {data_inicio or 'início dos registos'} a {data_fim or 'hoje'}", 10, espaco=10 * mm)

    escrever("Resumo", 12, negrito=True)
    escrever(f"Total de consultas: {stats['total']}", 10)
    for estado_nome, qtd in stats["por_estado"].items():
        escrever(f"- {estado_nome}: {qtd}", 9, espaco=5 * mm)
    taxa_texto = f"{stats['taxa_comparencia']:.0f}%" if stats["taxa_comparencia"] is not None else "sem dados suficientes"
    escrever(f"Taxa de comparência: {taxa_texto}", 10, espaco=10 * mm)

    escrever("Consultas por especialidade", 12, negrito=True)
    especialidades_ordenadas = sorted(stats["por_especialidade"].items(), key=lambda item: -item[1])
    if especialidades_ordenadas:
        for especialidade, qtd in especialidades_ordenadas:
            escrever(f"- {especialidade}: {qtd}", 9, espaco=5 * mm)
    else:
        escrever("Sem consultas registadas no período.", 10)

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        margem_esquerda, 15 * mm,
        "Documento gerado automaticamente — demonstração técnica de portfólio, dados sintéticos, não usar com pacientes reais.",
    )
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _gerar_excel_relatorio_atividade(nome, data_inicio=None, data_fim=None):
    stats = _estatisticas_atividade_profissional(nome, data_inicio, data_fim)

    livro = Workbook()
    folha_resumo = livro.active
    folha_resumo.title = "Resumo"
    folha_resumo.append(["Métrica", "Valor"])
    for celula in folha_resumo[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="0F7A6C")
    folha_resumo.append(["Profissional", nome])
    folha_resumo.append(["Período", f"{data_inicio or 'início dos registos'} a {data_fim or 'hoje'}"])
    folha_resumo.append(["Total de consultas", stats["total"]])
    for estado_nome, qtd in stats["por_estado"].items():
        folha_resumo.append([estado_nome, qtd])
    taxa_texto = f"{stats['taxa_comparencia']:.0f}%" if stats["taxa_comparencia"] is not None else "—"
    folha_resumo.append(["Taxa de comparência", taxa_texto])
    folha_resumo.column_dimensions["A"].width = 24
    folha_resumo.column_dimensions["B"].width = 30

    folha_especialidade = livro.create_sheet("Por especialidade")
    folha_especialidade.append(["Especialidade", "Consultas"])
    for celula in folha_especialidade[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="0F7A6C")
    for especialidade, qtd in sorted(stats["por_especialidade"].items(), key=lambda item: -item[1]):
        folha_especialidade.append([especialidade, qtd])
    folha_especialidade.column_dimensions["A"].width = 22
    folha_especialidade.column_dimensions["B"].width = 14

    buffer = io.BytesIO()
    livro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def _gerar_pdf_relatorio_consulta(id_consulta):
    linha = DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta]
    if linha.empty:
        return None
    consulta = linha.iloc[0]
    utente = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == consulta["id_utente"]].iloc[0]

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4)
    _largura, altura = A4
    margem_esquerda = 20 * mm
    posicao_y = altura - 20 * mm

    def escrever(texto, tamanho=10, negrito=False, espaco=6 * mm):
        nonlocal posicao_y
        c.setFont("Helvetica-Bold" if negrito else "Helvetica", tamanho)
        c.drawString(margem_esquerda, posicao_y, texto)
        posicao_y -= espaco

    escrever("Relatório de Consulta", 16, negrito=True, espaco=10 * mm)
    escrever(f"Utente: {utente['nome']}", 11, negrito=True)
    escrever(
        f"{utente['genero']} · {_idade_utente(utente['data_nascimento'])} anos · Processo {utente['processo']}",
        9,
        espaco=10 * mm,
    )

    escrever(f"Data/Hora: {consulta['data_hora'].strftime('%d/%m/%Y %H:%M')}", 10)
    escrever(f"Especialidade: {consulta['especialidade']}", 10)
    escrever(f"Profissional: {consulta['profissional']}", 10)
    escrever(f"Sala: {consulta['sala']}", 10)
    escrever(f"Estado: {consulta['estado']}", 10, espaco=10 * mm)

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        margem_esquerda, 15 * mm,
        "Documento gerado automaticamente — demonstração técnica de portfólio, dados sintéticos, não usar com pacientes reais.",
    )
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _gerar_excel_relatorio_consulta(id_consulta):
    linha = DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta]
    if linha.empty:
        return None
    consulta = linha.iloc[0]
    utente = DADOS["utentes"].loc[DADOS["utentes"]["id_utente"] == consulta["id_utente"]].iloc[0]

    livro = Workbook()
    folha = livro.active
    folha.title = "Consulta"
    folha.append(["Campo", "Valor"])
    for celula in folha[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="0F7A6C")
    folha.append(["Utente", utente["nome"]])
    folha.append(["Processo", utente["processo"]])
    folha.append(["Data/Hora", consulta["data_hora"].strftime("%d/%m/%Y %H:%M")])
    folha.append(["Especialidade", consulta["especialidade"]])
    folha.append(["Profissional", consulta["profissional"]])
    folha.append(["Sala", consulta["sala"]])
    folha.append(["Estado", consulta["estado"]])
    folha.column_dimensions["A"].width = 18
    folha.column_dimensions["B"].width = 30

    buffer = io.BytesIO()
    livro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8051)
