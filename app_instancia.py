"""Cria a instância única do Dash (e do servidor Flask por trás dela). Vive
num módulo à parte, minúsculo, só para os outros módulos (paginas,
callbacks) poderem fazer `from app_instancia import app` sem cair num
import circular com app.py (o próprio ponto de entrada, que por sua vez
importa callbacks para registar os callbacks contra este `app`)."""

import dash

app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Sistema de Gestão de Utentes"
server = app.server
