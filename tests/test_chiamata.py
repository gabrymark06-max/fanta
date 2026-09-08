"""Chi chiamare, in che ordine, e quando conviene chiamare uno che non vuoi.

Due idee nuove, e la seconda e' quella che distingue un'asta giocata da
un'asta subita:

  · **il reparto avanza da solo** — si passa ai difensori quando TUTTI hanno
    finito i portieri, non quando ho finito io;
  · **l'esca** — quando i tuoi obiettivi costano troppo perche' gli avversari
    sono ancora pieni di crediti, la mossa non e' chiamare quello che vuoi (lo
    paghi al massimo): e' chiamare quello che vogliono loro.
"""

from __future__ import annotations

import pytest

from fantabot.motore.asta import Acquisto, Squadra, StatoAsta
from fantabot.motore.valutazione import ParametriLega, valuta


@pytest.fixture
def parametri_corti():
    """Rose piccole: cosi' un reparto si chiude in poche mosse."""
    return ParametriLega(crediti=500, n_squadre=4, slot={"p": 1, "d": 2, "c": 2, "a": 2})


def _stato(listone, parametri, acquisti_per_squadra=None):
    valutazioni = valuta(listone, parametri)
    squadre = [Squadra(id=1, nome="La mia", e_mia=True)] + [
        Squadra(id=i, nome=f"Avv {i}") for i in range(2, parametri.n_squadre + 1)
    ]
    for id_squadra, acquisti in (acquisti_per_squadra or {}).items():
        squadra = next(s for s in squadre if s.id == id_squadra)
        for id_fc, prezzo in acquisti:
            g = valutazioni[id_fc].giocatore
            squadra.acquisti.append(
                Acquisto(
                    id_fc=id_fc,
                    nome=g.nome,
                    ruolo=g.ruolo,
                    id_squadra=id_squadra,
                    prezzo=prezzo,
                )
            )
    return StatoAsta(parametri, valutazioni, squadre)


def _per_ruolo(listone, ruolo, quanti):
    return [g.id_fc for g in listone if g.ruolo == ruolo][:quanti]


# -- il reparto avanza da solo --------------------------------------------


def test_si_comincia_dai_portieri(listone, parametri_corti):
    assert _stato(listone, parametri_corti).reparto_aperto() == "p"


def test_non_si_passa_avanti_finche_uno_solo_ha_lo_slot_scoperto(
    listone, parametri_corti
):
    """Finche' un avversario cerca un portiere, li' ci sono ancora crediti."""
    portieri = _per_ruolo(listone, "p", 3)
    stato = _stato(
        listone,
        parametri_corti,
        {1: [(portieri[0], 10)], 2: [(portieri[1], 10)], 3: [(portieri[2], 10)]},
    )
    assert stato.reparto_aperto() == "p"


def test_quando_tutti_hanno_il_portiere_si_passa_ai_difensori(
    listone, parametri_corti
):
    portieri = _per_ruolo(listone, "p", 4)
    stato = _stato(
        listone,
        parametri_corti,
        {i + 1: [(portieri[i], 10)] for i in range(4)},
    )
    assert stato.reparto_aperto() == "d"


def test_un_reparto_chiuso_non_si_riapre(listone, parametri_corti):
    """`da` esiste per questo: un annullamento non deve tornare indietro."""
    stato = _stato(listone, parametri_corti)
    assert stato.reparto_aperto(da="c") == "c"


def test_a_rose_piene_non_c_e_piu_nessun_reparto(listone, parametri_corti):
    acquisti = {}
    for squadra in range(1, 5):
        presi = []
        for ruolo, quanti in parametri_corti.slot.items():
            disponibili = [
                g.id_fc
                for g in listone
                if g.ruolo == ruolo
            ][(squadra - 1) * quanti : squadra * quanti]
            presi += [(i, 1) for i in disponibili]
        acquisti[squadra] = presi
    stato = _stato(listone, parametri_corti, acquisti)
    assert stato.reparto_aperto() is None


# -- l'esca ---------------------------------------------------------------


def test_l_esca_costa_agli_altri_piu_di_quanto_vale_a_me(listone, parametri):
    """Se e' un affare anche per te, chiamarlo e' regalare un affare a un altro."""
    stato = _stato(listone, parametri)
    for e in stato.esche(limite=5):
        assert e.valutazione.valore < e.prezzo_corrente


def test_l_esca_vuole_almeno_due_rivali(listone, parametri):
    """Con un solo interessato non c'e' rilancio: c'e' un regalo alla base."""
    stato = _stato(listone, parametri)
    for e in stato.esche(limite=5):
        assert len(e.rivali) >= 2


def test_non_si_usa_come_esca_un_giocatore_che_voglio(listone, parametri):
    """Il rischio dell'esca e' portarsela a casa: con un obiettivo sarebbe un regalo."""
    stato = _stato(listone, parametri)
    prima = stato.esche(limite=3)
    assert prima, "servono esche per poter provare che spariscono"
    bersaglio = prima[0].valutazione.giocatore.id_fc
    stato.preferenze = {bersaglio: 1}
    stato.invalida()
    assert all(e.valutazione.giocatore.id_fc != bersaglio for e in stato.esche(limite=5))


def test_l_esca_rispetta_il_reparto(listone, parametri):
    stato = _stato(listone, parametri)
    for e in stato.esche(limite=5, reparto="a"):
        assert e.valutazione.giocatore.ruolo == "a"


def test_le_esche_migliori_drenano_di_piu(listone, parametri):
    stato = _stato(listone, parametri)
    esche = stato.esche(limite=5)
    assert esche == sorted(esche, key=lambda e: -e.drenati)


def test_il_rischio_e_sempre_dichiarato(listone, parametri):
    """Un'esca e' una scommessa piccola, ma e' una scommessa."""
    stato = _stato(listone, parametri)
    for e in stato.esche(limite=3):
        assert "nessuno rilancia" in e.rischio


def test_senza_squadra_mia_non_ci_sono_esche(listone, parametri):
    valutazioni = valuta(listone, parametri)
    stato = StatoAsta(parametri, valutazioni, [Squadra(id=2, nome="Solo avversari")])
    assert stato.esche() == []


# -- i due pezzi insieme --------------------------------------------------


def test_chiamare_a_reparti_propone_solo_quel_ruolo(listone, parametri):
    stato = _stato(listone, parametri)
    for c in stato.da_chiamare(limite=8, reparto="p"):
        assert c.valutazione.giocatore.ruolo == "p"
