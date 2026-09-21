"""Gera todo o conjunto de dados sintéticos do sistema de gestão de utentes:
utentes, sinais vitais, diagnósticos, prescrições, visitas, alergias,
documentos (metadados), faturação, capacidade e altas.

Tudo sintético e claramente fictício — nomes gerados por Faker (nunca
pessoas reais), valores clínicos amostrados a partir dos datasets públicos
já usados (Pima Diabetes, UCI Heart Disease) para manter distribuições
realistas, e depois passados pelos modelos já treinados para pré-calcular
uma primeira avaliação de risco por utente.
"""
import datetime
import json
import pathlib
import random

import joblib
import numpy as np
import pandas as pd
from faker import Faker

from limpeza import COLUNAS_NUMERICAS_CLINICAS, limpar_registo_bruto
from riscos import (
    OPCOES_APOIO_MARCHA,
    OPCOES_DIAGNOSTICO_SECUNDARIO,
    OPCOES_ESTADO_MENTAL,
    OPCOES_HISTORICO_QUEDAS,
    OPCOES_MARCHA,
    OPCOES_SORO_IV,
    calcular_risco_queda,
)
from scripts.treinar_modelo_cardio import COLUNAS_CARDIO

ALEATORIO = random.Random(11)
RNG = np.random.default_rng(11)
faker_pt = Faker("pt_PT")
Faker.seed(11)

N_UTENTES = 45
TIPOS_CUIDADO = ["UCC", "ERPI", "SAD"]
CAPACIDADE = {"UCC": 18, "ERPI": 30, "SAD": 25}

DIAGNOSTICOS_COMUNS = [
    "Hipertensão arterial", "Diabetes tipo 2", "Insuficiência cardíaca",
    "Demência leve", "Osteoporose", "DPOC", "Artrose", "Depressão",
    "Obesidade", "Dislipidemia", "Fibrilhação auricular", "Doença renal crónica",
]
MEDICAMENTOS_COMUNS = [
    ("Metformina", "500mg, 2x/dia"), ("Losartan", "50mg, 1x/dia"),
    ("Paracetamol", "1g, se dor, máx 3x/dia"), ("Omeprazol", "20mg, 1x/dia"),
    ("Atorvastatina", "20mg, à noite"), ("Furosemida", "40mg, de manhã"),
    ("Sertralina", "50mg, 1x/dia"), ("AAS", "100mg, 1x/dia"),
    ("Alendronato", "70mg, semanal"), ("Levotiroxina", "50mcg, em jejum"),
]
ALERGIAS_POSSIVEIS = ["Penicilina", "Látex", "Aspirina", "Iodo", "Ácaros"]
TIPOS_VISITA = ["Consulta médica", "Enfermagem", "Fisioterapia", "Visita familiar", "Psicologia"]
PROFISSIONAIS = ["Dr. Ricardo Rocha", "Dra. Inês Fonseca", "Enf. Marta Sousa", "Enf. Paulo Cardoso", "Fisio. Beatriz Lima"]
TIPOS_DOCUMENTO = ["Consentimento informado", "Relatório de alta", "Plano individual de cuidados", "Ficha de anamnese"]
MOTIVOS_ALTA = ["Melhoria clínica", "Transferência para outra unidade", "Alta a pedido da família", "Óbito"]

PASTA_DADOS = pathlib.Path("dados")
PASTA_MODELO = pathlib.Path("modelo")


