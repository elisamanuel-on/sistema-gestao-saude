"""Camada de dados: carregamento dos CSV/modelos treinados no arranque, e as
constantes + funções auxiliares partilhadas por todo o resto da aplicação
(páginas, exportações em PDF/Excel, callbacks). Nada de Dash aqui (sem
html./dcc.) e nenhum @app.callback — só dados e lógica pura, para poder ser
importado por qualquer outro módulo sem risco de import circular."""

import datetime
import json
import logging
import pathlib
import random
import unicodedata

import joblib
import pandas as pd

from scripts.treinar_modelo_cardio import COLUNAS_CARDIO

logger = logging.getLogger(__name__)

PASTA_DADOS = pathlib.Path("dados")


PASTA_MODELO = pathlib.Path("modelo")


ESTADOS_UTENTE = ["Internado", "Em acompanhamento", "Alta", "Em espera"]


ESTADOS_VALIDOS_POR_TIPO = {
    "UCC": {"Internado", "Alta", "Em espera"},
    "ERPI": {"Internado", "Alta", "Em espera"},
    "SAD": {"Em acompanhamento", "Alta", "Em espera"},
    "Clínica/Hospital": {"Em acompanhamento", "Alta", "Em espera"},
}


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
    dados["faturacao"]["seguradora"] = dados["faturacao"]["seguradora"].fillna("N/D")
    dados["faturacao"]["numero_apolice"] = dados["faturacao"]["numero_apolice"].fillna("N/D")
    dados["historico"] = pd.read_csv(PASTA_DADOS / "historico.csv", parse_dates=["data_hora"])
    dados["profissionais"] = pd.read_csv(PASTA_DADOS / "profissionais.csv")
    dados["profissionais"]["especialidade"] = dados["profissionais"]["especialidade"].fillna("")
    dados["profissionais"]["contacto"] = dados["profissionais"]["contacto"].fillna("N/D")
    dados["profissionais"]["numero_cedula"] = dados["profissionais"]["numero_cedula"].fillna("N/D")
    dados["altas"] = pd.read_csv(PASTA_DADOS / "altas.csv")
    return dados


DADOS = _carregar_todos_os_dados()
logger.info(
    "Dados carregados: %d utentes, %d consultas, %d profissionais, %d faturas",
    len(DADOS["utentes"]), len(DADOS["consultas"]), len(DADOS["profissionais"]), len(DADOS["faturacao"]),
)


MODELO_DIABETES = joblib.load(PASTA_MODELO / "modelo_risco.joblib")


MODELO_CARDIO = joblib.load(PASTA_MODELO / "modelo_cardio.joblib")
logger.info("Modelos de risco carregados (diabetes, cardiovascular)")


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


def _proximo_id_utente():
    if DADOS["utentes"].empty:
        return "U0001"
    maior = DADOS["utentes"]["id_utente"].str.lstrip("U").astype(int).max()
    return f"U{maior + 1:04d}"


def _gerar_numero_processo():
    existentes = set(DADOS["utentes"]["processo"].astype(str))
    candidato = str(random.randint(100000, 999999))
    while candidato in existentes:
        candidato = str(random.randint(100000, 999999))
    return candidato


SECCOES_NAVEGACAO = [
    ("Início", [("/", "Visão Geral")]),
    ("Geral", [("/utentes", "Utentes")]),
    ("Cuidados continuados", [("/ocupacao", "Mapa de Ocupação")]),
    ("Clínica & Hospital", [("/consultas", "Consultas")]),
    ("Relatórios", [("/relatorios", "Relatórios")]),
    ("Faturação", [("/faturacao", "Faturação")]),
    ("Profissionais", [("/profissionais", "Profissionais")]),
]


ICONES_PERFIL = {
    "Enfermeiro": "/assets/icones/enfermeiro.svg",
    "Médico": "/assets/icones/medico.svg",
    "Receção": "/assets/icones/recepcao.svg",
    "Admin": "/assets/icones/admin.svg",
}


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


def _e_simulacao(sessao):
    """True se a sessão atual entrou através de /simulacao ("Modo simulação"), em vez
    do /login real. Usado só para mostrar o aviso de simulação e mandar o "Sair" de
    volta para a vitrine em vez do login — não muda o formato de _dados_sessao acima
    (muitos pontos do código dependem do tuplo (perfil, profissional) que essa função
    devolve)."""
    if not sessao or isinstance(sessao, str):
        return False
    return bool(sessao.get("simulacao"))


