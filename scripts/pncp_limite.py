#!/usr/bin/env python3
"""
Cofre Aberto MS — limite adaptativo de consultas simultâneas ao PNCP (coletores de Shows e Aluguéis)

O PNCP responde 429 quando recebe consultas demais. Começa com 3 consultas ao mesmo tempo; a cada 429 cai uma (até 1);
depois de 5 minutos sem 429 sobe uma de volta (no máximo 3). O Retry-After é sempre respeitado (sem ele: 30–60 s).
Os pools de threads dos coletores não mudam — o limite segura quantas consultas saem de fato ao mesmo tempo.

  requisitar(url, **kw)  requests.get com o limite (a resposta 429 já reduz o limite)
  espera_429(resp)       segundos a esperar depois de um 429
  esperar(seg)           dorme e soma no tempo total de espera
  resumo()               linha para o log: 429, espera total, limite final, duração
"""
import random, threading, time

import requests

MAXIMO, MINIMO, SUBIR_APOS = 3, 1, 5 * 60


class Limite:
    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self.atual = MAXIMO
        self.em_uso = 0
        self.ultimo_429 = None
        self.ultima_mudanca = relogio()
        self.n429 = 0
        self.espera_total = 0.0
        self.inicio = relogio()
        self.cond = threading.Condition()

    def _talvez_subir(self):
        t = self.relogio()
        ref = max(self.ultimo_429 or self.inicio, self.ultima_mudanca)
        if self.atual < MAXIMO and t - ref >= SUBIR_APOS:
            self.atual += 1
            self.ultima_mudanca = t
            print(f"  PNCP: 5 min sem 429 — até {self.atual} consultas ao mesmo tempo")
            self.cond.notify_all()

    def entrar(self):
        with self.cond:
            self._talvez_subir()
            while self.em_uso >= self.atual:
                self.cond.wait(timeout=5)
                self._talvez_subir()
            self.em_uso += 1

    def sair(self, status=None):
        with self.cond:
            self.em_uso -= 1
            if status == 429:
                self.n429 += 1
                self.ultimo_429 = self.ultima_mudanca = self.relogio()
                if self.atual > MINIMO:
                    self.atual -= 1
                    print(f"  PNCP: 429 — até {self.atual} consulta(s) ao mesmo tempo")
            self.cond.notify_all()


LIMITE = Limite()


def requisitar(url, **kw):
    if "pncp.gov.br" not in url:  # outro host: sem o limite do PNCP
        return requests.get(url, **kw)
    LIMITE.entrar()
    st = None
    try:
        r = requests.get(url, **kw)
        st = r.status_code
        return r
    finally:
        LIMITE.sair(st)


def espera_429(resp=None):
    ra = (resp.headers.get("Retry-After") if resp is not None else None) or ""
    return min(300.0, float(ra)) if ra.strip().isdigit() else random.uniform(30, 60)


def esperar(seg):
    with LIMITE.cond:
        LIMITE.espera_total += seg
    time.sleep(seg)


def resumo():
    L = LIMITE
    return (f"PNCP: {L.n429} resposta(s) 429 · espera total {L.espera_total / 60:.1f} min · limite final {L.atual} simultânea(s) · "
            f"duração {(L.relogio() - L.inicio) / 60:.1f} min")