def _gerar_utentes():
    linhas = []
    hoje = datetime.date.today()
    for i in range(1, N_UTENTES + 1):
        genero = ALEATORIO.choice(["Feminino", "Masculino"])
        nome = faker_pt.name_female() if genero == "Feminino" else faker_pt.name_male()
        idade = ALEATORIO.randint(45, 94)
        data_nascimento = hoje - datetime.timedelta(days=idade * 365 + ALEATORIO.randint(0, 364))
        tipo_cuidado = ALEATORIO.choices(TIPOS_CUIDADO, weights=[0.3, 0.45, 0.25])[0]
        dias_admissao = ALEATORIO.randint(10, 900)
        data_admissao = hoje - datetime.timedelta(days=dias_admissao)
        estado = ALEATORIO.choices(["Internado", "Alta", "Em espera"], weights=[0.78, 0.14, 0.08])[0]
        quarto = f"{ALEATORIO.randint(1, 4)}0{ALEATORIO.randint(1, 9)}-{ALEATORIO.choice('ABC')}" if tipo_cuidado != "SAD" and estado == "Internado" else "—"
        linhas.append(
            {
                "id_utente": f"U{i:04d}",
                "nome": nome,
                "genero": genero,
                "data_nascimento": data_nascimento.isoformat(),
                "processo": f"{ALEATORIO.randint(100000, 999999)}",
                "tipo_cuidado": tipo_cuidado,
                "data_admissao": data_admissao.isoformat(),
                "quarto": quarto,
                "estado": estado,
            }
        )
    return pd.DataFrame(linhas)


def _amostrar_clinicos_diabetes(n):
    df_limpo, _ = limpar_registo_bruto("dados/registo_bruto.csv")
    completo = df_limpo.dropna(subset=COLUNAS_NUMERICAS_CLINICAS + ["resultado"])
    amostra = completo.sample(n=n, replace=True, random_state=11).reset_index(drop=True)
    return amostra[COLUNAS_NUMERICAS_CLINICAS]


def _amostrar_clinicos_cardio(n):
    df = pd.read_csv("dados/heart_disease_raw.csv")
    df.columns = COLUNAS_CARDIO + ["resultado"]
    amostra = df.sample(n=n, replace=True, random_state=12).reset_index(drop=True)
    return amostra[COLUNAS_CARDIO]


def _gerar_avaliacoes_risco(utentes):
    modelo_diabetes = joblib.load(PASTA_MODELO / "modelo_risco.joblib")
    modelo_cardio = joblib.load(PASTA_MODELO / "modelo_cardio.joblib")

    clinicos_diabetes = _amostrar_clinicos_diabetes(len(utentes))
    clinicos_cardio = _amostrar_clinicos_cardio(len(utentes))

    prob_diabetes = modelo_diabetes.predict_proba(clinicos_diabetes)[:, 1]
    prob_cardio = modelo_cardio.predict_proba(clinicos_cardio)[:, 1]

    clinicos_diabetes = clinicos_diabetes.copy()
    clinicos_diabetes.insert(0, "id_utente", utentes["id_utente"].values)
    clinicos_diabetes["probabilidade"] = prob_diabetes

    clinicos_cardio = clinicos_cardio.copy()
    clinicos_cardio.insert(0, "id_utente", utentes["id_utente"].values)
    clinicos_cardio["probabilidade"] = prob_cardio

    linhas_queda = []
    for id_utente in utentes["id_utente"]:
        historico = ALEATORIO.choices(list(OPCOES_HISTORICO_QUEDAS), weights=[0.75, 0.25])[0]
        secundario = ALEATORIO.choices(list(OPCOES_DIAGNOSTICO_SECUNDARIO), weights=[0.4, 0.6])[0]
        apoio = ALEATORIO.choices(list(OPCOES_APOIO_MARCHA), weights=[0.35, 0.45, 0.2])[0]
        soro = ALEATORIO.choices(list(OPCOES_SORO_IV), weights=[0.85, 0.15])[0]
        marcha = ALEATORIO.choices(list(OPCOES_MARCHA), weights=[0.4, 0.35, 0.25])[0]
        mental = ALEATORIO.choices(list(OPCOES_ESTADO_MENTAL), weights=[0.7, 0.3])[0]
        pontuacao, classificacao, _tom = calcular_risco_queda(historico, secundario, apoio, soro, marcha, mental)
        linhas_queda.append(
            {
                "id_utente": id_utente,
                "historico_quedas": historico,
                "diagnostico_secundario": secundario,
                "apoio_marcha": apoio,
                "soro_iv": soro,
                "marcha": marcha,
                "estado_mental": mental,
                "pontuacao": pontuacao,
                "classificacao": classificacao,
            }
        )
    df_queda = pd.DataFrame(linhas_queda)
    return clinicos_diabetes, clinicos_cardio, df_queda


