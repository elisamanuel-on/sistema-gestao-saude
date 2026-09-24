"""Construção das páginas e componentes de UI (tudo o que devolve uma
árvore html./dcc.) — sem nenhum @app.callback aqui. Os callbacks (em
callbacks.py) chamam estas funções para (re)desenhar cada página ou secção
depois de uma ação do utilizador."""

import datetime
import json
import urllib.parse

import pandas as pd
import plotly.graph_objects as go
from dash import dash_table, dcc, html

from constantes import (
    CATEGORIAS_PROFISSIONAL,
    ESPECIALIDADES,
    HORARIOS_CONSULTA,
    PERFIS_ACESSO,
    PERFIS_GESTAO_AGENDA,
    PERFIS_GESTAO_UTENTES,
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
)
from nucleo import (
    CORES,
    DADOS,
    ESTADOS_UTENTE,
    ESTILO_CABECALHO_TABELA,
    ESTILO_CELULA_TABELA,
    FUNCIONALIDADES_VITRINE,
    ICONES_PERFIL,
    OPCOES_ECG_REPOUSO,
    OPCOES_INCLINACAO_ST,
    OPCOES_SEXO,
    OPCOES_SIM_NAO,
    OPCOES_TALASSEMIA,
    OPCOES_TIPO_DOR_PEITO,
    ORIENTACAO_POR_PERFIL,
    PASTA_DADOS,
    RES_DIABETES,
    SECCOES_NAVEGACAO,
    TOM_PLANO,
    URL_REPOSITORIO,
    _com_zebra,
    _estatisticas_atividade_profissional,
    _formatar_euros,
    _idade_utente,
    _ids_utentes_risco_elevado,
    _nome_utente,
    _opcoes_relatorio_consulta,
    _slug,
    _stats_profissional,
)

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
                    html.Img(src="/assets/icones/logo.svg", alt="", className="icone-logotipo-lateral"),
                    html.Span("Gestão de Saúde", className="logotipo-lateral-texto"),
                ],
                className="logotipo-lateral",
            ),
            html.Div(seccoes, className="grupo-nav-lateral"),
            html.Div(
                [
                    html.Div(
                        f"Perfil: {perfil}" + (f" ({profissional})" if profissional else ""),
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


def _pagina_login(simulacao=False):
    return html.Div(
        html.Div(
            [
                html.Img(src="/assets/icones/logo.svg", alt="", className="logotipo-login"),
                html.H1("Modo simulação" if simulacao else "Gestão de Saúde"),
                *(
                    [
                        html.P(
                            "Entras diretamente num perfil de demonstração, com os mesmos dados reais do "
                            "sistema. Podes sair a qualquer momento, sem precisar de voltar aqui.",
                            className="texto-explicativo",
                        )
                    ]
                    if simulacao
                    else []
                ),
                dcc.Store(id="perfil-provisorio-login", storage_type="memory"),
                dcc.Store(id="simulacao-login-flag", storage_type="memory", data=simulacao),
                html.Div(id="corpo-login"),
                *([dcc.Link("‹ Voltar à vitrine", href="/vitrine", className="ligacao-voltar")] if simulacao else []),
            ],
            className="cartao-login",
        ),
        className="ecra-login",
    )


def _corpo_login_escolha_perfil():
    botoes = [
        html.Button(
            [html.Img(src=ICONES_PERFIL.get(perfil, ""), alt="", className="icone-perfil-login"), html.Span(perfil)],
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
                "Isto é uma simulação de acesso por perfil para fins de portfólio: não há "
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
            html.P(f"Perfil {perfil}: agora escolhe qual profissional és.", className="texto-explicativo"),
            corpo_lista,
            html.Button("‹ Voltar", id="botao-voltar-login", className="botao-secundario", n_clicks=0),
        ]
    )


def _cartao_funcionalidade_vitrine(icone, titulo, texto):
    return html.Div(
        [
            html.Div(html.Img(src=icone, alt="", className="icone-funcionalidade-vitrine"), className="icone-caixa-vitrine"),
            html.H3(titulo),
            html.P(texto, className="texto-explicativo"),
        ],
        className="cartao-funcionalidade-vitrine",
    )


def _painel_visual_vitrine():
    """Pré-visualização estilizada do dashboard — barras/números fictícios, só
    para sugerir a interface na vitrine, nunca dados reais de um utente."""
    return html.Div(
        [
            html.Div("● Dados sintéticos ao vivo", className="etiqueta-flutuante-vitrine"),
            html.Div(
                [
                    html.Div(className="linha-mock linha-mock--curta"),
                    html.Div(
                        [
                            html.Div([html.Strong("45", className="cor-primaria"), html.Span("Utentes")]),
                            html.Div([html.Strong("27%", className="cor-clinica"), html.Span("Ocupação")]),
                            html.Div([html.Strong("3", className="cor-sad"), html.Span("Consultas hoje")]),
                        ],
                        className="kpis-mini-vitrine",
                    ),
                ],
                className="cartao-mock-vitrine",
            ),
            html.Div(
                [
                    html.Div(className="linha-mock linha-mock--curta"),
                    html.Div(
                        [
                            html.Div(className="barra-mock", style={"height": "60%", "background": "var(--tipo-erpi)"}),
                            html.Div(className="barra-mock", style={"height": "90%", "background": "var(--tipo-clinica-hospital)"}),
                            html.Div(className="barra-mock", style={"height": "40%", "background": "var(--tipo-sad)"}),
                            html.Div(className="barra-mock", style={"height": "75%", "background": "var(--primaria)"}),
                        ],
                        className="barras-mock-vitrine",
                    ),
                ],
                className="cartao-mock-vitrine",
            ),
        ],
        className="painel-visual-vitrine",
    )


def _pagina_vitrine():
    return html.Div(
        html.Div(
            [
                html.Div(
                    [
                        html.Img(src="/assets/icones/logo.svg", alt="", className="logotipo-vitrine"),
                        html.Span("Gestão de Saúde", className="logotipo-vitrine-texto"),
                    ],
                    className="topo-vitrine",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Img(src="/assets/icones/logo.svg", alt="", className="icone-badge-vitrine"),
                                        "Projeto de portfólio",
                                    ],
                                    className="badge-vitrine",
                                ),
                                html.H1(["Gestão de utentes e cuidados de saúde, ", html.Span("num só sistema", className="cor-primaria")]),
                                html.P(
                                    "Cuidados continuados (UCC/ERPI/SAD) e ambulatório clínico/hospitalar, com "
                                    "avaliação de risco por machine learning e acesso por perfil para Enfermeiro, "
                                    "Médico, Receção e Admin.",
                                    className="texto-explicativo texto-lead-vitrine",
                                ),
                                html.Div(
                                    [
                                        dcc.Link("Simulação", href="/simulacao", className="botao-vitrine-primario"),
                                        dcc.Link("Ver o sistema inteiro", href="/login", className="botao-vitrine-secundario"),
                                    ],
                                    className="grupo-botoes-vitrine",
                                ),
                                html.Div(
                                    [
                                        html.Div([html.Strong("4"), html.Span("tipos de unidade")]),
                                        html.Div([html.Strong("3"), html.Span("modelos de risco clínico")]),
                                        html.Div([html.Strong("4"), html.Span("perfis de acesso")]),
                                    ],
                                    className="estatisticas-vitrine",
                                ),
                            ],
                            className="texto-hero-vitrine",
                        ),
                        _painel_visual_vitrine(),
                    ],
                    className="hero-vitrine",
                ),
                html.Div(
                    [_cartao_funcionalidade_vitrine(icone, titulo, texto) for icone, titulo, texto in FUNCIONALIDADES_VITRINE],
                    className="grelha-funcionalidades-vitrine",
                ),
                html.P(
                    "Projeto de portfólio: nenhuma pessoa real está representada, todos os dados são "
                    "sintéticos, e a ferramenta não é um sistema clínico certificado nem substitui "
                    "avaliação por um profissional de saúde.",
                    className="nota-rodape-login nota-rodape-vitrine",
                ),
            ],
            className="conteudo-vitrine",
        ),
        className="ecra-vitrine",
    )


