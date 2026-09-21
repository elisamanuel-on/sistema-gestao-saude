"""Limpeza e validação do registo clínico "em bruto".

Módulo partilhado entre o treino do modelo (scripts/treinar_modelo.py) e a
aplicação (app.py), para garantir que os dados usados para treinar o modelo
passam exatamente pela mesma limpeza que os dados mostrados/editados no
dashboard — nunca duas lógicas de limpeza divergentes.

Todos os dados aqui são sintéticos/anonimizados (ver README). Nada neste
ficheiro identifica pessoas reais.
"""
import unicodedata

import numpy as np
import pandas as pd

COLUNAS_NUMERICAS_CLINICAS = [
    "gravidezes",
    "glicose",
    "pressao_arterial",
    "espessura_pele",
    "insulina",
    "imc",
    "pedigree_diabetes",
    "idade",
]

# Nestas colunas, no registo em bruto, um "0" não é um valor real — é um
# marcador de "não medido" que fica registado como zero por erro de
# digitação/exportação. Ver dataset original (Pima Indians Diabetes).
COLUNAS_ONDE_ZERO_E_FALTA = ["glicose", "pressao_arterial", "espessura_pele", "insulina", "imc"]

MARCADORES_DE_FALTA = {"", "n/d", "s/dados", "--", "nd", "na", "n/a"}

# Limites de plausibilidade clínica — fora destes intervalos o valor é
# tratado como inválido (erro de digitação), não como um valor extremo real.
LIMITES_PLAUSIVEIS = {
    "gravidezes": (0, 20),
    "glicose": (30, 500),
    "pressao_arterial": (20, 220),
    "espessura_pele": (0, 100),
    "insulina": (0, 900),
    "imc": (8, 80),
    "pedigree_diabetes": (0, 3),
    "idade": (0, 120),
}

FORMATOS_DE_DATA = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]


def _remover_acentos(texto):
    forma = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in forma if not unicodedata.combining(c))


def _normalizar_resultado(valor):
    if pd.isna(valor):
        return np.nan
    texto = _remover_acentos(str(valor).strip().lower())
    if texto in {"sim", "positivo", "1"}:
        return 1
    if texto in {"nao", "negativo", "0"}:
        return 0
    return np.nan


def _texto_para_numero(valor, coluna):
    if pd.isna(valor):
        return np.nan
    texto = str(valor).strip().lower()
    if texto in MARCADORES_DE_FALTA:
        return np.nan
    try:
        numero = float(texto)
    except ValueError:
        return np.nan
    if coluna in COLUNAS_ONDE_ZERO_E_FALTA and numero == 0.0:
        return np.nan
    return numero


def _data_para_iso(valor):
    if pd.isna(valor):
        return pd.NaT
    texto = str(valor).strip()
    for formato in FORMATOS_DE_DATA:
        try:
            return pd.to_datetime(texto, format=formato)
        except ValueError:
            continue
    return pd.NaT


def limpar_registo_bruto(caminho_ou_df):
    """Recebe o caminho do CSV em bruto (ou já um DataFrame) e devolve
    (df_limpo, relatorio). df_limpo mantém NaN onde o dado está em falta —
    não inventa valores; ver preparar_para_modelo() para a versão imputada
    usada só para treinar/prever."""
    if isinstance(caminho_ou_df, pd.DataFrame):
        bruto = caminho_ou_df.copy()
    else:
        bruto = pd.read_csv(caminho_ou_df, dtype=str)

    relatorio = {"linhas_no_ficheiro_bruto": len(bruto)}

    bruto["id_paciente"] = bruto["id_paciente"].astype(str).str.strip()
    antes = len(bruto)
    bruto = bruto.drop_duplicates(subset="id_paciente", keep="first").reset_index(drop=True)
    relatorio["duplicados_removidos"] = antes - len(bruto)

    limpo = pd.DataFrame({"id_paciente": bruto["id_paciente"]})
    limpo["data_registo"] = bruto["data_registo"].apply(_data_para_iso)
    relatorio["datas_nao_reconhecidas"] = int(limpo["data_registo"].isna().sum())

    valores_invalidos_corrigidos = 0
    for coluna in COLUNAS_NUMERICAS_CLINICAS:
        serie = bruto[coluna].apply(lambda v, c=coluna: _texto_para_numero(v, c))
        minimo, maximo = LIMITES_PLAUSIVEIS[coluna]
        fora_do_limite = serie.notna() & ((serie < minimo) | (serie > maximo))
        valores_invalidos_corrigidos += int(fora_do_limite.sum())
        serie = serie.mask(fora_do_limite, np.nan)
        limpo[coluna] = serie
    relatorio["valores_invalidos_corrigidos"] = valores_invalidos_corrigidos

    # gravidezes é uma contagem — depois de limpo, arredonda para inteiro
    # anulável (o CSV em bruto trazia "10.0" por causa de um detalhe do
    # pandas ao ler a linha inteira como float, não é um valor real com casas decimais).
    limpo["gravidezes"] = limpo["gravidezes"].round().astype("Int64")

    limpo["resultado"] = bruto["resultado"].apply(_normalizar_resultado).astype("Int64")
    relatorio["resultados_nao_reconhecidos"] = int(limpo["resultado"].isna().sum())

    relatorio["valores_em_falta_por_coluna"] = {
        coluna: int(limpo[coluna].isna().sum()) for coluna in COLUNAS_NUMERICAS_CLINICAS
    }
    relatorio["linhas_estruturadas"] = len(limpo)

    return limpo, relatorio


def preparar_para_modelo(df_limpo):
    """Versão imputada (mediana por coluna) do registo limpo, só para
    treinar ou alimentar o modelo — nunca usada para mostrar os dados na
    tabela de registo, onde os valores em falta continuam visíveis como tal."""
    completo = df_limpo.dropna(subset=["resultado"]).copy()
    for coluna in COLUNAS_NUMERICAS_CLINICAS:
        mediana = completo[coluna].median()
        completo[coluna] = completo[coluna].fillna(mediana)
    completo["gravidezes"] = completo["gravidezes"].astype(float)
    X = completo[COLUNAS_NUMERICAS_CLINICAS]
    y = completo["resultado"].astype(int)
    return X, y