FUNCIONALIDADES_VITRINE = [
    (
        "/assets/icones/ficha-clinica.svg",
        "Ficha clínica completa",
        "Sinais vitais, diagnósticos, prescrições, exames, plano de cuidados multidisciplinar e "
        "histórico, com exportação em PDF.",
    ),
    (
        "/assets/icones/risco-ml.svg",
        "Risco por machine learning",
        "Diabetes e risco cardiovascular (random forest) e risco de queda (Morse Fall Scale), com "
        "resumo automático em português.",
    ),
    (
        "/assets/icones/agenda-faturacao.svg",
        "Agenda e faturação",
        "Marcação, cancelamento e reagendamento de consultas, mapa de ocupação e faturação com "
        "comparticipação da Segurança Social e seguradoras privadas.",
    ),
    (
        "/assets/icones/acesso-perfil.svg",
        "Acesso por perfil",
        "Cada perfil (Enfermeiro, Médico, Receção e Admin) só vê os módulos relevantes ao seu papel, "
        "tal como aconteceria com contas reais.",
    ),
]


ORIENTACAO_POR_PERFIL = {
    "Enfermeiro": "Vês a ficha clínica dos utentes, registas sinais vitais e cuidados, e consultas a tua agenda, sem acesso a faturação nem à gestão de profissionais.",
    "Médico": "Além da ficha clínica, podes prescrever medicação e emitir receitas em PDF, e consultas o teu relatório de atividade, sem acesso a faturação nem à gestão de profissionais.",
    "Receção": "Marca, cancela e reagenda consultas, consultas a ocupação e emites faturação, sem acesso a atos clínicos (prescrições, avaliação de risco) nem à gestão de profissionais.",
    "Admin": "Acesso total: tudo o que a Receção faz, mais a gestão do cadastro de profissionais e os relatórios de atividade de qualquer um deles.",
}


URL_REPOSITORIO = "https://github.com/elisamanuel-on/sistema-gestao-saude"


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


def _consultas_periodo_profissional(nome, data_inicio=None, data_fim=None):
    """Lista detalhada (uma linha por consulta, com o nome do utente) por
    trás dos totais de _estatisticas_atividade_profissional — só usada nos
    relatórios em PDF/Excel, que precisam do detalhe, não só dos KPIs
    agregados que a página mostra."""
    df = DADOS["consultas"][DADOS["consultas"]["profissional"] == nome]
    if data_inicio:
        df = df[df["data_hora"] >= pd.Timestamp(data_inicio)]
    if data_fim:
        df = df[df["data_hora"] < pd.Timestamp(data_fim) + pd.Timedelta(days=1)]
    return df.merge(DADOS["utentes"][["id_utente", "nome"]], on="id_utente").sort_values("data_hora")


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



__all__ = [
    "PASTA_DADOS",
    "PASTA_MODELO",
    "ESTADOS_UTENTE",
    "ESTADOS_VALIDOS_POR_TIPO",
    "TOM_PLANO",
    "_slug",
    "RES_DIABETES",
    "OPCOES_SEXO",
    "OPCOES_TIPO_DOR_PEITO",
    "OPCOES_SIM_NAO",
    "OPCOES_ECG_REPOUSO",
    "OPCOES_INCLINACAO_ST",
    "OPCOES_TALASSEMIA",
    "CORES",
    "ESTILO_CELULA_TABELA",
    "ESTILO_CABECALHO_TABELA",
    "ZEBRA_TABELA",
    "_com_zebra",
    "_carregar_todos_os_dados",
    "DADOS",
    "MODELO_DIABETES",
    "MODELO_CARDIO",
    "RES_CARDIO",
    "_nome_utente",
    "_idade_utente",
    "_ids_utentes_risco_elevado",
    "_registar_historico",
    "_proximo_id_prescricao",
    "_proximo_id_utente",
    "_gerar_numero_processo",
    "SECCOES_NAVEGACAO",
    "ICONES_PERFIL",
    "PERFIS_COM_PROFISSIONAL",
    "_dados_sessao",
    "_e_simulacao",
    "FUNCIONALIDADES_VITRINE",
    "ORIENTACAO_POR_PERFIL",
    "URL_REPOSITORIO",
    "_proximo_id_consulta",
    "_conflito_consulta",
    "_formatar_euros",
    "COLUNAS_EXPORTACAO_FATURACAO",
    "COLUNAS_COM_PROFISSIONAL",
    "_stats_profissional",
    "_profissional_tem_historico",
    "_estatisticas_atividade_profissional",
    "_consultas_periodo_profissional",
    "_opcoes_relatorio_consulta",
    "METRICAS_DIABETES",
    "METRICAS_CARDIO",
]