def _banner_simulacao():
    return html.Div(
        [
            html.Div(
                [
                    html.Strong("Modo simulação: "),
                    "estás a ver o sistema com um perfil de demonstração e dados de exemplo, sem "
                    "sessão real. Podes sair a qualquer momento.",
                ]
            ),
            dcc.Link("Ver o sistema inteiro", href="/login", className="botao-secundario"),
        ],
        className="banner-simulacao",
    )


def _linha_alerta(tom, texto, href):
    return dcc.Link(
        html.Div([html.Span(className=f"ponto-alerta ponto-alerta--{tom}"), html.Span(texto)], className="linha-alerta"),
        href=href,
        className="ligacao-alerta",
    )


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
        alertas.append(_linha_alerta("risco_elevado", f"{_nome_utente(id_utente)}: risco clínico elevado por rever", f"/utentes/{id_utente}"))
    alterados = (
        exames[exames["estado"] == "Alterado"]
        .merge(utentes[["id_utente", "nome"]], on="id_utente")
        .sort_values("data", ascending=False)
        .head(5)
    )
    for _idx, ex in alterados.iterrows():
        alertas.append(_linha_alerta("risco_moderado", f"{ex['nome']}: exame \"{ex['tipo_exame']}\" alterado, por rever", f"/utentes/{ex['id_utente']}"))
    if erros_fatura:
        faturas_erro = fat[fat["erro_fatura"]].merge(utentes[["id_utente", "nome"]], on="id_utente").head(5)
        for _idx, fx in faturas_erro.iterrows():
            alertas.append(_linha_alerta("risco_moderado", f"{fx['nome']}: fatura com erro por corrigir", "/faturacao"))

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
                "Ponto de partida com os indicadores mais importantes de todos os módulos: cuidados "
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


