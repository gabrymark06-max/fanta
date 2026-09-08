"""Azzerare l'asta dopo una prova, senza portarsi via il resto.

La cosa che questo comando deve garantire non e' che cancelli: e' **cosa non
cancella**. Le regole della lega si riscrivono in un minuto, ma il foglio
delle fasce si ricarica da Telegram e i dati dei giocatori si riscaricano —
e nel mezzo di una serata non hai voglia di fare ne' l'una ne' l'altra cosa.
"""

from __future__ import annotations

import pytest

from fantabot.bot import formato
from fantabot.servizio import Servizio


@pytest.fixture
def srv_con_asta(conn_popolato):
    srv = Servizio(conn_popolato)
    srv.crea_lega(
        1234, crediti=500, n_squadre=4, slot={"p": 3, "d": 8, "c": 8, "a": 6}
    )
    lega = srv.lega(1234)
    srv.rinomina_squadre(lega, ["Marco", "Luca", "Giulia"])
    mia = next(s for s in srv.squadre(lega) if s.e_mia)
    altra = next(s for s in srv.squadre(lega) if not s.e_mia)
    for id_fc, squadra, prezzo in ((1, mia, 30), (2, mia, 12), (3, altra, 7)):
        assert srv.registra(lega, id_fc, squadra.id, prezzo) is None
    srv.imposta_preferenza(lega, 5, 1)
    srv.imposta_preferenza(lega, 6, -1)
    conn_popolato.execute(
        "INSERT INTO mercato_esterno (id_fc, prezzo_medio, fascia) VALUES (1, 30.0, 1)"
    )
    conn_popolato.commit()
    return srv, srv.lega(1234)


def test_dice_cosa_si_perde_prima_di_perderlo(srv_con_asta):
    """Una conferma senza numeri non e' una domanda: si clicca senza leggere."""
    srv, lega = srv_con_asta
    perso = srv.cosa_si_perde(lega)
    assert perso == {"acquisti": 3, "preferenze": 2, "crediti": 49}
    testo = formato.conferma_azzera(perso)
    assert "3 acquisti" in testo and "49 crediti" in testo


def test_senza_niente_da_azzerare_non_chiede(conn_popolato):
    srv = Servizio(conn_popolato)
    srv.crea_lega(9, crediti=500, n_squadre=4, slot={"p": 3, "d": 8, "c": 8, "a": 6})
    perso = srv.cosa_si_perde(srv.lega(9))
    assert "niente da azzerare" in formato.conferma_azzera(perso)


def test_azzera_le_rose(srv_con_asta):
    srv, lega = srv_con_asta
    perso = srv.azzera_asta(lega)
    assert perso["acquisti"] == 3
    assert all(not s.acquisti for s in srv.squadre(lega))


def test_non_tocca_le_regole_ne_i_nomi(srv_con_asta):
    """Rifarle costa un minuto, e quel minuto e' sempre quello sbagliato."""
    srv, lega = srv_con_asta
    prima = (lega.parametri.crediti, lega.parametri.n_squadre, lega.parametri.slot)
    srv.azzera_asta(lega)
    dopo = srv.lega(1234)
    assert (dopo.parametri.crediti, dopo.parametri.n_squadre, dopo.parametri.slot) == prima
    assert sorted(s.nome for s in srv.squadre(dopo)) == [
        "Giulia",
        "La mia squadra",
        "Luca",
        "Marco",
    ]


def test_non_tocca_il_foglio_delle_fasce(srv_con_asta):
    """Quello arriva da Telegram: cancellarlo vorrebbe dire ricaricarlo a mano."""
    srv, lega = srv_con_asta
    srv.azzera_asta(lega)
    assert (
        srv.conn.execute("SELECT COUNT(*) FROM mercato_esterno").fetchone()[0] == 1
    )


def test_non_tocca_i_dati_dei_giocatori(srv_con_asta):
    srv, lega = srv_con_asta
    quanti = srv.conta_giocatori()
    srv.azzera_asta(lega)
    assert srv.conta_giocatori() == quanti


def test_riporta_il_turno_all_inizio(srv_con_asta):
    srv, lega = srv_con_asta
    srv.imposta_turno(lega, 2)
    srv.imposta_reparto(lega, "p")
    srv.azzera_asta(lega)
    dopo = srv.lega(1234)
    assert dopo.turno == 0 and dopo.reparto == ""


def test_si_possono_tenere_gli_obiettivi(srv_con_asta):
    """Fra una prova e l'asta vera la lista dei nomi che vuoi non cambia."""
    srv, lega = srv_con_asta
    srv.azzera_asta(lega, anche_obiettivi=False)
    assert len(srv.preferenze(lega)) == 2
    assert srv.conn.execute("SELECT COUNT(*) FROM acquisti").fetchone()[0] == 0


def test_dopo_l_azzeramento_si_ricompra_lo_stesso_giocatore(srv_con_asta):
    """La prova che serve: azzerare deve lasciare un'asta rigiocabile."""
    srv, lega = srv_con_asta
    srv.azzera_asta(lega)
    mia = next(s for s in srv.squadre(lega) if s.e_mia)
    assert srv.registra(lega, 1, mia.id, 42) is None
