"""Gera dados/registo_bruto.csv a partir do dataset público Pima Indians Diabetes.

O ficheiro original (dados/pima_diabetes_raw.csv, descarregado de uma cópia
pública amplamente redistribuída do dataset do National Institute of
Diabetes and Digestive and Kidney Diseases, sem qualquer identificação de
pacientes) é só números: Pregnancies, Glucose, BloodPressure, SkinThickness,
Insulin, BMI, DiabetesPedigreeFunction, Age, Outcome.

Este script constrói uma versão "em bruto" propositadamente desorganizada,
como se fosse a digitalização inicial de fichas de admissão de uma clínica:
IDs de paciente sintéticos (nunca nomes reais), datas em formatos
inconsistentes, valores em falta representados de formas diferentes
consoante quem digitou, duplicados e valores claramente inválidos. É este
ficheiro "sujo" que a página de estruturação do dashboard trata e limpa —
não há nenhum dado de paciente real em lado nenhum deste projeto.
"""
import random

import numpy as np
import pandas as pd

ALEATORIO = random.Random(42)
RNG = np.random.default_rng(42)

COLUNAS_ORIGINAIS = [
    "gravidezes",
    "glicose",
    "pressao_arterial",
    "espessura_pele",
    "insulina",
    "imc",
    "pedigree_diabetes",
    "idade",
    "resultado",
]

# Colunas onde, no dataset original, um "0" é na verdade um marcador de
# valor em falta (não é biologicamente possível ter glicose ou IMC = 0).
COLUNAS_COM_ZEROS_SUSPEITOS = ["glicose", "pressao_arterial", "espessura_pele", "insulina", "imc"]

MARCADORES_DE_FALTA = ["", "N/D", "s/dados", "0", "--"]


def _data_aleatoria_inconsistente():
    """Devolve uma data de registo em 1 de 3 formatos diferentes, simulando
    que fichas de admissão foram digitalizadas por pessoas diferentes."""
    dia = ALEATORIO.randint(1, 28)
    mes = ALEATORIO.randint(1, 12)
    ano = ALEATORIO.choice([2024, 2025])
    formato = ALEATORIO.choice(["iso", "pt", "pt_barra"])
    if formato == "iso":
        return f"{ano:04d}-{mes:02d}-{dia:02d}"
    if formato == "pt":
        return f"{dia:02d}-{mes:02d}-{ano:04d}"
    return f"{dia:02d}/{mes:02d}/{ano:04d}"


def _resultado_inconsistente(valor_original):
    """0/1 -> "sim"/"não" escritos de formas diferentes (maiúsculas,
    minúsculas, com/sem acento) — outro tipo de sujidade comum em registos
    manuais que a limpeza de dados tem de normalizar."""
    positivo = ["Sim", "sim", "SIM", "Positivo"]
    negativo = ["Não", "nao", "NÃO", "Negativo"]
    return ALEATORIO.choice(positivo) if valor_original == 1 else ALEATORIO.choice(negativo)


def _sujar_valor_numerico(valor, coluna):
    if coluna in COLUNAS_COM_ZEROS_SUSPEITOS and float(valor) == 0.0:
        return ALEATORIO.choice(MARCADORES_DE_FALTA)
    # ocasionalmente introduz espaços em branco à volta do número, outro
    # problema clássico de exportações/digitação manual.
    texto = str(valor)
    if ALEATORIO.random() < 0.03:
        texto = f" {texto} "
    return texto


def gerar():
    df = pd.read_csv("dados/pima_diabetes_raw.csv", header=None, names=COLUNAS_ORIGINAIS)

    linhas = []
    for i, linha in df.iterrows():
        id_paciente = f"P{i + 1:04d}"
        registo = {
            "id_paciente": id_paciente,
            "data_registo": _data_aleatoria_inconsistente(),
        }
        for coluna in COLUNAS_ORIGINAIS:
            if coluna == "resultado":
                registo[coluna] = _resultado_inconsistente(linha[coluna])
            else:
                registo[coluna] = _sujar_valor_numerico(linha[coluna], coluna)
        linhas.append(registo)

    bruto = pd.DataFrame(linhas)

    # introduz ~15 duplicados (fichas digitalizadas duas vezes por engano)
    indices_duplicados = ALEATORIO.sample(range(len(bruto)), 15)
    duplicados = bruto.iloc[indices_duplicados].copy()
    bruto = pd.concat([bruto, duplicados], ignore_index=True)

    # introduz um punhado de valores claramente inválidos para a validação apanhar
    indices_invalidos = ALEATORIO.sample(range(len(bruto)), 6)
    for pos, idx in enumerate(indices_invalidos):
        if pos % 3 == 0:
            bruto.loc[idx, "idade"] = "300"
        elif pos % 3 == 1:
            bruto.loc[idx, "imc"] = "-5.0"
        else:
            bruto.loc[idx, "glicose"] = "9999"

    bruto = bruto.sample(frac=1, random_state=7).reset_index(drop=True)
    bruto.to_csv("dados/registo_bruto.csv", index=False)
    print(f"Gerado dados/registo_bruto.csv com {len(bruto)} linhas (inclui duplicados e valores inválidos propositados).")


if __name__ == "__main__":
    gerar()
