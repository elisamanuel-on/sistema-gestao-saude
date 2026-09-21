"""Módulo central de avaliação de risco clínico: diabetes (ML), risco
cardiovascular (ML) e risco de queda (escala clínica baseada em regras —
não é machine learning, é a Morse Fall Scale, um instrumento clínico
publicado e amplamente usado, não uma invenção deste projeto).

Inclui também gerar_resumo_ia(): um resumo em linguagem natural, gerado por
um motor de regras (template), pensado para o profissional de saúde ler em
segundos e decidir — nunca é a decisão final, só apoio à decisão. Não chama
nenhuma API externa de IA generativa: é determinístico, corre offline e sem
custos, o que é intencional para um projeto de portfólio autossuficiente
(ver README).
"""

# --- Risco de queda: Morse Fall Scale ---------------------------------------
# Escala clínica publicada (Morse, 1989), usada em hospitais e unidades de
# cuidados continuados em todo o mundo. Pontuação 0-125.

OPCOES_HISTORICO_QUEDAS = {"Não": 0, "Sim, nos últimos 3 meses": 25}
OPCOES_DIAGNOSTICO_SECUNDARIO = {"Não": 0, "Sim (mais de um diagnóstico ativo)": 15}
OPCOES_APOIO_MARCHA = {
    "Nenhum / repouso / acompanhado por profissional": 0,
    "Canadianas, bengala ou andarilho": 15,
    "Apoia-se em mobiliário": 30,
}
OPCOES_SORO_IV = {"Não": 0, "Sim": 20}
OPCOES_MARCHA = {"Normal / acamado / cadeira de rodas": 0, "Fraca": 10, "Comprometida": 20}
OPCOES_ESTADO_MENTAL = {
    "Orientado(a), consciente das suas limitações": 0,
    "Sobrestima capacidades ou esquece limitações": 15,
}


def calcular_risco_queda(historico_quedas, diagnostico_secundario, apoio_marcha, soro_iv, marcha, estado_mental):
    pontuacao = (
        OPCOES_HISTORICO_QUEDAS[historico_quedas]
        + OPCOES_DIAGNOSTICO_SECUNDARIO[diagnostico_secundario]
        + OPCOES_APOIO_MARCHA[apoio_marcha]
        + OPCOES_SORO_IV[soro_iv]
        + OPCOES_MARCHA[marcha]
        + OPCOES_ESTADO_MENTAL[estado_mental]
    )
    if pontuacao < 25:
        classificacao = "Risco baixo"
        tom = "risco_baixo"
    elif pontuacao <= 50:
        classificacao = "Risco moderado"
        tom = "risco_moderado"
    else:
        classificacao = "Risco elevado"
        tom = "risco_elevado"
    return pontuacao, classificacao, tom


# --- Classificação genérica de probabilidade (diabetes / cardiovascular) ---


def classificar_risco(probabilidade):
    if probabilidade < 0.33:
        return "Risco baixo", "risco_baixo"
    if probabilidade < 0.66:
        return "Risco moderado", "risco_moderado"
    return "Risco elevado", "risco_elevado"


# --- Resumo automático (motor de regras, não é uma chamada a um LLM) -------


def gerar_resumo_ia(nome_utente, resultado_diabetes=None, resultado_cardio=None, resultado_queda=None):
    """Resumo curto em linguagem natural combinando os 3 domínios de risco
    já calculados, para o profissional ler antes de decidir. Cada
    resultado_* é opcional (None se ainda não foi calculado nesta sessão)."""
    frases = [f"Resumo automático para {nome_utente}:"]

    riscos_elevados = []
    riscos_moderados = []

    def _adjetivo(classificacao):
        return classificacao.lower().replace("risco ", "")

    if resultado_diabetes is not None:
        prob, classificacao, fatores = resultado_diabetes
        frases.append(f"O risco de diabetes é {_adjetivo(classificacao)} ({prob:.0%})" + (f", sobretudo por {fatores}" if fatores else "") + ".")
        if classificacao == "Risco elevado":
            riscos_elevados.append("diabetes")
        elif classificacao == "Risco moderado":
            riscos_moderados.append("diabetes")

    if resultado_cardio is not None:
        prob, classificacao, fatores = resultado_cardio
        frases.append(f"O risco cardiovascular é {_adjetivo(classificacao)} ({prob:.0%})" + (f", sobretudo por {fatores}" if fatores else "") + ".")
        if classificacao == "Risco elevado":
            riscos_elevados.append("cardiovascular")
        elif classificacao == "Risco moderado":
            riscos_moderados.append("cardiovascular")

    if resultado_queda is not None:
        pontuacao, classificacao, _tom = resultado_queda
        frases.append(f"O risco de queda é {_adjetivo(classificacao)} (Morse {pontuacao}/125).")
        if classificacao == "Risco elevado":
            riscos_elevados.append("queda")
        elif classificacao == "Risco moderado":
            riscos_moderados.append("queda")

    if riscos_elevados:
        frases.append(f"⚠ Recomenda-se revisão clínica prioritária: {', '.join(riscos_elevados)}.")
    elif riscos_moderados:
        frases.append(f"Vigilância recomendada em: {', '.join(riscos_moderados)}.")
    else:
        frases.append("Sem sinais de risco elevado nos domínios avaliados.")

    frases.append("Este resumo é apoio à decisão — a avaliação clínica final é sempre do profissional de saúde.")
    return " ".join(frases)


def principais_fatores(importancias, rotulos, n=3):
    """Devolve uma string com os n fatores de maior peso no modelo, em
    português, para compor o resumo automático."""
    principais = sorted(importancias.items(), key=lambda par: abs(par[1]), reverse=True)[:n]
    nomes = [rotulos.get(coluna, coluna) for coluna, _peso in principais]
    return ", ".join(nomes)
