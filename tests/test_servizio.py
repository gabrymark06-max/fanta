"""Il servizio: quello che il bot chiama quando tu scrivi una cifra.

Qui i test valgono piu' che altrove, perche' l'errore tipico dell'asta non e'
un consiglio sbagliato: e' battere "25" invece di "2", o registrare due volte
lo stesso giocatore mentre tutti urlano.
"""

from __future__ import annotations

import pytest

from fantabot.servizio import Servizio


@pytest.fixture
def srv(conn_popolato):
    return Servizio(conn_popolato)


@pytest.fixture
def lega(srv):
    return srv.crea_lega(-100, crediti=500, n_squadre=8)


def _id_di_ruolo(srv, ruolo: str, quanti: int = 1) -> list[int]:
    return [
        r["id_fc"]
        for r in srv.conn.execute(
            "SELECT id_fc FROM giocatori WHERE ruolo = ? ORDER BY fvm DESC LIMIT ?",
            (ruolo, quanti),
        )
    ]


def test_la_lega_nasce_con_la_mia_squadra_e_gli_avversari(srv, lega):
    squadre = srv.squadre(lega)
    assert len(squadre) == 8
    assert sum(1 for s in squadre if s.e_mia) == 1
    assert squadre[0].e_mia


def test_registra_e_annulla(srv, lega):
    id_fc = _id_di_ruolo(srv, "a")[0]
    mia = srv.squadre(lega)[0]
    assert srv.registra(lega, id_fc, mia.id, 40) is None
    assert srv.squadre(lega)[0].spesa() == 40
    tolto = srv.annulla_ultimo(lega)
    assert tolto is not None
    assert srv.squadre(lega)[0].spesa() == 0
    assert srv.annulla_ultimo(lega) is None


def test_lo_stesso_giocatore_non_va_a_due_squadre(srv, lega):
    id_fc = _id_di_ruolo(srv, "c")[0]
    squadre = srv.squadre(lega)
    assert srv.registra(lega, id_fc, squadre[0].id, 30) is None
    errore = srv.registra(lega, id_fc, squadre[1].id, 35)
    assert errore is not None and "assegnato" in errore


def test_un_reparto_pieno_rifiuta_il_giocatore_in_piu(srv, lega):
    portieri = _id_di_ruolo(srv, "p", 4)
    mia = srv.squadre(lega)[0]
    for id_fc in portieri[:3]:
        assert srv.registra(lega, id_fc, mia.id, 5) is None
    errore = srv.registra(lega, portieri[3], mia.id, 5)
    assert errore is not None and "completato" in errore


def test_non_si_spende_piu_di_quanto_si_puo(srv, lega):
    """Battere uno zero di troppo deve essere un rifiuto, non una rosa monca."""
    id_fc = _id_di_ruolo(srv, "a")[0]
    mia = srv.squadre(lega)[0]
    # 500 crediti, 25 slot: il massimo per il primo acquisto e' 476.
    errore = srv.registra(lega, id_fc, mia.id, 490)
    assert errore is not None and "476" in errore
    assert srv.registra(lega, id_fc, mia.id, 476) is None


def test_riconfigurare_la_lega_azzera_gli_acquisti(srv, lega):
    id_fc = _id_di_ruolo(srv, "d")[0]
    mia = srv.squadre(lega)[0]
    srv.registra(lega, id_fc, mia.id, 20)
    nuova = srv.crea_lega(-100, crediti=300, n_squadre=10)
    assert nuova.parametri.crediti == 300
    assert all(not s.acquisti for s in srv.squadre(nuova))


def test_le_valutazioni_si_ricalcolano_quando_cambiano_le_regole(srv, lega):
    prima = max(v.prezzo_mercato for v in srv.valutazioni(lega).values())
    ricca = srv.crea_lega(-100, crediti=1000, n_squadre=8)
    dopo = max(v.prezzo_mercato for v in srv.valutazioni(ricca).values())
    assert dopo > prima * 1.5


def test_rinomina_gli_avversari_lasciando_stare_la_mia(srv, lega):
    esito = srv.rinomina_squadre(lega, ["Marco", "Luca"])
    assert esito.assegnati == ["Marco", "Luca"]
    nomi = [s.nome for s in srv.squadre(lega)]
    assert nomi[0] == "La mia squadra"
    assert "Marco" in nomi and "Luca" in nomi


def test_dice_quanti_avversari_restano_senza_nome(srv, lega):
    """Sette avversari e due nomi: cinque restano com'erano, e va detto."""
    esito = srv.rinomina_squadre(lega, ["Marco", "Luca"])
    assert esito.senza_nome == 5
    assert esito.avanzati == []


def test_un_nome_di_troppo_non_sparisce_in_silenzio(srv, lega):
    """Il caso vero: otto nomi per una lega da otto, ma una squadra e' la tua.

    La prima versione ne applicava sette e buttava l'ottavo senza una parola.
    Un nome scartato in silenzio la sera dell'asta diventa una rosa attribuita
    alla squadra sbagliata.
    """
    esito = srv.rinomina_squadre(lega, list("abcdefgh"))
    assert len(esito.assegnati) == 7
    assert esito.avanzati == ["h"]
    assert esito.senza_nome == 0


def test_la_mia_squadra_si_puo_chiamare_come_vuoi(srv, lega):
    prima = srv.rinomina_mia(lega, "CarmySpecial")
    assert prima == "La mia squadra"
    mia = next(s for s in srv.squadre(lega) if s.e_mia)
    assert mia.nome == "CarmySpecial"


def test_rinominare_la_mia_non_tocca_gli_avversari(srv, lega):
    srv.rinomina_squadre(lega, ["Marco", "Luca"])
    srv.rinomina_mia(lega, "CarmySpecial")
    nomi = sorted(s.nome for s in srv.squadre(lega) if not s.e_mia)
    assert "Marco" in nomi and "Luca" in nomi
    assert "CarmySpecial" not in nomi
