"""Todos os @app.callback do sistema: sessão/login, navegação e
roteamento, agendamento de consultas, prescrições e receita, relatórios,
profissionais, utentes, sinais vitais, avaliação de risco e faturação.
Chamam as funções de paginas.py para (re)desenhar UI e as de exportacoes.py
para gerar os ficheiros de download."""

import datetime
import logging

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html

from app_instancia import app
from riscos import calcular_risco_queda, classificar_risco, gerar_resumo_ia, principais_fatores
from scripts.treinar_modelo_cardio import COLUNAS_CARDIO
from nucleo import (
    COLUNAS_EXPORTACAO_FATURACAO,
    CORES,
    DADOS,
    ESTADOS_UTENTE,
    ESTADOS_VALIDOS_POR_TIPO,
    MODELO_CARDIO,
    MODELO_DIABETES,
    METRICAS_CARDIO,
    METRICAS_DIABETES,
    OPCOES_ECG_REPOUSO,
    OPCOES_INCLINACAO_ST,
    OPCOES_SEXO,
    OPCOES_SIM_NAO,
    OPCOES_TALASSEMIA,
    OPCOES_TIPO_DOR_PEITO,
    PERFIS_COM_PROFISSIONAL,
    RES_CARDIO,
    RES_DIABETES,
    _conflito_consulta,
    _dados_sessao,
    _e_simulacao,
    _gerar_numero_processo,
    _nome_utente,
    _profissional_tem_historico,
    _proximo_id_consulta,
    _proximo_id_prescricao,
    _proximo_id_utente,
    _registar_historico,
    _slug,
)
from paginas import (
    _banner_simulacao,
    _barra_lateral,
    _corpo_login_escolha_perfil,
    _corpo_login_escolha_profissional,
    _corpo_prescricoes,
    _corpo_relatorio_atividade,
    _inicio_semana_atual,
    _pagina_consultas,
    _pagina_faturacao,
    _pagina_ficha_utente,
    _pagina_login,
    _pagina_ocupacao,
    _pagina_profissionais,
    _pagina_relatorios,
    _pagina_sobre,
    _pagina_utentes,
    _pagina_vitrine,
    _pagina_visao_geral,
    _tabela_consultas,
    _tabela_profissionais,
    _tabela_utentes,
    _vista_calendario_consultas,
)
from exportacoes import (
    _gerar_excel_faturacao,
    _gerar_excel_relatorio_atividade,
    _gerar_excel_relatorio_consulta,
    _gerar_pdf_ficha,
    _gerar_pdf_receita,
    _gerar_pdf_relatorio_atividade,
    _gerar_pdf_relatorio_consulta,
)

logger = logging.getLogger(__name__)


@app.callback(
    Output("perfil-provisorio-login", "data", allow_duplicate=True),
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input({"type": "botao-login-perfil", "perfil": ALL}, "n_clicks"),
    State("simulacao-login-flag", "data"),
    prevent_initial_call=True,
)
def _escolher_perfil_login(cliques, simulacao):
    if not ctx.triggered_id or not any(cliques):
        return dash.no_update, dash.no_update, dash.no_update
    perfil = ctx.triggered_id["perfil"]
    if perfil not in PERFIS_COM_PROFISSIONAL:
        # Receção/Admin não têm identidade de profissional — entram logo.
        logger.info("Sessão iniciada: perfil=%s simulacao=%s", perfil, bool(simulacao))
        return dash.no_update, {"perfil": perfil, "profissional": None, "simulacao": bool(simulacao)}, "/"
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
    State("simulacao-login-flag", "data"),
    prevent_initial_call=True,
)
def _escolher_profissional_login(cliques, perfil_provisorio, simulacao):
    if not ctx.triggered_id or not any(cliques) or not perfil_provisorio:
        return dash.no_update, dash.no_update
    logger.info(
        "Sessão iniciada: perfil=%s profissional=%s simulacao=%s",
        perfil_provisorio, ctx.triggered_id["nome"], bool(simulacao),
    )
    return {"perfil": perfil_provisorio, "profissional": ctx.triggered_id["nome"], "simulacao": bool(simulacao)}, "/"


@app.callback(Output("corpo-login", "children"), Input("perfil-provisorio-login", "data"))
def _renderizar_corpo_login(perfil_provisorio):
    if perfil_provisorio:
        return _corpo_login_escolha_profissional(perfil_provisorio)
    return _corpo_login_escolha_perfil()


