"""I percorsi che userai davvero all'asta, senza Telegram di mezzo.

Gli handler ricevono oggetti finti che rispondono come quelli veri per la sola
parte che il codice tocca. Non e' un test di python-telegram-bot: e' un test
del fatto che scrivere "+lautaro 94" tolga davvero 94 crediti alla mia
squadra, che e' l'unica cosa che non puoi permetterti di scoprire in sala.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from fantabot.bot import main as bot
from fantabot.servizio import Servizio


@dataclass
class FintoMessaggio:
    text: str = ""
    risposte: list[str] = field(default_factory=list)
    tastiere: list[Any] = field(default_factory=list)
    documenti: list[tuple[str, str]] = field(default_factory=list)

    async def reply_text(self, testo, parse_mode=None, reply_markup=None):
        self.risposte.append(testo)
        self.tastiere.append(reply_markup)

    async def reply_document(self, document, filename=None, caption=None):
        self.documenti.append((filename, document.getvalue().decode("utf-8")))


@dataclass
class FintaQuery:
    data: str
    message: FintoMessaggio

    async def answer(self):
        return None


class FintoUpdate:
    def __init__(self, testo="", chat_id=-100, utente=42, callback=None):
        self.message = FintoMessaggio(text=testo) if callback is None else None
        self.callback_query = (
            FintaQuery(callback, FintoMessaggio()) if callback else None
        )
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("Utente", (), {"id": utente})()
        self.effective_message = self.message

    @property
    def dette(self) -> list[str]:
        fonte = self.message or self.callback_query.message
        return fonte.risposte

    @property
    def ultima(self) -> str:
        return self.dette[-1] if self.dette else ""


class FintoContext:
    def __init__(self, srv, args=None):
        self.args = args or []
        self.application = type(
            "App", (), {"bot_data": {bot.CHIAVE_SERVIZIO: srv}}
        )()


@pytest.fixture
def srv(conn_popolato, monkeypatch):
    # Nessun elenco di utenti ammessi: in un test non c'e' nessuno da tenere fuori.
    monkeypatch.setenv("UTENTI_AMMESSI", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:test")
    from fantabot.config import impostazioni

    impostazioni.cache_clear()
    conn_popolato.execute(
        """
        INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                               quota_iniziale, quota_attuale, fvm)
        VALUES (7001, 'Lautaro', 'lautaro', 'INT', 'a', 33, 33, 361)
        """
    )
    conn_popolato.commit()
    return Servizio(conn_popolato)


def esegui(coroutine):
    return asyncio.run(coroutine)


def test_senza_lega_il_bot_spiega_come_crearla(srv):
    u, c = FintoUpdate("lautaro"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "/setup" in u.ultima


def test_scrivere_un_nome_da_la_scheda_con_la_cifra(srv):
    srv.crea_lega(-100)
    u, c = FintoUpdate("lautaro"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "LAUTARO" in u.ultima
    # La prima cosa leggibile e' una cifra da dire, o l'avviso che non basta.
    assert "DOVREBBE BASTARE" in u.ultima or "TI SUPERERANNO" in u.ultima
    # E i bottoni per metterlo in lista con un pollice.
    bottoni = [b for riga in u.message.tastiere[-1].inline_keyboard for b in riga]
    assert {b.text for b in bottoni} == {"◎ obiettivo", "✕ evita"}


def test_il_piu_registra_alla_mia_squadra(srv):
    lega = srv.crea_lega(-100)
    u, c = FintoUpdate("+lautaro 94"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    mia = srv.squadre(lega)[0]
    assert mia.spesa() == 94
    assert "94" in u.ultima
    assert "ti restano 406" in u.ultima


def test_nome_e_prezzo_senza_piu_chiede_chi_lo_ha_preso(srv):
    lega = srv.crea_lega(-100)
    u, c = FintoUpdate("lautaro 94"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "Chi se l'e' preso?" in u.ultima
    tastiera = u.message.tastiere[-1]
    assert tastiera is not None
    bottoni = [b for riga in tastiera.inline_keyboard for b in riga]
    assert len(bottoni) == 8
    # Nessun acquisto finche' non si sceglie: la domanda non e' una conferma.
    assert all(not s.acquisti for s in srv.squadre(lega))


def test_il_bottone_assegna_alla_squadra_scelta(srv):
    lega = srv.crea_lega(-100)
    avversario = srv.squadre(lega)[1]
    u = FintoUpdate(callback=f"a:7001:94:{avversario.id}")
    esegui(bot.bottone(u, FintoContext(srv)))
    squadre = {s.id: s for s in srv.squadre(lega)}
    assert squadre[avversario.id].spesa() == 94
    assert squadre[srv.squadre(lega)[0].id].spesa() == 0


def test_un_nome_ambiguo_offre_la_scelta(srv):
    srv.crea_lega(-100)
    srv.conn.execute(
        """
        INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                               quota_iniziale, quota_attuale, fvm)
        VALUES (7002, 'Lautaro Jr.', 'lautaro jr', 'GEN', 'a', 5, 5, 20)
        """
    )
    srv.conn.commit()
    u, c = FintoUpdate("lauta"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "Quale?" in u.ultima
    bottoni = [b for riga in u.message.tastiere[-1].inline_keyboard for b in riga]
    assert len(bottoni) == 2


def test_un_nome_inesistente_lo_dice(srv):
    srv.crea_lega(-100)
    u, c = FintoUpdate("qwertyuiop"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "Non trovo" in u.ultima


def test_un_giocatore_gia_assegnato_lo_dice_invece_di_consigliarlo(srv):
    lega = srv.crea_lega(-100)
    avversario = srv.squadre(lega)[1]
    srv.registra(lega, 7001, avversario.id, 90)
    u, c = FintoUpdate("lautaro"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "e' gia' di" in u.ultima


def test_annulla_torna_indietro(srv):
    lega = srv.crea_lega(-100)
    mia = srv.squadre(lega)[0]
    srv.registra(lega, 7001, mia.id, 50)
    u, c = FintoUpdate(), FintoContext(srv)
    u.message = FintoMessaggio()
    esegui(bot.cmd_annulla(u, c))
    assert "Annullato" in u.ultima
    assert srv.squadre(lega)[0].spesa() == 0


def test_setup_legge_i_parametri_dalla_riga(srv):
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_setup(u, FintoContext(srv, args=["300", "10", "3-8-8-6"])))
    lega = srv.lega(-100)
    assert lega.parametri.crediti == 300
    assert lega.parametri.n_squadre == 10
    assert len(srv.squadre(lega)) == 10


def test_setup_rifiuta_numeri_impossibili(srv):
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_setup(u, FintoContext(srv, args=["10", "crediti"])))
    assert "non stanno in piedi" in u.ultima
    assert srv.lega(-100) is None


def test_setup_rilegge_sempre_quello_che_ha_capito(srv):
    """Nessun rifiuto muto: il bot ripete le regole e tu vedi cosa ha preso.

    Con "3-8-8" (tre numeri invece di quattro) la rosa non e' leggibile e
    resta quella di prima - ma la risposta la mostra, quindi l'errore si vede
    subito invece di saltare fuori a meta' asta.
    """
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_setup(u, FintoContext(srv, args=["500", "8", "3-8-8"])))
    assert "Le regole di questa lega" in u.ultima
    assert "3-8-8-6" in u.ultima


def test_setup_a_frase_intera(srv):
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(
        bot.cmd_setup(
            u,
            FintoContext(
                srv, args=["10", "squadre,", "750", "crediti,", "con", "modificatore"]
            ),
        )
    )
    lega = srv.lega(-100)
    assert lega.parametri.crediti == 750
    assert lega.parametri.n_squadre == 10
    assert lega.parametri.modificatore_difesa is True


def test_setup_parziale_non_azzera_il_resto(srv):
    """Correggere un dettaglio non deve costare la riscrittura di tutto."""
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_setup(u, FintoContext(srv, args=["750", "10", "3-8-8-6"])))
    u2 = FintoUpdate()
    u2.message = FintoMessaggio()
    esegui(bot.cmd_setup(u2, FintoContext(srv, args=["con", "modificatore"])))
    lega = srv.lega(-100)
    assert lega.parametri.crediti == 750
    assert lega.parametri.n_squadre == 10
    assert lega.parametri.modificatore_difesa is True


def test_regole_rilegge_la_configurazione(srv):
    srv.crea_lega(-100, crediti=600, n_squadre=9, modificatore_difesa=True)
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_regole(u, FintoContext(srv)))
    assert "600" in u.ultima and "9" in u.ultima
    assert "media voto" in u.ultima


def test_chi_non_e_ammesso_non_ottiene_risposte(srv, monkeypatch):
    monkeypatch.setenv("UTENTI_AMMESSI", "999")
    from fantabot.config import impostazioni

    impostazioni.cache_clear()
    srv.crea_lega(-100)
    u, c = FintoUpdate("lautaro", utente=42), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert u.dette == []
    impostazioni.cache_clear()


def test_spezza_il_messaggio():
    def come_tupla(testo):
        c = bot._spezza(testo)
        return (c.nome, c.prezzo, c.mio, c.squadra)

    assert come_tupla("+vlahovic 25") == ("vlahovic", 25, True, "")
    assert come_tupla("vlahovic 25") == ("vlahovic", 25, False, "")
    assert come_tupla("  vlahovic  ") == ("vlahovic", None, False, "")
    assert come_tupla("martinez l. 30") == ("martinez l.", 30, False, "")
    assert come_tupla("") == ("", None, False, "")
    # Il numero separa il giocatore dalla squadra: un messaggio, nessun tap.
    assert come_tupla("vlahovic 25 marco") == ("vlahovic", 25, False, "marco")
    assert come_tupla("martinez l. 94 la mia") == ("martinez l.", 94, False, "la mia")


def test_registrare_con_la_squadra_nel_messaggio(srv):
    lega = srv.crea_lega(-100)
    srv.rinomina_squadre(lega, ["Marco", "Luca"])
    u, c = FintoUpdate("lautaro 94 marco"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    squadre = {s.nome: s for s in srv.squadre(lega)}
    assert squadre["Marco"].spesa() == 94
    assert u.message.tastiere[-1] is None  # nessun bottone: era gia' tutto detto


def test_una_squadra_sconosciuta_ricade_sui_bottoni(srv):
    lega = srv.crea_lega(-100)
    u, c = FintoUpdate("lautaro 94 zzz"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "Non ho una squadra" in u.dette[0]
    assert "Chi se l'e' preso?" in u.ultima
    assert all(not s.acquisti for s in srv.squadre(lega))


def test_il_bottone_obiettivo_alza_le_offerte(srv):
    lega = srv.crea_lega(-100)
    prima = srv.stato(lega).consiglia(7001).massimo
    u = FintoUpdate(callback="p:7001:1")
    esegui(bot.bottone(u, FintoContext(srv)))
    assert srv.preferenze(lega)[7001] == 1
    dopo = srv.stato(lega).consiglia(7001).massimo
    assert dopo > prima


def test_annulla_per_nome_anche_se_non_e_l_ultimo(srv):
    lega = srv.crea_lega(-100)
    mia = srv.squadre(lega)[0]
    srv.registra(lega, 7001, mia.id, 50)
    altro = [
        r["id_fc"]
        for r in srv.conn.execute("SELECT id_fc FROM giocatori WHERE ruolo='d' LIMIT 1")
    ][0]
    srv.registra(lega, altro, mia.id, 10)
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_annulla(u, FintoContext(srv, args=["lautaro"])))
    assert "Annullato" in u.ultima
    rimasti = {a.id_fc for a in srv.squadre(lega)[0].acquisti}
    assert rimasti == {altro}


def test_correggi_cambia_il_prezzo_senza_rifare_l_acquisto(srv):
    lega = srv.crea_lega(-100)
    mia = srv.squadre(lega)[0]
    srv.registra(lega, 7001, mia.id, 94)
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_correggi(u, FintoContext(srv, args=["lautaro", "9"])))
    assert srv.squadre(lega)[0].spesa() == 9
    assert len(srv.squadre(lega)[0].acquisti) == 1


def test_la_lista_vuota_spiega_come_riempirla(srv):
    srv.crea_lega(-100)
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_lista(u, FintoContext(srv)))
    assert "vuota" in u.ultima


def test_chiama_propone_solo_ruoli_che_mi_mancano(srv):
    lega = srv.crea_lega(-100)
    mia = srv.squadre(lega)[0]
    portieri = [
        r["id_fc"]
        for r in srv.conn.execute(
            "SELECT id_fc FROM giocatori WHERE ruolo='p' ORDER BY fvm DESC LIMIT 3"
        )
    ]
    for id_fc in portieri:
        srv.registra(lega, id_fc, mia.id, 5)
    stato = srv.stato(lega)
    assert all(c.valutazione.giocatore.ruolo != "p" for c in stato.da_chiamare())


def test_avvisa_quando_un_obiettivo_resta_senza_rivali(srv):
    """L'occasione nasce mentre guardi altrove: il bot deve dirlo da solo."""
    lega = srv.crea_lega(-100)
    srv.imposta_preferenza(lega, 7001, 1)
    squadre = srv.squadre(lega)
    altri = [
        (r["id_fc"], r["nome"])
        for r in srv.conn.execute(
            "SELECT id_fc, nome FROM giocatori WHERE ruolo='a' AND id_fc != 7001 "
            "ORDER BY fvm DESC LIMIT 60"
        )
    ]
    passo = iter(altri)
    # Tutti gli avversari chiudono l'attacco tranne l'ultimo slot dell'ultimo,
    # che verra' riempito dal messaggio sotto.
    for s in squadre[1:-1]:
        for _ in range(lega.parametri.slot["a"]):
            srv.registra(lega, next(passo)[0], s.id, 5)
    ultimo = squadre[-1]
    for _ in range(lega.parametri.slot["a"] - 1):
        srv.registra(lega, next(passo)[0], ultimo.id, 5)
    id_ultimo, nome_ultimo = next(passo)

    u, c = FintoUpdate(f"{nome_ultimo} 5 {ultimo.nome}"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    # Con quel colpo l'ultimo avversario ha chiuso il reparto: da qui in poi
    # Lautaro e' solo mio, e il bot lo dice senza che io chieda niente.
    assert "non te lo puo' piu' togliere nessuno" in u.ultima
    assert "Lautaro" in u.ultima


def test_il_piu_senza_cifra_spiega_come_registrare(srv):
    srv.crea_lega(-100)
    u, c = FintoUpdate("+lautaro"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "Per registrarlo scrivi" in u.ultima


def test_la_squadra_si_puo_indicare_col_numero(srv):
    """Con gli avversari ancora chiamati "Avversario 3", il numero e' piu' veloce."""
    lega = srv.crea_lega(-100)
    terza = srv.squadre(lega)[2]
    u, c = FintoUpdate("lautaro 40 3"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    squadre = {s.id: s for s in srv.squadre(lega)}
    assert squadre[terza.id].spesa() == 40


def test_un_numero_di_squadra_inesistente_non_assegna_a_caso(srv):
    lega = srv.crea_lega(-100)
    u, c = FintoUpdate("lautaro 40 99"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert all(not s.acquisti for s in srv.squadre(lega))
    assert "Chi se l'e' preso?" in u.ultima


def test_il_piano_arriva_come_file_con_tutti_i_reparti(srv):
    srv.crea_lega(-100)
    u = FintoUpdate()
    u.message = FintoMessaggio()
    esegui(bot.cmd_piano(u, FintoContext(srv)))
    assert len(u.message.documenti) == 1
    nome, contenuto = u.message.documenti[0]
    assert nome == "piano-asta.txt"
    for reparto in ("PORTIERI", "DIFENSORI", "CENTROCAMPISTI", "ATTACCANTI"):
        assert reparto in contenuto
    assert "PIANO D'ASTA" in contenuto


def test_un_giocatore_senza_ruolo_non_fa_esplodere_niente(srv):
    """Il listone puo' contenere un arrivo dell'ultima ora senza ruolo.

    Prima questo caso sollevava KeyError dentro la registrazione: il bot
    sarebbe morto in mezzo a un'asta, dopo un /aggiorna fatto la sera stessa.
    """
    lega = srv.crea_lega(-100)
    srv.conn.execute(
        """
        INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                               quota_iniziale, quota_attuale, fvm)
        VALUES (8001, 'Ignoto', 'ignoto', 'XXX', '?', 1, 1, 1)
        """
    )
    srv.conn.commit()
    srv.invalida_cache()

    # La scheda lo spiega invece di rispondere "non riesco a valutarlo".
    u, c = FintoUpdate("ignoto"), FintoContext(srv)
    esegui(bot.messaggio(u, c))
    assert "senza ruolo assegnato" in u.ultima

    # E la registrazione lo rifiuta con parole, non con un'eccezione.
    mia = srv.squadre(lega)[0]
    assert "senza un ruolo assegnato" in srv.registra(lega, 8001, mia.id, 5)
    assert not srv.squadre(lega)[0].acquisti