def _pagina_sobre(logado=True):
    estatisticas = html.Div(
        [
            _cartao_kpi("Perfis de acesso", len(PERFIS_ACESSO), nota="Enfermeiro, Médico, Receção, Admin"),
            _cartao_kpi("Testes automatizados", 121, nota="pytest, corridos em CI a cada push"),
            _cartao_kpi("Avaliações de risco clínico", 3, nota="diabetes, cardiovascular e queda"),
            _cartao_kpi("Tipos de unidade", len(TIPOS_CUIDADO), nota="UCC, ERPI, SAD, Clínica/Hospital"),
        ],
        className="kpis-linha",
    )

    cabecalho = [html.H1("Sobre este projeto")]
    if not logado:
        cabecalho.insert(0, dcc.Link("‹ Voltar à vitrine", href="/vitrine", className="ligacao-voltar"))

    return html.Div(
        [
            *cabecalho,
            html.P(
                "Projeto de portfólio: um sistema de gestão de utentes e cuidados de saúde que combina dois "
                "contextos, cuidados continuados/residências sénior (UCC/ERPI/SAD) e ambulatório clínico/"
                "hospitalar (Clínica/Hospital), com avaliação de risco clínico por machine learning.",
                className="texto-explicativo",
            ),
            estatisticas,
            html.Div(
                [
                    html.H3("O que inclui"),
                    html.Ul(
                        [
                            html.Li("Registo de utentes para os 4 tipos de unidade, com pesquisa e filtros."),
                            html.Li(
                                "Ficha clínica: sinais vitais, alergias/diagnósticos, exames, prescrições, plano de "
                                "cuidados multidisciplinar, visitas, documentos e histórico/auditoria, com "
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
                ],
                className="cartao-secao",
            ),
            html.Div(
                [
                    html.H3("Sobre os dados"),
                    html.P(
                        "Nenhuma pessoa real está representada: todos os utentes, profissionais e dados clínicos são "
                        "gerados sinteticamente. Os valores usados para pré-preencher a avaliação de risco vêm de dois "
                        "datasets públicos e anonimizados (Pima Indians Diabetes, UCI Heart Disease), usados só para "
                        "manter distribuições realistas, nunca de pacientes reais.",
                        className="texto-explicativo",
                    ),
                    _aviso_medico(),
                ],
                className="cartao-secao",
            ),
            html.Div(
                [
                    html.H3("Stack técnica"),
                    html.P(
                        "Python, Dash + Plotly (interface e gráficos), scikit-learn (modelos de risco), pandas "
                        "(dados), reportlab (exportação em PDF), pytest (testes automatizados) e deploy no Render.",
                        className="texto-explicativo",
                    ),
                    html.A(
                        "Ver o código fonte no GitHub →",
                        href=URL_REPOSITORIO,
                        target="_blank",
                        rel="noopener noreferrer",
                        className="ligacao-voltar",
                    ),
                ],
                className="cartao-secao",
            ),
        ]
    )


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


def _formulario_novo_utente():
    return html.Details(
        [
            html.Summary("+ Novo Utente", className="resumo-details"),
            html.Div(
                [
                    dcc.Input(id="form-utente-nome", type="text", placeholder="Nome completo", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="form-utente-genero",
                        options=[{"label": g, "value": g} for g in ["Feminino", "Masculino"]],
                        placeholder="Género",
                        className="filtro-dropdown",
                    ),
                    dcc.DatePickerSingle(
                        id="form-utente-nascimento",
                        placeholder="Data de nascimento",
                        display_format="DD/MM/YYYY",
                        month_format="MM/YYYY",
                        first_day_of_week=1,
                        max_date_allowed=datetime.date.today(),
                    ),
                    dcc.Dropdown(
                        id="form-utente-tipo-cuidado",
                        options=[{"label": t, "value": t} for t in TIPOS_CUIDADO],
                        placeholder="Tipo de cuidado",
                        className="filtro-dropdown",
                    ),
                    dcc.DatePickerSingle(
                        id="form-utente-admissao",
                        placeholder="Data de admissão",
                        display_format="DD/MM/YYYY",
                        month_format="MM/YYYY",
                        first_day_of_week=1,
                        max_date_allowed=datetime.date.today(),
                    ),
                ],
                className="grelha-formulario",
            ),
            html.Button("Adicionar utente", id="botao-criar-utente", className="botao-primario", n_clicks=0),
            html.Div(id="mensagem-criar-utente", className="resultado-mini"),
        ],
        className="painel-details",
    )


def _painel_gerir_utente():
    return html.Div(
        [
            html.H3("Gerir utente"),
            html.P("Alterar o quarto ou o estado de um utente já registado, ou dar-lhe alta.", className="texto-explicativo"),
            dcc.Dropdown(id="select-utente-gerir", placeholder="Escolhe um utente...", className="filtro-dropdown"),
            html.Div(
                [
                    dcc.Input(id="form-utente-editar-quarto", type="text", placeholder="Novo quarto (deixa em branco para não alterar)", className="campo-pesquisa"),
                    dcc.Dropdown(
                        id="form-utente-editar-estado",
                        options=[{"label": e, "value": e} for e in ESTADOS_UTENTE],
                        placeholder="Novo estado (deixa em branco para não alterar)",
                        className="filtro-dropdown",
                    ),
                ],
                className="grelha-formulario",
            ),
            html.Div(
                [
                    html.Button("Guardar alterações", id="botao-editar-utente", className="botao-secundario", n_clicks=0),
                    html.Button("Dar Alta", id="botao-dar-alta-utente", className="botao-secundario", n_clicks=0),
                ],
                className="botoes-exportar",
            ),
            html.Div(id="mensagem-gerir-utente", className="resultado-mini"),
        ],
        className="cartao-secao",
    )


def _pagina_utentes(perfil=None):
    df = DADOS["utentes"]
    total = len(df)
    ativos = int(df["estado"].isin(["Internado", "Em acompanhamento"]).sum())
    em_espera = int((df["estado"] == "Em espera").sum())
    altas_mes = len(DADOS["altas"])
    pode_gerir = perfil in PERFIS_GESTAO_UTENTES

    return html.Div(
        [
            html.H1("Utentes"),
            html.P(
                "Registo único para todos os tipos de unidade: cuidados continuados (UCC/ERPI/SAD) e "
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
            *([_formulario_novo_utente()] if pode_gerir else []),
            dcc.Store(id="utentes-atualizacao", data=0),
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
            *([_painel_gerir_utente()] if pode_gerir else []),
        ]
    )


def _aba_resumo(id_utente, utente):
    idade = _idade_utente(utente["data_nascimento"])
    ultimos_vitais = DADOS["vitais"][DADOS["vitais"]["id_utente"] == id_utente].sort_values("data_hora").tail(1)
    ultima_glicemia = f"{int(ultimos_vitais['glicemia'].iloc[0])} mg/dL" if len(ultimos_vitais) else "N/D"
    ultimo_peso = f"{ultimos_vitais['peso_kg'].iloc[0]:.1f} kg" if len(ultimos_vitais) else "N/D"
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
                    html.Img(src="/assets/icones/documento.svg", alt="", className="icone-documento"),
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
                    _etiqueta_tom(f"{item['estado']} ({item['progresso_percent']}%)", tom),
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
                        "Calcula pelo menos um dos riscos acima e depois gera o resumo: motor de "
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
                    " não usa mapa de camas: é ambulatório, organizado por marcação. Ver ",
                    dcc.Link("Consultas", href="/consultas"),
                    ".",
                ],
                className="texto-explicativo nota-modulo-cruzado",
            ),
        ]
    )


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
            html.P("Agendamento do módulo Clínica/Hospital: ambulatório, organizado por especialidade e profissional.", className="texto-explicativo"),
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


