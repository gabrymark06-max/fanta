"""Il trasporto che riprova quando il proxy si distrae.

Il caso vero da cui nasce: un `/squadre` durante una prova d'asta. Le squadre
erano state rinominate, ma il proxy di PythonAnywhere ha risposto 503 mentre
partiva la conferma, e il bot ha detto «qualcosa e' andato storto» su un
comando che aveva funzionato. Il peggio dei due mondi — il lavoro fatto e chi
lo ha chiesto convinto del contrario, quindi pronto a riscriverlo. In asta,
riscrivere vuol dire registrare due volte lo stesso acquisto.

I test girano le coroutine con `asyncio.run`: aggiungere `pytest-asyncio` per
quattro prove sarebbe una dipendenza in piu' sul server, dove il disco e' 512
MB e ogni pacchetto va giustificato.
"""

from __future__ import annotations

import asyncio

import pytest
from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest

from fantabot.bot.rete import ATTESE, RichiestaOstinata


@pytest.fixture(autouse=True)
def _senza_attese(monkeypatch):
    """Si prova la logica, non l'orologio."""

    async def subito(_secondi):
        return None

    monkeypatch.setattr("fantabot.bot.rete.asyncio.sleep", subito)


@pytest.fixture
def prova(monkeypatch):
    """Costruisce un trasporto che fallisce N volte e poi risponde."""

    def costruisci(fallimenti: int, errore=None):
        conteggio = {"tentativi": 0}
        errore = errore or NetworkError("httpx.ProxyError: 503 Service Unavailable")

        async def finto(self, *args, **kwargs):
            conteggio["tentativi"] += 1
            if conteggio["tentativi"] <= fallimenti:
                raise errore
            return 200, b'{"ok": true}'

        monkeypatch.setattr(HTTPXRequest, "do_request", finto)
        return RichiestaOstinata(), conteggio

    return costruisci


def test_un_intoppo_solo_non_si_vede(prova):
    trasporto, conteggio = prova(fallimenti=1)
    assert asyncio.run(trasporto.do_request()) == (200, b'{"ok": true}')
    assert conteggio["tentativi"] == 2


def test_riprova_fino_al_limite_e_poi_si_arrende(prova):
    """Se non passa in un secondo e mezzo non e' un intoppo: l'errore si vede."""
    trasporto, conteggio = prova(fallimenti=99)
    with pytest.raises(NetworkError):
        asyncio.run(trasporto.do_request())
    assert conteggio["tentativi"] == len(ATTESE) + 1


def test_un_timeout_non_si_riprova(prova):
    """La richiesta puo' essere arrivata: rispedirla duplicherebbe il messaggio."""
    trasporto, conteggio = prova(fallimenti=99, errore=TimedOut())
    with pytest.raises(TimedOut):
        asyncio.run(trasporto.do_request())
    assert conteggio["tentativi"] == 1


def test_se_va_bene_subito_non_riprova_niente(prova):
    trasporto, conteggio = prova(fallimenti=0)
    assert asyncio.run(trasporto.do_request()) == (200, b'{"ok": true}')
    assert conteggio["tentativi"] == 1


def test_le_attese_sono_corte(prova):
    """Mentre si aspetta, il banditore non aspetta."""
    assert sum(ATTESE) < 3.0
    assert all(a > 0 for a in ATTESE)
