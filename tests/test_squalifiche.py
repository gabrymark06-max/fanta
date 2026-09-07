"""Squalificati e diffidati: due cose diverse che la stessa pagina mette vicine.

ONESTA' SULLA COPERTURA. Nel momento in cui questi test sono stati scritti la
pagina vera era vuota per tutte e venti le squadre — dopo tre giornate quattro
cartellini non li ha nessuno — quindi il caso «c'e' qualcuno dentro» e'
provato su un HTML costruito qui, con la stessa struttura della pagina reale
(schede `.team-card`, due colonne riconosciute dall'etichetta). La lettura a
vuoto invece e' provata sul vero, ed e' quella che distingue le due situazioni
che non devono somigliarsi: nessuno squalificato, e pagina che non si legge.
"""

from __future__ import annotations

import pytest

from fantabot.dati import squalifiche
from fantabot.dati.magazzino import carica_giocatori
from fantabot.motore.formazione import probabilita_che_giochi
from fantabot.motore.valutazione import ParametriLega, valuta

SCHEDA = """
<div class="card team-card">
  <header class="team-info"><span class="team-name">{squadra}</span></header>
  <div class="row">
    <div class="col">
      <header><strong class="label label-danger">Squalificati</strong></header>
      {squalificati}
    </div>
    <div class="col">
      <header><strong class="label label-warn">Diffidati</strong></header>
      {diffidati}
    </div>
  </div>
</div>
"""
VUOTO = '<div class="empty-list-message">Nessuno</div>'


def _voce(nome: str, coda: str = "") -> str:
    return f'<li><span class="item-name">{nome}</span> {coda}</li>'


def _pagina(squalificati: str = VUOTO, diffidati: str = VUOTO) -> str:
    return SCHEDA.format(
        squadra="Atalanta", squalificati=squalificati, diffidati=diffidati
    )


@pytest.fixture
def conn_atalanta(conn_popolato):
    """Due giocatori con una sigla vera, che il listone di prova non ha."""
    conn_popolato.executemany(
        "INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo, fvm)"
        " VALUES (?, ?, ?, 'ATA', ?, 60)",
        [
            (9001, "Ederson", "ederson", "c"),
            (9002, "Hien", "hien", "d"),
        ],
    )
    conn_popolato.commit()
    return conn_popolato


# -- leggere la pagina ----------------------------------------------------


def test_venti_schede_vuote_sono_un_esito_valido(conn_atalanta):
    """«Nessuno squalificato» e «non ho letto niente» non sono la stessa cosa."""
    esito = squalifiche.leggi(conn_atalanta, _pagina())
    assert esito.riuscito
    assert esito.schede == 1
    assert esito.squalificati == [] and esito.diffidati == []


def test_una_pagina_senza_schede_e_un_guasto(conn_atalanta):
    esito = squalifiche.leggi(conn_atalanta, "<html><body>ciao</body></html>")
    assert not esito.riuscito
    assert "e' cambiata" in esito.errore


def test_riconosce_squalificato_e_diffidato(conn_atalanta):
    esito = squalifiche.leggi(
        conn_atalanta,
        _pagina(squalificati=_voce("Ederson"), diffidati=_voce("Hien")),
    )
    assert [f.nome for f in esito.squalificati] == ["Ederson"]
    assert [f.nome for f in esito.diffidati] == ["Hien"]
    assert esito.squalificati[0].id_fc == 9001
    assert esito.diffidati[0].id_fc == 9002


def test_le_colonne_si_riconoscono_dall_etichetta_non_dalla_posizione(
    conn_atalanta,
):
    """Una colonna in piu' domani non deve scambiare le due liste.

    Un elenco di diffidati letto come squalificati toglierebbe dal campo
    giocatori che invece giocano — e sono spesso i migliori, perche' i
    diffidati sono chi ha giocato di piu'.
    """
    invertita = SCHEDA.format(
        squadra="Atalanta", squalificati=VUOTO, diffidati=_voce("Ederson")
    ).replace("label-danger", "label-x")
    esito = squalifiche.leggi(conn_atalanta, invertita)
    assert [f.nome for f in esito.diffidati] == ["Ederson"]
    assert esito.squalificati == []


def test_legge_le_giornate_quando_ci_sono(conn_atalanta):
    esito = squalifiche.leggi(
        conn_atalanta, _pagina(squalificati=_voce("Ederson", "2 giornate"))
    )
    assert esito.squalificati[0].giornate == 2


def test_senza_numero_la_squalifica_e_di_una_giornata(conn_atalanta):
    esito = squalifiche.leggi(conn_atalanta, _pagina(squalificati=_voce("Ederson")))
    assert esito.squalificati[0].giornate == 1


def test_un_nome_che_non_esiste_viene_dichiarato(conn_atalanta):
    """Un nome perso in silenzio e' un giocatore schierato per sbaglio."""
    esito = squalifiche.leggi(
        conn_atalanta, _pagina(squalificati=_voce("Chi Non Esiste"))
    )
    assert esito.squalificati == []
    assert esito.non_trovati == ["Chi Non Esiste (ATA)"]


# -- cosa cambia nel bot --------------------------------------------------


def test_salvare_riscrive_e_non_somma(conn_atalanta):
    """Chi ha scontato deve sparire, non restare fuori il doppio."""
    prima = squalifiche.leggi(conn_atalanta, _pagina(squalificati=_voce("Ederson")))
    squalifiche.salva(conn_atalanta, prima)
    assert squalifiche.carica(conn_atalanta)[9001][0] == 1
    squalifiche.salva(conn_atalanta, squalifiche.leggi(conn_atalanta, _pagina()))
    assert squalifiche.carica(conn_atalanta) == {}


def test_uno_squalificato_non_si_schiera(conn_atalanta):
    squalifiche.salva(
        conn_atalanta,
        squalifiche.leggi(conn_atalanta, _pagina(squalificati=_voce("Ederson"))),
    )
    valutazioni = valuta(carica_giocatori(conn_atalanta), ParametriLega())
    gioca, nota = probabilita_che_giochi(valutazioni[9001])
    assert gioca == 0.0
    assert "squalificato" in nota


def test_un_diffidato_gioca_lo_stesso(conn_atalanta):
    """La diffida riguarda la giornata dopo, non questa."""
    squalifiche.salva(
        conn_atalanta,
        squalifiche.leggi(conn_atalanta, _pagina(diffidati=_voce("Hien"))),
    )
    giocatori = {g.id_fc: g for g in carica_giocatori(conn_atalanta)}
    assert giocatori[9002].diffidato is True
    assert giocatori[9002].squalificato == 0
    valutazioni = valuta(list(giocatori.values()), ParametriLega())
    gioca, _ = probabilita_che_giochi(valutazioni[9002])
    assert gioca > 0.0