@app.callback(
    Output("perfil-sessao", "data", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input("botao-sair-sessao", "n_clicks"),
    State("perfil-sessao", "data"),
    prevent_initial_call=True,
)
def _sair_sessao(n_clicks, sessao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    # Uma sessão de simulação volta para a vitrine (é de lá que veio); uma sessão
    # real volta para o login, tal como sempre.
    destino = "/vitrine" if _e_simulacao(sessao) else "/login"
    logger.info("Sessão terminada, a voltar para %s", destino)
    return None, destino


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


@app.callback(Output("barra-lateral-app", "children"), Input("url", "pathname"), Input("perfil-sessao", "data"))
def _atualizar_barra_lateral(caminho, sessao):
    perfil, profissional = _dados_sessao(sessao)
    if not perfil or (caminho or "/") in ("/vitrine", "/simulacao", "/login"):
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
    conteudo = _conteudo_rota(caminho, query_search, sessao, perfil, profissional, onboarding_dispensada)
    # O aviso de "Modo simulação" aparece em todas as páginas de uma sessão de
    # simulação, exceto nas públicas (vitrine/simulação/login) — lá já é óbvio
    # que ainda não se entrou em nenhuma área da app.
    if perfil and _e_simulacao(sessao) and caminho not in ("/vitrine", "/simulacao", "/login"):
        return html.Div([_banner_simulacao(), conteudo])
    return conteudo


def _conteudo_rota(caminho, query_search, sessao, perfil, profissional, onboarding_dispensada):
    if caminho == "/vitrine":
        return _pagina_vitrine()
    if caminho == "/simulacao":
        return _pagina_login(simulacao=True)
    if caminho == "/login":
        return _pagina_login()
    if not perfil:
        # A vitrine é a porta de entrada pública; o /sobre também fica aberto
        # sem sessão (é o link que se partilha diretamente, ex.: num CV) —
        # qualquer outro caminho sem sessão cai no login real, tal como antes.
        if caminho == "/":
            return _pagina_vitrine()
        if caminho == "/sobre":
            return _pagina_sobre(logado=False)
        return _pagina_login()
    if caminho == "/":
        return _pagina_visao_geral(perfil, onboarding_dispensada)
    if caminho == "/utentes":
        return _pagina_utentes(perfil)
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
    Input("utentes-atualizacao", "data"),
)
def _filtrar_utentes(texto_pesquisa, tipo_cuidado, estado, _versao=None):
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
    logger.info("Consulta criada: utente=%s profissional=%s em %s", id_utente, profissional, data_hora)

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
        return html.Div("Consulta não encontrada, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta, "estado"] = "Cancelada"
    _registar_historico(linha.iloc[0]["id_utente"], linha.iloc[0]["profissional"], "Alterou estado da consulta")
    logger.info("Consulta cancelada: %s", id_consulta)
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
        return html.Div("Consulta não encontrada, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update

    profissional = linha.iloc[0]["profissional"]
    nova_data_hora = pd.Timestamp(f"{data} {hora}")
    if _conflito_consulta(profissional, sala, nova_data_hora, excluir_id=id_consulta):
        return (
            html.Div("Já existe uma consulta marcada para este profissional ou esta sala a essa hora.", className="resultado-inline resultado-inline--risco_elevado"),
            dash.no_update,
        )

    DADOS["consultas"].loc[DADOS["consultas"]["id_consulta"] == id_consulta, ["data_hora", "sala"]] = [nova_data_hora, sala]
    _registar_historico(linha.iloc[0]["id_utente"], profissional, "Alterou estado da consulta")
    logger.info("Consulta reagendada: %s para %s", id_consulta, nova_data_hora)
    mensagem = f"Consulta reagendada para {nova_data_hora.strftime('%d/%m/%Y %H:%M')}."
    return html.Div(mensagem, className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


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
    logger.info("Prescrição registada: utente=%s medicamento=%s por %s", id_utente, medicamento, profissional)

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
        return dash.no_update, html.Div("Prescrição não encontrada, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
    return dcc.send_bytes(lambda b: b.write(pdf_bytes), f"receita_{id_prescricao}.pdf"), ""


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
        return dash.no_update, html.Div("Consulta não encontrada, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
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
        return dash.no_update, html.Div("Consulta não encontrada, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado")
    return dcc.send_bytes(lambda b: b.write(conteudo), f"relatorio_{id_consulta}.xlsx"), ""


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
            html.Div("Escolhe a especialidade: é obrigatória para a categoria Médico.", className="resultado-inline resultado-inline--risco_moderado"),
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
                "contacto": contacto or "N/D",
                "numero_cedula": cedula or "N/D",
                "data_admissao": admissao or datetime.date.today().isoformat(),
                "estado": "Ativo",
            }
        ]
    )
    DADOS["profissionais"] = pd.concat([DADOS["profissionais"], nova_linha], ignore_index=True)
    logger.info("Profissional criado: %s (%s)", nome, categoria)
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
        return html.Div("Profissional não encontrado, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
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
            html.Div(f"{nome} não é Médico: a especialidade só se aplica a essa categoria; os outros campos foram guardados.", className="resultado-inline resultado-inline--risco_moderado"),
            (versao or 0) + 1,
        )
    logger.info("Profissional editado: %s", nome)
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
        return html.Div("Profissional não encontrado, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    atual = DADOS["profissionais"].loc[mascara, "estado"].iloc[0]
    novo_estado = "Inativo" if atual == "Ativo" else "Ativo"
    DADOS["profissionais"].loc[mascara, "estado"] = novo_estado
    logger.info("Profissional %s passou a %s", nome, novo_estado)
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
            f"{nome} tem consultas, plano de cuidados ou outro histórico associado: não pode ser removido "
            "para não partir esses registos. Marca como Inativo em vez de remover."
        )
        return html.Div(mensagem, className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    if nome not in DADOS["profissionais"]["nome"].values:
        return html.Div("Profissional não encontrado, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    DADOS["profissionais"] = DADOS["profissionais"][DADOS["profissionais"]["nome"] != nome].reset_index(drop=True)
    logger.info("Profissional removido: %s", nome)
    return html.Div(f"{nome} removido.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("select-utente-gerir", "options"),
    Input("utentes-atualizacao", "data"),
)
def _atualizar_opcoes_utente_gerir(_versao):
    df = DADOS["utentes"].sort_values("nome")
    return [{"label": f"{u['nome']} ({u['id_utente']})", "value": u["id_utente"]} for _idx, u in df.iterrows()]


@app.callback(
    Output("mensagem-criar-utente", "children"),
    Output("utentes-atualizacao", "data", allow_duplicate=True),
    Input("botao-criar-utente", "n_clicks"),
    State("form-utente-nome", "value"),
    State("form-utente-genero", "value"),
    State("form-utente-nascimento", "date"),
    State("form-utente-tipo-cuidado", "value"),
    State("form-utente-admissao", "date"),
    State("utentes-atualizacao", "data"),
    prevent_initial_call=True,
)
def _criar_utente(n_clicks, nome, genero, nascimento, tipo_cuidado, admissao, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    nome = (nome or "").strip()
    if not nome or not genero or not nascimento or not tipo_cuidado:
        return html.Div("Preenche pelo menos o nome, o género, a data de nascimento e o tipo de cuidado.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update

    nova_linha = pd.DataFrame(
        [
            {
                "id_utente": _proximo_id_utente(),
                "nome": nome,
                "genero": genero,
                "data_nascimento": nascimento,
                "processo": _gerar_numero_processo(),
                "tipo_cuidado": tipo_cuidado,
                "data_admissao": admissao or datetime.date.today().isoformat(),
                "quarto": "N/D",
                "estado": "Em espera",
            }
        ]
    )
    DADOS["utentes"] = pd.concat([DADOS["utentes"], nova_linha], ignore_index=True)
    logger.info("Utente registado: %s (%s)", nome, tipo_cuidado)
    return html.Div(f"Utente {nome} registado, com o estado \"Em espera\".", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-utente", "children"),
    Output("utentes-atualizacao", "data", allow_duplicate=True),
    Input("botao-editar-utente", "n_clicks"),
    State("select-utente-gerir", "value"),
    State("form-utente-editar-quarto", "value"),
    State("form-utente-editar-estado", "value"),
    State("utentes-atualizacao", "data"),
    prevent_initial_call=True,
)
def _editar_utente(n_clicks, id_utente, quarto, estado, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_utente:
        return html.Div("Escolhe primeiro um utente.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    mascara = DADOS["utentes"]["id_utente"] == id_utente
    if not mascara.any():
        return html.Div("Utente não encontrado, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    if not any([quarto, estado]):
        return html.Div("Preenche pelo menos um campo para atualizar.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update

    nome = DADOS["utentes"].loc[mascara, "nome"].iloc[0]
    if quarto:
        DADOS["utentes"].loc[mascara, "quarto"] = quarto
    if estado:
        tipo_cuidado = DADOS["utentes"].loc[mascara, "tipo_cuidado"].iloc[0]
        estados_validos = ESTADOS_VALIDOS_POR_TIPO.get(tipo_cuidado, set(ESTADOS_UTENTE))
        DADOS["utentes"].loc[mascara, "estado"] = estado
        if estado not in estados_validos:
            logger.warning("Utente %s passou a estado pouco habitual para %s: %s", nome, tipo_cuidado, estado)
            return (
                html.Div(
                    f"{nome} passou a \"{estado}\", mas repara que este estado não é o habitual para {tipo_cuidado}: confirma se é mesmo isso.",
                    className="resultado-inline resultado-inline--risco_moderado",
                ),
                (versao or 0) + 1,
            )
    logger.info("Utente editado: %s (quarto=%s estado=%s)", nome, quarto, estado)
    return html.Div(f"Dados de {nome} atualizados.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


@app.callback(
    Output("mensagem-gerir-utente", "children", allow_duplicate=True),
    Output("utentes-atualizacao", "data", allow_duplicate=True),
    Input("botao-dar-alta-utente", "n_clicks"),
    State("select-utente-gerir", "value"),
    State("utentes-atualizacao", "data"),
    prevent_initial_call=True,
)
def _dar_alta_utente(n_clicks, id_utente, versao):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not id_utente:
        return html.Div("Escolhe primeiro um utente.", className="resultado-inline resultado-inline--risco_moderado"), dash.no_update
    mascara = DADOS["utentes"]["id_utente"] == id_utente
    if not mascara.any():
        return html.Div("Utente não encontrado, a lista pode ter mudado.", className="resultado-inline resultado-inline--risco_elevado"), dash.no_update
    nome = DADOS["utentes"].loc[mascara, "nome"].iloc[0]
    DADOS["utentes"].loc[mascara, "estado"] = "Alta"
    logger.info("Utente com alta: %s", nome)
    return html.Div(f"{nome} passou a Alta.", className="resultado-inline resultado-inline--risco_baixo"), (versao or 0) + 1


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
    resultado = html.Div([html.Strong(classificacao), f" ({probabilidade:.0%})"], className=f"resultado-inline resultado-inline--{tom}")
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
    resultado = html.Div([html.Strong(classificacao), f" ({probabilidade:.0%})"], className=f"resultado-inline resultado-inline--{tom}")
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
    resultado = html.Div([html.Strong(classificacao), f" (Morse {pontuacao}/125)"], className=f"resultado-inline resultado-inline--{tom}")
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

__all__ = [
    "_escolher_perfil_login",
    "_voltar_login",
    "_escolher_profissional_login",
    "_renderizar_corpo_login",
    "_sair_sessao",
    "_dispensar_orientacao",
    "_atualizar_barra_lateral",
    "_rotear_pagina",
    "_conteudo_rota",
    "_filtrar_utentes",
    "_filtrar_consultas",
    "_navegar_semana_consultas",
    "_profissionais_disponiveis_para_especialidade",
    "_criar_consulta",
    "_opcoes_consultas_para_gerir",
    "_cancelar_consulta",
    "_reagendar_consulta",
    "_renderizar_prescricoes",
    "_criar_prescricao",
    "_descarregar_receita_pdf",
    "_atualizar_corpo_relatorio_atividade",
    "_descarregar_pdf_relatorio_atividade",
    "_descarregar_excel_relatorio_atividade",
    "_descarregar_pdf_relatorio_consulta",
    "_descarregar_excel_relatorio_consulta",
    "_atualizar_tabela_profissionais",
    "_opcoes_profissionais_para_gerir",
    "_criar_profissional",
    "_editar_profissional",
    "_alternar_estado_profissional",
    "_remover_profissional",
    "_atualizar_opcoes_utente_gerir",
    "_criar_utente",
    "_editar_utente",
    "_dar_alta_utente",
    "_atualizar_grafico_vitais",
    "_calcular_diabetes_tab",
    "_calcular_cardio_tab",
    "_calcular_queda_tab",
    "_descarregar_csv_faturacao",
    "_descarregar_excel_faturacao",
    "_gerar_resumo",
    "_descarregar_pdf_ficha",
]
