"""Testes do Sistema de Gestão de Utentes e Cuidados de Saúde.

Cobre: limpeza/estruturação dos dados de diabetes (usada para treinar o
modelo), a escala clínica de risco de queda (Morse Fall Scale), o resumo
automático (motor de regras), e o roteamento/callbacks principais da app
(lista de utentes, ficha, avaliação de risco).

Não faz suposições sobre nomes concretos de utentes: usa sempre o primeiro
utente carregado a partir de dados/utentes.csv (sintético — ver
scripts/gerar_dados_utentes.py), para não ficar frágil a alterações na
geração dos dados.
"""
import pandas as pd

import app as m
import riscos
from limpeza import limpar_registo_bruto, preparar_para_modelo


def _primeiro_utente():
    return m.DADOS["utentes"].iloc[0]


class FalsoNClicks:
    pass


# --- Limpeza / estruturação (dados de diabetes) -----------------------------


def test_limpeza_remove_duplicados_e_marca_invalidos():
    df, relatorio = limpar_registo_bruto("dados/registo_bruto.csv")
    assert relatorio["duplicados_removidos"] == 15
    assert relatorio["valores_invalidos_corrigidos"] == 6
    assert relatorio["linhas_estruturadas"] == 768


def test_limpeza_mantem_valores_em_falta_como_nan_nao_inventa():
    df, _ = limpar_registo_bruto("dados/registo_bruto.csv")
    assert df["insulina"].isna().sum() > 0


def test_preparar_para_modelo_nao_deixa_nan():
    df, _ = limpar_registo_bruto("dados/registo_bruto.csv")
    X, y = preparar_para_modelo(df)
    assert X.isna().sum().sum() == 0
    assert set(y.unique()) <= {0, 1}


def test_data_em_3_formatos_diferentes_e_reconhecida():
    bruto = pd.DataFrame(
        {
            "id_paciente": ["P1", "P2", "P3"],
            "data_registo": ["2024-01-15", "15-01-2024", "15/01/2024"],
            "gravidezes": ["1", "1", "1"],
            "glicose": ["120", "120", "120"],
            "pressao_arterial": ["70", "70", "70"],
            "espessura_pele": ["20", "20", "20"],
            "insulina": ["80", "80", "80"],
            "imc": ["25.0", "25.0", "25.0"],
            "pedigree_diabetes": ["0.3", "0.3", "0.3"],
            "idade": ["40", "40", "40"],
            "resultado": ["Sim", "sim", "SIM"],
        }
    )
    limpo, relatorio = limpar_registo_bruto(bruto)
    assert relatorio["datas_nao_reconhecidas"] == 0
    assert limpo["data_registo"].nunique() == 1  # as 3 datas são o mesmo dia


# --- Risco de queda (Morse Fall Scale) ---------------------------------------


def test_risco_queda_pontuacao_minima_e_baixo():
    pontuacao, classificacao, tom = riscos.calcular_risco_queda(
        "Não", "Não", "Nenhum / repouso / acompanhado por profissional", "Não",
        "Normal / acamado / cadeira de rodas", "Orientado(a), consciente das suas limitações",
    )
    assert pontuacao == 0
    assert classificacao == "Risco baixo"
    assert tom == "risco_baixo"


def test_risco_queda_pontuacao_maxima_e_elevado():
    pontuacao, classificacao, tom = riscos.calcular_risco_queda(
        "Sim, nos últimos 3 meses", "Sim (mais de um diagnóstico ativo)", "Apoia-se em mobiliário", "Sim",
        "Comprometida", "Sobrestima capacidades ou esquece limitações",
    )
    assert pontuacao == 125
    assert classificacao == "Risco elevado"
    assert tom == "risco_elevado"


def test_risco_queda_limiar_baixo_para_moderado():
    # histórico de quedas sozinho = 25 pontos -> fronteira exata baixo/moderado
    pontuacao, classificacao, _tom = riscos.calcular_risco_queda(
        "Sim, nos últimos 3 meses", "Não", "Nenhum / repouso / acompanhado por profissional", "Não",
        "Normal / acamado / cadeira de rodas", "Orientado(a), consciente das suas limitações",
    )
    assert pontuacao == 25
    assert classificacao == "Risco moderado"


def test_risco_queda_limiar_moderado_para_elevado():
    # soro (20) + marcha comprometida (20) + diagnóstico secundário (15) = 55 -> elevado
    pontuacao, classificacao, _tom = riscos.calcular_risco_queda(
        "Não", "Sim (mais de um diagnóstico ativo)", "Nenhum / repouso / acompanhado por profissional", "Sim",
        "Comprometida", "Orientado(a), consciente das suas limitações",
    )
    assert pontuacao == 55
    assert classificacao == "Risco elevado"


