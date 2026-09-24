"""Sistema de Gestão de Utentes e Cuidados de Saúde — projeto de portfólio.

Inspirado (só na ideia funcional, nunca na marca/design) em dois produtos
reais pesquisados antes de construir isto: hitCare (hitEcosystem), software
português para UCC/ERPI/SAD com mapas de ocupação/altas e faturação com a
Segurança Social, e LinkHMS, um sistema hospitalar com ficha clínica por
paciente (EMR, exames, consultas). Nada aqui reproduz o logótipo, as cores
de marca ou o layout exato de nenhum dos dois — é uma implementação
original, que cobre os dois tipos de contexto: cuidados continuados
(UCC/ERPI/SAD) e ambulatório clínico/hospitalar.

Módulos, navegação lateral agrupada por contexto (visível/oculta consoante
o perfil de acesso escolhido no login — Enfermeiro, Médico, Receção ou
Admin, uma simulação sem autenticação real):
  /login              — escolha de perfil (mock, sem palavra-passe)
  /                   — Visão Geral: KPIs agregados de todos os módulos e
                         painel de alertas (risco elevado, exames por rever,
                         faturas com erro)
  /utentes            — lista de utentes de todas as unidades (pesquisa/filtro)
  /utentes/<id>       — ficha do utente: resumo, sinais vitais, alergias &
                         diagnósticos, exames, prescrições, plano de cuidados
                         multidisciplinar, visitas, documentos, histórico/
                         auditoria, e avaliação de risco (diabetes +
                         cardiovascular, por machine learning, + risco de
                         queda pela Morse Fall Scale — instrumento clínico
                         publicado), com um resumo automático em linguagem
                         natural (motor de regras local, sem API externa)
                         para o profissional ler em segundos antes de
                         decidir, e exportação da ficha em PDF.
  /ocupacao           — capacidade, ocupação e altas (cuidados continuados)
  /consultas          — agendamento/consultas (módulo Clínica/Hospital),
                         em vista de lista ou de calendário semanal
  /faturacao          — valores a pagar, comparticipação, ARS, seguros,
                         saldos, exportação em Excel (.xlsx) ou CSV
  /profissionais      — cadastro de profissionais (médicos + equipa de
                         apoio): adicionar, editar, marcar inativo/ativo,
                         remover (bloqueado se houver histórico associado)
  /relatorios         — relatório de atividade profissional e relatório de
                         consulta, em PDF/Excel
  /sobre              — sobre este projeto (para quem abre o link direto)

Nota sobre persistência: não há base de dados — os dados vivem em memória,
carregados uma vez a partir dos CSV no arranque do servidor. Consultas
criadas/canceladas/reagendadas e profissionais adicionados/editados/
removidos pela própria aplicação ficam só nessa memória: refletem-se
imediatamente para quem estiver a usar o sistema, mas perdem-se se o
servidor reiniciar. Decisão de âmbito consciente para um projeto de
portfólio — ver README.

Dados: tudo sintético (ver scripts/gerar_dados_utentes.py e constantes.py).
Os modelos de risco são treinados em datasets públicos e anonimizados (Pima
Diabetes, UCI Heart Disease) — nenhuma pessoa real, utente ou paciente está
representada em nenhum ficheiro deste projeto, e as seguradoras que
aparecem na faturação têm nomes inventados (nenhuma marca real). Esta
ferramenta é uma demonstração técnica de portfólio, não um sistema clínico
certificado.

Organização do código (módulos, por ordem de dependência — cada um só
importa dos que vêm antes desta lista, nunca ao contrário, para não haver
imports circulares):
  nucleo.py         — dados (DADOS, modelos treinados) + constantes +
                       funções auxiliares partilhadas. Sem Dash.
  paginas.py        — construção de cada página/componente (html./dcc.).
                       Sem @app.callback.
  exportacoes.py     — geração dos PDF/Excel descarregáveis.
  app_instancia.py  — a instância do Dash (app, server) — módulo à parte só
                       para evitar um import circular com callbacks.py.
  callbacks.py      — todos os @app.callback, que ligam a interação do
                       utilizador às páginas e exportações acima.
  app.py (este)     — ponto de entrada: junta tudo, define o layout e
                       arranca o servidor (ou expõe `server` para o gunicorn
                       usar em produção).
"""

import logging

# Configurado antes de qualquer import dos módulos da app: o carregamento
# dos dados/modelos em nucleo.py já regista logs (nível INFO) no momento em
# que é importado a seguir, por isso o logging tem de estar pronto primeiro.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from app_instancia import app, server  # noqa: F401,E402 - `server` é o alvo do gunicorn ("app:server"), não usado neste ficheiro
from nucleo import *  # noqa: F401,F403,E402 - reexportado para uso externo (testes) e por conveniência
from paginas import *  # noqa: F401,F403,E402
from exportacoes import *  # noqa: F401,F403,E402
from callbacks import *  # noqa: F401,F403,E402

app.layout = _construir_layout  # noqa: F405 - vem de paginas.py, importado acima via "from paginas import *"


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8051)