def _gerar_vitais(utentes):
    linhas = []
    hoje = datetime.datetime.now()
    for id_utente in utentes["id_utente"]:
        n_leituras = ALEATORIO.randint(6, 14)
        peso_base = RNG.normal(70, 12)
        for _j in range(n_leituras):
            data_hora = hoje - datetime.timedelta(days=ALEATORIO.randint(0, 60), hours=ALEATORIO.randint(0, 23))
            linhas.append(
                {
                    "id_utente": id_utente,
                    "data_hora": data_hora.isoformat(timespec="minutes"),
                    "temperatura": round(float(RNG.normal(36.5, 0.4)), 1),
                    "tensao_sistolica": int(RNG.normal(128, 15)),
                    "tensao_diastolica": int(RNG.normal(80, 10)),
                    "glicemia": int(RNG.normal(110, 25)),
                    "peso_kg": round(peso_base + float(RNG.normal(0, 0.6)), 1),
                    "dor": ALEATORIO.choices(range(0, 11), weights=[30, 15, 12, 10, 8, 8, 6, 5, 3, 2, 1])[0],
                }
            )
    return pd.DataFrame(linhas).sort_values(["id_utente", "data_hora"]).reset_index(drop=True)


def _gerar_diagnosticos(utentes):
    linhas = []
    hoje = datetime.date.today()
    for id_utente in utentes["id_utente"]:
        for diagnostico in ALEATORIO.sample(DIAGNOSTICOS_COMUNS, ALEATORIO.randint(1, 4)):
            linhas.append(
                {
                    "id_utente": id_utente,
                    "data": (hoje - datetime.timedelta(days=ALEATORIO.randint(0, 700))).isoformat(),
                    "profissional": ALEATORIO.choice(PROFISSIONAIS),
                    "diagnostico": diagnostico,
                }
            )
    return pd.DataFrame(linhas)


def _gerar_prescricoes(utentes):
    linhas = []
    hoje = datetime.date.today()
    for id_utente in utentes["id_utente"]:
        for medicamento, posologia in ALEATORIO.sample(MEDICAMENTOS_COMUNS, ALEATORIO.randint(1, 5)):
            linhas.append(
                {
                    "id_utente": id_utente,
                    "data": (hoje - datetime.timedelta(days=ALEATORIO.randint(0, 400))).isoformat(),
                    "profissional": ALEATORIO.choice(PROFISSIONAIS),
                    "medicamento": medicamento,
                    "posologia": posologia,
                }
            )
    return pd.DataFrame(linhas)


def _gerar_visitas(utentes):
    linhas = []
    hoje = datetime.datetime.now()
    for id_utente in utentes["id_utente"]:
        for _ in range(ALEATORIO.randint(2, 8)):
            linhas.append(
                {
                    "id_utente": id_utente,
                    "data_hora": (hoje - datetime.timedelta(days=ALEATORIO.randint(0, 120))).isoformat(timespec="minutes"),
                    "tipo": ALEATORIO.choice(TIPOS_VISITA),
                    "registado_por": ALEATORIO.choice(PROFISSIONAIS),
                }
            )
    return pd.DataFrame(linhas).sort_values(["id_utente", "data_hora"], ascending=[True, False]).reset_index(drop=True)


def _gerar_alergias(utentes):
    linhas = []
    for id_utente in utentes["id_utente"]:
        if ALEATORIO.random() < 0.35:
            for alergia in ALEATORIO.sample(ALERGIAS_POSSIVEIS, ALEATORIO.randint(1, 2)):
                linhas.append({"id_utente": id_utente, "alergia": alergia})
        else:
            linhas.append({"id_utente": id_utente, "alergia": "Nenhuma conhecida"})
    return pd.DataFrame(linhas)


