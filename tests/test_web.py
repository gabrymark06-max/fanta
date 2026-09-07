"""Il webhook: cosa entra, cosa viene respinto, e cosa succede al riavvio.

Non si costruisce l'`Application` vera — servirebbe un token e una rete. Si
prova la parte che decide, che e' quella che puo' sbagliare: il segreto, il
metodo, e l'assorbimento del pacco all'avvio del processo.
"""

from __future__ import annotations

import io
import json

from fantabot.bot import web
from fantabot.dati import sincronizza
from fantabot.db import connetti


class _FintoBot:
    """Abbastanza `Applicazione` da poterla chiamare, senza toccare Telegram."""

    def __init__(self, segreto: str = "") -> None:
        self.segreto = segreto
        self.ricevuti: list[dict] = []

    def _consegna(self, dati: bytes) -> None:
        self.ricevuti.append(json.loads(dati))

    __call__ = web.Applicazione.__call__


def _chiama(app, metodo="POST", segreto=None, corpo=b"{}"):
    ambiente = {
        "REQUEST_METHOD": metodo,
        "CONTENT_LENGTH": str(len(corpo)),
        "wsgi.input": io.BytesIO(corpo),
    }
    if segreto is not None:
        ambiente[web.INTESTAZIONE_SEGRETO] = segreto
    visto = {}

    def start_response(codice, intestazioni):
        visto["codice"] = codice

    corpo_risposta = app(ambiente, start_response)
    return visto["codice"], b"".join(corpo_risposta)


# -- chi entra e chi no ---------------------------------------------------


def test_senza_il_segreto_giusto_e_403():
    """L'indirizzo non e' una password: chi lo indovina non deve entrare."""
    app = _FintoBot(segreto="parolina")
    codice, _ = _chiama(app, segreto="sbagliata")
    assert codice.startswith("403")
    assert app.ricevuti == []


def test_senza_intestazione_del_tutto_e_403():
    app = _FintoBot(segreto="parolina")
    codice, _ = _chiama(app, segreto=None)
    assert codice.startswith("403")


def test_col_segreto_giusto_l_aggiornamento_arriva():
    app = _FintoBot(segreto="parolina")
    codice, _ = _chiama(app, segreto="parolina", corpo=b'{"update_id": 7}')
    assert codice.startswith("200")
    assert app.ricevuti == [{"update_id": 7}]


def test_una_GET_dice_solo_che_e_vivo():
    """Aprire l'indirizzo col browser non deve rivelare niente."""
    app = _FintoBot(segreto="parolina")
    codice, corpo = _chiama(app, metodo="GET", segreto=None)
    assert codice.startswith("200")
    assert corpo == b"fantabot"
    assert app.ricevuti == []


def test_un_aggiornamento_illeggibile_non_fa_ritentare_telegram():
    """Un 500 farebbe riconsegnare, e riconsegnare qui raddoppia un acquisto."""

    class Rotto(_FintoBot):
        def _consegna(self, dati):
            raise ValueError("json a pezzi")

    codice, _ = _chiama(Rotto(segreto="parolina"), segreto="parolina")
    assert codice.startswith("200")


# -- il pacco che arriva da GitHub Actions --------------------------------


def _pacco(tmp_path, conn_popolato):
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(conn_popolato, pacco)
    return pacco


def test_il_pacco_si_assorbe_una_volta_sola(tmp_path, conn_popolato):
    """Ogni reload ricarica il processo: riassorbire ogni volta sarebbe sprecato."""
    pacco = _pacco(tmp_path, conn_popolato)
    segno = tmp_path / "riferimento.assorbito"
    vuoto = connetti(tmp_path / "bot.sqlite3")

    assert web.assorbi_se_arrivato(vuoto, pacco, segno) is True
    assert segno.exists()
    assert web.assorbi_se_arrivato(vuoto, pacco, segno) is False
    vuoto.close()


