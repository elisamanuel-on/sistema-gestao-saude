"""Constantes partilhadas entre app.py e os scripts de geração de dados.

Centralizadas aqui para o tipo de unidade "Clínica/Hospital" (e os módulos
que vieram com ele — consultas, exames, plano de cuidados, seguros) terem
uma única fonte de verdade, em vez de listas duplicadas e a arriscar
divergir entre o gerador de dados e a app.
"""

# Tipos de unidade/cuidado. As três primeiras existiam desde o início
# (inspiração hitCare: UCC/ERPI/SAD, cuidados continuados/residências
# sénior). "Clínica/Hospital" é o módulo novo (inspiração LinkHMS):
# ambulatório, por consulta/especialidade, sem internamento em quarto.
TIPOS_CUIDADO = ["UCC", "ERPI", "SAD", "Clínica/Hospital"]

# Estados possíveis de um utente. "Internado" só se aplica a UCC/ERPI.
# "Em acompanhamento" é o equivalente ambulatório, usado por SAD e por
# Clínica/Hospital (não há cama/quarto associado).
ESTADOS_INTERNAMENTO = ["Internado", "Alta", "Em espera"]
ESTADOS_AMBULATORIO = ["Em acompanhamento", "Alta", "Em espera"]

ESPECIALIDADES = [
    "Clínica Geral",
    "Cardiologia",
    "Ortopedia",
    "Pneumologia",
    "Psiquiatria",
    "Endocrinologia",
    "Neurologia",
    "Ginecologia",
]

# Profissional -> especialidade (só médicos — usado nas consultas do módulo
# Clínica/Hospital). Fisioterapia, enfermagem, nutrição, psicologia e
# serviço social não são especialidades médicas de consulta: entram no
# plano de cuidados multidisciplinar (PROFISSIONAIS_POR_AREA_CUIDADOS)
# e/ou nas visitas, nunca aqui.
PROFISSIONAL_ESPECIALIDADE = {
    "Dr. Ricardo Rocha": "Clínica Geral",
    "Dra. Inês Fonseca": "Cardiologia",
    "Dr. Hugo Teixeira": "Ortopedia",
    "Dr. Nuno Barreto": "Pneumologia",
    "Dra. Carla Nogueira": "Psiquiatria",
    "Dr. Tiago Matos": "Endocrinologia",
    "Dra. Sofia Ramalho": "Neurologia",
    "Dra. Patrícia Gomes": "Ginecologia",
}

PROFISSIONAIS_APOIO = {
    "Enfermagem": ["Enf. Marta Sousa", "Enf. Paulo Cardoso"],
    "Fisioterapia": ["Fisio. Beatriz Lima"],
    "Nutrição": ["Nutric. Renata Alves"],
    "Psicologia": ["Psic. Vera Matos"],
    "Serviço Social": ["Ass. Social Miguel Nunes"],
}

# Profissional "responsável" apropriado para cada área do plano de cuidados
# multidisciplinar — evita atribuir, por exemplo, um ortopedista como
# responsável por um item de enfermagem.
PROFISSIONAIS_POR_AREA_CUIDADOS = {
    "Enfermagem": PROFISSIONAIS_APOIO["Enfermagem"],
    "Medicina": list(PROFISSIONAL_ESPECIALIDADE.keys()),
    "Fisioterapia": PROFISSIONAIS_APOIO["Fisioterapia"],
    "Nutrição": PROFISSIONAIS_APOIO["Nutrição"],
    "Psicologia": PROFISSIONAIS_APOIO["Psicologia"],
    "Serviço Social": PROFISSIONAIS_APOIO["Serviço Social"],
}

PROFISSIONAIS = [
    *PROFISSIONAL_ESPECIALIDADE.keys(),
    *PROFISSIONAIS_APOIO["Enfermagem"],
    *PROFISSIONAIS_APOIO["Fisioterapia"],
    *PROFISSIONAIS_APOIO["Nutrição"],
    *PROFISSIONAIS_APOIO["Psicologia"],
    *PROFISSIONAIS_APOIO["Serviço Social"],
]

# Seguradoras — nomes claramente fictícios (nenhuma marca real), só para dar
# à faturação um cenário de seguro privado além da comparticipação da
# Segurança Social (essa sim, uma entidade real, mas os valores são todos
# sintéticos — ver README).
SEGURADORAS = ["SegurCuidar", "ViverSeguro", "Confiança Saúde", "Proteger+"]

AREAS_PLANO_CUIDADOS = ["Enfermagem", "Medicina", "Fisioterapia", "Nutrição", "Psicologia", "Serviço Social"]