def _gerar_documentos(utentes):
    linhas = []
    hoje = datetime.date.today()
    for id_utente in utentes["id_utente"]:
        for tipo in ALEATORIO.sample(TIPOS_DOCUMENTO, ALEATORIO.randint(1, 3)):
            linhas.append(
                {
                    "id_utente": id_utente,
                    "nome_documento": f"{tipo}.pdf",
                    "tipo": tipo,
                    "data_upload": (hoje - datetime.timedelta(days=ALEATORIO.randint(0, 500))).isoformat(),
                }
            )
    return pd.DataFrame(linhas)


def _gerar_faturacao(utentes):
    linhas = []
    for _idx, utente in utentes.iterrows():
        if utente["tipo_cuidado"] == "SAD":
            ars_diarias = 0.0
        else:
            ars_diarias = round(RNG.uniform(600, 1400), 2)
        linhas.append(
            {
                "id_utente": utente["id_utente"],
                "periodo": "2026-08",
                "valor_a_pagar_utente": round(RNG.uniform(300, 900), 2),
                "comparticipacao_ss": round(RNG.uniform(200, 700), 2),
                "ars_diarias_internamento": ars_diarias,
                "ars_pacote_medicamentos": round(RNG.uniform(80, 260), 2),
                "ars_remuneracao_adicional": round(RNG.uniform(0, 150), 2),
                "erro_fatura": ALEATORIO.random() < 0.08,
            }
        )
    df = pd.DataFrame(linhas)
    df["saldo_cc"] = (df["valor_a_pagar_utente"] + df["comparticipacao_ss"] - df["ars_diarias_internamento"] * 0.1).round(2)
    return df


def _gerar_altas(utentes):
    linhas = []
    hoje = datetime.date.today()
    utentes_alta = utentes[utentes["estado"] == "Alta"]
    for _idx, utente in utentes_alta.iterrows():
        linhas.append(
            {
                "id_utente": utente["id_utente"],
                "tipo_cuidado": utente["tipo_cuidado"],
                "data_alta": (hoje - datetime.timedelta(days=ALEATORIO.randint(0, 180))).isoformat(),
                "motivo": ALEATORIO.choices(MOTIVOS_ALTA, weights=[0.45, 0.25, 0.2, 0.1])[0],
            }
        )
    return pd.DataFrame(linhas)


def gerar_tudo():
    PASTA_DADOS.mkdir(exist_ok=True)
    utentes = _gerar_utentes()
    utentes.to_csv(PASTA_DADOS / "utentes.csv", index=False)

    clinicos_diabetes, clinicos_cardio, df_queda = _gerar_avaliacoes_risco(utentes)
    clinicos_diabetes.to_csv(PASTA_DADOS / "avaliacao_diabetes.csv", index=False)
    clinicos_cardio.to_csv(PASTA_DADOS / "avaliacao_cardio.csv", index=False)
    df_queda.to_csv(PASTA_DADOS / "avaliacao_queda.csv", index=False)

    _gerar_vitais(utentes).to_csv(PASTA_DADOS / "vitais.csv", index=False)
    _gerar_diagnosticos(utentes).to_csv(PASTA_DADOS / "diagnosticos.csv", index=False)
    _gerar_prescricoes(utentes).to_csv(PASTA_DADOS / "prescricoes.csv", index=False)
    _gerar_visitas(utentes).to_csv(PASTA_DADOS / "visitas.csv", index=False)
    _gerar_alergias(utentes).to_csv(PASTA_DADOS / "alergias.csv", index=False)
    _gerar_documentos(utentes).to_csv(PASTA_DADOS / "documentos.csv", index=False)
    _gerar_faturacao(utentes).to_csv(PASTA_DADOS / "faturacao.csv", index=False)
    _gerar_altas(utentes).to_csv(PASTA_DADOS / "altas.csv", index=False)

    with open(PASTA_DADOS / "capacidade.json", "w", encoding="utf-8") as f:
        json.dump(CAPACIDADE, f, indent=2, ensure_ascii=False)

    print(f"Gerados {len(utentes)} utentes e todas as tabelas associadas em {PASTA_DADOS}/")


if __name__ == "__main__":
    gerar_tudo()