def test_classificar_risco_generico_limiares():
    assert riscos.classificar_risco(0.10)[0] == "Risco baixo"
    assert riscos.classificar_risco(0.50)[0] == "Risco moderado"
    assert riscos.classificar_risco(0.90)[0] == "Risco elevado"


# --- Resumo automático (motor de regras) -------------------------------------


def test_resumo_ia_sem_nenhum_resultado_nao_rebenta():
    resumo = riscos.gerar_resumo_ia("Ana Teste")
    assert "Ana Teste" in resumo
    assert "apoio à decisão" in resumo


def test_resumo_ia_marca_risco_elevado_para_revisao_prioritaria():
    resumo = riscos.gerar_resumo_ia(
        "Ana Teste",
        resultado_diabetes=(0.9, "Risco elevado", "glicose"),
    )
    assert "revisão clínica prioritária" in resumo
    assert "diabetes" in resumo


def test_resumo_ia_nunca_repete_a_palavra_risco_duas_vezes_seguidas():
    resumo = riscos.gerar_resumo_ia(
        "Ana Teste",
        resultado_diabetes=(0.9, "Risco elevado", "glicose"),
        resultado_cardio=(0.5, "Risco moderado", "idade"),
        resultado_queda=(10, "Risco baixo", "risco_baixo"),
    )
    assert "risco risco" not in resumo.lower()


def test_principais_fatores_ordena_por_peso_absoluto():
    importancias = {"a": 0.1, "b": -0.9, "c": 0.5}
    rotulos = {"a": "Fator A", "b": "Fator B", "c": "Fator C"}
    resultado = riscos.principais_fatores(importancias, rotulos, n=2)
    assert resultado == "Fator B, Fator C"


# --- App: dados carregados e páginas -----------------------------------------


def test_dados_utentes_carregados_tem_pelo_menos_um_utente():
    assert len(m.DADOS["utentes"]) > 0


def test_cada_utente_tem_avaliacao_diabetes_cardio_e_queda():
    utente = _primeiro_utente()
    assert utente["id_utente"] in m.DADOS["avaliacao_diabetes"].index
    assert utente["id_utente"] in m.DADOS["avaliacao_cardio"].index
    assert utente["id_utente"] in m.DADOS["avaliacao_queda"].index


def test_pagina_utentes_renderiza():
    pagina = m._pagina_utentes()
    assert pagina is not None


def test_pagina_ficha_utente_existente_mostra_nome():
    utente = _primeiro_utente()
    pagina = m._pagina_ficha_utente(utente["id_utente"])
    # o H1 com o nome é o segundo filho (depois da ligação "voltar")
    assert utente["nome"] in str(pagina)


def test_pagina_ficha_utente_inexistente_nao_rebenta():
    pagina = m._pagina_ficha_utente("ID-QUE-NAO-EXISTE")
    assert "não encontrado" in str(pagina).lower()


def test_filtrar_utentes_por_texto():
    utente = _primeiro_utente()
    primeiro_nome = utente["nome"].split()[0]
    resultado = m._filtrar_utentes(primeiro_nome, None, None)
    assert utente["nome"] in str(resultado)


def test_filtrar_utentes_sem_resultado():
    resultado = m._filtrar_utentes("Nome Que Nao Existe De Certeza Absoluta", None, None)
    assert "Nenhum utente encontrado" in str(resultado)


def test_formatar_euros_usa_formato_portugues():
    assert m._formatar_euros(1234.5, 2) == "1.234,50 €"
    assert m._formatar_euros(18755) == "18.755 €"


def test_pagina_ocupacao_renderiza():
    assert m._pagina_ocupacao() is not None


def test_pagina_faturacao_renderiza():
    assert m._pagina_faturacao() is not None


# --- Modelos de risco: previsões plausíveis -----------------------------------


def test_modelo_diabetes_prevé_probabilidade_valida():
    linha = pd.DataFrame([{c: 1.0 for c in m.RES_DIABETES}])
    prob = m.MODELO_DIABETES.predict_proba(linha)[0, 1]
    assert 0.0 <= prob <= 1.0


def test_modelo_cardio_prevé_probabilidade_valida():
    from scripts.treinar_modelo_cardio import COLUNAS_CARDIO

    linha = pd.DataFrame([{c: 1.0 for c in COLUNAS_CARDIO}])
    prob = m.MODELO_CARDIO.predict_proba(linha)[0, 1]
    assert 0.0 <= prob <= 1.0


def test_metricas_dos_modelos_tem_auc_razoavel():
    assert m.METRICAS_DIABETES["auc_conjunto_teste"] > 0.7
    assert m.METRICAS_CARDIO["auc_conjunto_teste"] > 0.7
