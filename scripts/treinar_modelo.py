"""Treina o modelo de risco de diabetes a partir do registo clínico limpo.

Compara regressão logística com random forest por validação cruzada
(AUC-ROC) e guarda o vencedor em modelo/modelo_risco.joblib, mais as
métricas de desempenho em modelo/metricas_modelo.json para serem mostradas
na página da calculadora de risco (transparência sobre a fiabilidade do
modelo, não só um número de risco sem contexto).
"""
import json
import pathlib

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from limpeza import COLUNAS_NUMERICAS_CLINICAS, limpar_registo_bruto, preparar_para_modelo

PASTA_MODELO = pathlib.Path("modelo")


def treinar():
    df_limpo, _relatorio = limpar_registo_bruto("dados/registo_bruto.csv")
    X, y = preparar_para_modelo(df_limpo)

    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    candidatos = {
        "regressao_logistica": Pipeline(
            [("escala", StandardScaler()), ("modelo", LogisticRegression(max_iter=1000, random_state=42))]
        ),
        "random_forest": Pipeline(
            [("modelo", RandomForestClassifier(n_estimators=300, max_depth=6, random_state=42))]
        ),
    }

    resultados_cv = {}
    for nome, pipeline in candidatos.items():
        pontuacoes = cross_val_score(pipeline, X_treino, y_treino, cv=5, scoring="roc_auc")
        resultados_cv[nome] = float(np.mean(pontuacoes))
        print(f"{nome}: AUC média (5-fold CV) = {resultados_cv[nome]:.3f}")

    nome_vencedor = max(resultados_cv, key=resultados_cv.get)
    pipeline_vencedor = candidatos[nome_vencedor]
    pipeline_vencedor.fit(X_treino, y_treino)

    probabilidades = pipeline_vencedor.predict_proba(X_teste)[:, 1]
    previsoes = pipeline_vencedor.predict(X_teste)

    auc_teste = float(roc_auc_score(y_teste, probabilidades))
    acc_teste = float(accuracy_score(y_teste, previsoes))
    matriz = confusion_matrix(y_teste, previsoes).tolist()

    if nome_vencedor == "regressao_logistica":
        coeficientes = pipeline_vencedor.named_steps["modelo"].coef_[0]
        importancias = dict(zip(COLUNAS_NUMERICAS_CLINICAS, [float(c) for c in coeficientes], strict=True))
    else:
        importancias_arr = pipeline_vencedor.named_steps["modelo"].feature_importances_
        importancias = dict(zip(COLUNAS_NUMERICAS_CLINICAS, [float(c) for c in importancias_arr], strict=True))

    PASTA_MODELO.mkdir(exist_ok=True)
    joblib.dump(pipeline_vencedor, PASTA_MODELO / "modelo_risco.joblib")

    metricas = {
        "modelo_escolhido": nome_vencedor,
        "auc_validacao_cruzada": resultados_cv,
        "auc_conjunto_teste": auc_teste,
        "acuracia_conjunto_teste": acc_teste,
        "matriz_confusao": {
            "rotulos": ["sem_diabetes", "com_diabetes"],
            "valores": matriz,
        },
        "n_treino": len(X_treino),
        "n_teste": len(X_teste),
        "importancia_features": importancias,
    }
    with open(PASTA_MODELO / "metricas_modelo.json", "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2, ensure_ascii=False)

    print(f"\nModelo escolhido: {nome_vencedor}")
    print(f"AUC (conjunto de teste, nunca visto no treino): {auc_teste:.3f}")
    print(f"Acurácia (conjunto de teste): {acc_teste:.3f}")
    print("Guardado em modelo/modelo_risco.joblib e modelo/metricas_modelo.json")


if __name__ == "__main__":
    treinar()