CATEGORIAS_EXAME = ["Análises clínicas", "Imagiologia", "Cardiológico", "Outro"]

TIPOS_EXAME_POR_CATEGORIA = {
    "Análises clínicas": [
        "Hemograma completo", "Perfil lipídico", "Função renal", "Função hepática",
        "Glicemia em jejum", "Hemoglobina glicada (HbA1c)", "Ionograma",
    ],
    "Imagiologia": [
        "Radiografia do tórax", "Ecografia abdominal", "TAC crânio-encefálico",
        "Ressonância magnética lombar", "Densitometria óssea",
    ],
    "Cardiológico": ["Eletrocardiograma", "Ecocardiograma", "Prova de esforço"],
    "Outro": ["Espirometria", "Audiograma", "Exame oftalmológico"],
}

# Perfis de acesso — demonstração de portfólio, sem autenticação real (sem
# palavra-passe nem verificação de identidade). Cada perfil só vê as secções
# de navegação relevantes ao seu papel.
#
# Receção herda exatamente as capacidades do antigo perfil único
# "Administrativo": agenda, marcar/cancelar/reagendar consultas, faturação.
# Admin tem tudo o que a Receção tem, mais a gestão do cadastro de
# profissionais e a visão de relatórios de qualquer profissional (a Receção
# só vê o relatório de uma consulta específica, não a atividade agregada de
# um profissional — isso é informação de gestão, não de front-desk).
PERFIS_ACESSO = ["Enfermeiro", "Médico", "Receção", "Admin"]

SECCOES_POR_PERFIL = {
    "Enfermeiro": ["Início", "Geral", "Cuidados continuados", "Clínica & Hospital", "Relatórios"],
    "Médico": ["Início", "Geral", "Cuidados continuados", "Clínica & Hospital", "Relatórios"],
    "Receção": ["Início", "Geral", "Cuidados continuados", "Clínica & Hospital", "Relatórios", "Faturação"],
    "Admin": ["Início", "Geral", "Cuidados continuados", "Clínica & Hospital", "Relatórios", "Faturação", "Profissionais"],
}

# Perfis com acesso de gestão alargado (usados nas verificações de RBAC ao
# longo do app.py, em vez de comparar sempre com uma string solta).
PERFIS_GESTAO_AGENDA = {"Médico", "Receção", "Admin"}  # podem marcar/cancelar/reagendar consultas
PERFIS_RELATORIO_QUALQUER_PROFISSIONAL = {"Admin"}  # escolhem livremente o profissional no relatório de atividade
PERFIS_SEM_ATOS_CLINICOS = {"Receção"}  # não têm avaliação de risco, prescrições nem receita

# "Profissionais" é gerido à parte — cadastro de pessoal é uma função de
# gestão, reservada ao perfil Admin.

# Ações fictícias para o histórico/auditoria de cada utente (quem alterou o
# quê e quando) — dado sintético, tal como todo o resto (ver README).
ACOES_HISTORICO = [
    "Atualizou sinais vitais", "Registou novo diagnóstico", "Atualizou prescrição",
    "Registou visita", "Atualizou plano de cuidados", "Registou resultado de exame",
    "Agendou consulta", "Alterou estado da consulta", "Consultou avaliação de risco",
    "Atualizou dados de faturação",
]

# --- Cadastro de profissionais -----------------------------------------------
# Categoria da pessoa (o "cargo"), distinta de área do plano de cuidados
# (AREAS_PLANO_CUIDADOS acima) e de especialidade médica (ESPECIALIDADES).
# Só "Médico" tem especialidade médica de consulta — as outras categorias
# entram no plano de cuidados multidisciplinar através de
# CATEGORIA_PARA_AREA_CUIDADOS.
CATEGORIAS_PROFISSIONAL = ["Médico", "Enfermeiro", "Fisioterapeuta", "Nutricionista", "Psicólogo", "Assistente Social"]

CATEGORIA_PARA_AREA_CUIDADOS = {
    "Médico": "Medicina",
    "Enfermeiro": "Enfermagem",
    "Fisioterapeuta": "Fisioterapia",
    "Nutricionista": "Nutrição",
    "Psicólogo": "Psicologia",
    "Assistente Social": "Serviço Social",
}

ESTADOS_PROFISSIONAL = ["Ativo", "Inativo"]

# Salas e horários usados no agendamento de consultas (criar/reagendar).
SALAS_CONSULTA = [f"Sala {n}" for n in range(1, 7)]
HORARIOS_CONSULTA = [f"{h:02d}:{m:02d}" for h in range(8, 19) for m in (0, 30) if not (h == 18 and m == 30)]
