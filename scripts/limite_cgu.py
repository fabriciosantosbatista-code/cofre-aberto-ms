#!/usr/bin/env python3
"""
Cofre Aberto MS — limite de requisições da API do Portal da Transparência (CGU)

A CGU aceita 400 requisições por minuto durante o dia e 700 entre 0h e 6h (horário de Brasília); passar disso
suspende o token. Todo acesso do robô à api.portaldatransparencia.gov.br passa por esperar_vez(), que mantém uma
janela deslizante de 60 s e nunca passa de 300 por minuto (folga sobre os 400 do dia; à noite também fica em 300).

  chave()        PORTAL_TRANSPARENCIA_API_KEY (secret do GitHub); None sem chave
  esperar_vez()  dorme o necessário antes de cada requisição
"""
import collections, os, random, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo

TETO = 300  # folga: no máximo 300/min em qualquer horário
_feitas = collections.deque()
_trava = threading.Lock()


def chave():
    return (os.environ.get("PORTAL_TRANSPARENCIA_API_KEY") or "").strip() or None


def limite_por_minuto(agora=None):
    h = (agora or datetime.now(ZoneInfo("America/Sao_Paulo"))).hour
    return min(TETO, 700 if 0 <= h < 6 else 400)  # 0h–5h59: 700 · 6h–23h59: 400 · com folga: 300


def esperar_vez(agora=None, relogio=time.monotonic, dormir=time.sleep):
    with _trava:
        lim = limite_por_minuto(agora)
        while True:
            t = relogio()
            while _feitas and t - _feitas[0] >= 60:
                _feitas.popleft()
            if len(_feitas) < lim:
                _feitas.append(t)
                return
            dormir(60 - (t - _feitas[0]) + 0.05)


def espera_429(retry_after=None):
    """Segundos de espera depois de um 429: o Retry-After da resposta (limitado a 5 min) ou 30–60 s."""
    try:
        return min(300.0, max(1.0, float(retry_after)))
    except (TypeError, ValueError):
        return random.uniform(30, 60)