def test_un_pacco_piu_recente_si_riassorbe(tmp_path, conn_popolato):
    pacco = _pacco(tmp_path, conn_popolato)
    segno = tmp_path / "riferimento.assorbito"
    vuoto = connetti(tmp_path / "bot.sqlite3")
    web.assorbi_se_arrivato(vuoto, pacco, segno)

    import os

    dopo = segno.stat().st_mtime + 10
    os.utime(pacco, (dopo, dopo))
    assert web.assorbi_se_arrivato(vuoto, pacco, segno) is True
    vuoto.close()


def test_senza_pacco_non_succede_niente(tmp_path):
    vuoto = connetti(tmp_path / "bot.sqlite3")
    assert (
        web.assorbi_se_arrivato(
            vuoto, tmp_path / "manco.sqlite3", tmp_path / "segno"
        )
        is False
    )
    vuoto.close()


def test_un_pacco_rotto_non_lascia_il_segno(tmp_path):
    """Se non e' stato assorbito, il reload dopo deve riprovarci."""
    pacco = tmp_path / "riferimento.sqlite3"
    pacco.write_bytes(b"non sono un database")
    segno = tmp_path / "riferimento.assorbito"
    vuoto = connetti(tmp_path / "bot.sqlite3")
    assert web.assorbi_se_arrivato(vuoto, pacco, segno) is False
    assert not segno.exists()
    vuoto.close()


def test_assorbire_scatta_anche_la_fotografia(tmp_path, conn_popolato):
    """`andamento` non viaggia: si ricostruisce qui, appena arrivano i dati.

    Actions riparte ogni volta dal pacco, quindi la sua storia sarebbe lunga
    una riga sola. Il database del bot invece e' sempre lo stesso, ed e' il
    solo posto dove quella storia puo' crescere.
    """
    conn_popolato.execute("UPDATE statistiche SET giornate = 5 WHERE stagione = ?",
                          ("2026-27",))
    conn_popolato.execute(
        "INSERT OR REPLACE INTO statistiche (id_fc, stagione, presenze, giornate,"
        " fantamedia, media_voto) VALUES (1, '2026-27', 5, 5, 7.0, 6.5)"
    )
    conn_popolato.commit()
    pacco = _pacco(tmp_path, conn_popolato)

    vuoto = connetti(tmp_path / "bot.sqlite3")
    assert web.assorbi_se_arrivato(vuoto, pacco, tmp_path / "segno") is True
    from fantabot.dati.andamento import ultima_giornata

    assert ultima_giornata(vuoto) == 5
    vuoto.close()


# -- convivere con un altro progetto sulla stessa web app -----------------


def test_affianca_manda_il_resto_all_altra_app():
    """Il progetto che c'era gia' non deve accorgersi di niente."""
    import wsgi_fanta

    visite = []

    def altra(environ, start_response):
        visite.append(environ["PATH_INFO"])
        start_response("200 OK", [])
        return [b"altra"]

    def mia(environ, start_response):
        visite.append(("mia", environ["PATH_INFO"], environ["SCRIPT_NAME"]))
        start_response("200 OK", [])
        return [b"mia"]

    app = wsgi_fanta.affianca("/fanta", altra, mia)

    def chiama(percorso):
        return b"".join(app({"PATH_INFO": percorso, "SCRIPT_NAME": ""}, lambda *a: None))

    assert chiama("/") == b"altra"
    assert chiama("/webhook/qualcosa") == b"altra"
    assert chiama("/fanta") == b"mia"
    assert chiama("/fanta/telegram") == b"mia"
    # Il prefisso viene tolto dal percorso e spostato in SCRIPT_NAME.
    assert ("mia", "/telegram", "/fanta") in visite


def test_affianca_non_confonde_un_prefisso_che_somiglia():
    """`/fantacalcio` non deve finire nel fantabot solo perche' comincia uguale."""
    import wsgi_fanta

    def altra(environ, start_response):
        start_response("200 OK", [])
        return [b"altra"]

    def mia(environ, start_response):
        start_response("200 OK", [])
        return [b"mia"]

    app = wsgi_fanta.affianca("/fanta", altra, mia)
    corpo = b"".join(
        app({"PATH_INFO": "/fantacalcio", "SCRIPT_NAME": ""}, lambda *a: None)
    )
    assert corpo == b"altra"