def _pagina_faturacao():
    fat = DADOS["faturacao"].merge(DADOS["utentes"][["id_utente", "nome", "tipo_cuidado"]], on="id_utente")

    total_a_pagar = fat["valor_a_pagar_utente"].sum()
    total_comparticipacao = fat["comparticipacao_ss"].sum()
    total_ars = (fat["ars_diarias_internamento"] + fat["ars_pacote_medicamentos"] + fat["ars_remuneracao_adicional"]).sum()
    total_seguradoras = fat["valor_seguradora"].sum()
    utentes_com_seguro = int((fat["seguradora"] != "N/D").sum())
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
                f"{stats['taxa_comparencia']:.0f}%" if stats["taxa_comparencia"] is not None else "N/D",
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
                    html.Td(p["especialidade"] or "N/D"),
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
                "Cadastro da equipa: médicos (com especialidade, para as consultas) e a equipa de apoio "
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
                "Documentação e exportação: atividade de um profissional (Médico/Enfermeiro veem só a sua, "
                "Admin escolhe qualquer um) ou o resumo de uma consulta específica.",
                className="texto-explicativo",
            ),
            *([secao_atividade] if mostrar_atividade else []),
            secao_consulta,
        ]
    )


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



__all__ = [
    "_cartao_kpi",
    "_aviso_medico",
    "_barra_lateral",
    "_etiqueta_tipo_cuidado",
    "_etiqueta_tom",
    "_pagina_login",
    "_corpo_login_escolha_perfil",
    "_corpo_login_escolha_profissional",
    "_cartao_funcionalidade_vitrine",
    "_painel_visual_vitrine",
    "_pagina_vitrine",
    "_banner_simulacao",
    "_linha_alerta",
    "_banner_orientacao",
    "_pagina_visao_geral",
    "_pagina_sobre",
    "_tabela_utentes",
    "_formulario_novo_utente",
    "_painel_gerir_utente",
    "_pagina_utentes",
    "_aba_resumo",
    "_aba_vitais",
    "_aba_alergias_diagnosticos",
    "_aba_prescricoes",
    "_formulario_nova_prescricao",
    "_corpo_prescricoes",
    "_aba_visitas",
    "_aba_documentos",
    "_aba_exames",
    "_aba_plano_cuidados",
    "_aba_historico",
    "_campo_numerico",
    "_campo_dropdown",
    "_sub_cartao_diabetes",
    "_sub_cartao_cardio",
    "_sub_cartao_queda",
    "_aba_avaliacao_risco",
    "_pagina_ficha_utente",
    "_pagina_ocupacao",
    "_tabela_consultas",
    "_formulario_nova_consulta",
    "_painel_gerir_consulta",
    "_inicio_semana_atual",
    "_vista_calendario_consultas",
    "_pagina_consultas",
    "_pagina_faturacao",
    "_corpo_relatorio_atividade",
    "_tabela_profissionais",
    "_formulario_novo_profissional",
    "_painel_gerir_profissional",
    "_pagina_profissionais",
    "_pagina_relatorios",
    "_construir_layout",
]
