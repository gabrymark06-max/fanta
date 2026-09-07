"""Il bot deve capire le regole come le scrive uno che ha fretta.

Le regole della lega si decidono spesso il giorno stesso: chi le scrive al bot
le ha appena sentite a voce, non sta compilando un modulo. Questi test sono
tutte frasi che possono davvero arrivare dieci minuti prima dell'asta.
"""

from __future__ import annotations

import pytest

from fantabot.bot.regole import leggi
from fantabot.motore.valutazione import ParametriLega


def test_la_forma_secca_di_sempre():
    r = leggi("500 8 3-8-8-6")
    assert r.crediti == 500
    assert r.n_squadre == 8
    assert r.slot == {"p": 3, "d": 8, "c": 8, "a": 6}


@pytest.mark.parametrize(
    "frase",
    [
        "10 squadre, 750 crediti, rose 3-8-8-6",
        "750 crediti 10 squadre 3-8-8-6",
        "siamo in 10, budget 750, 3-8-8-6",
        "rose da 3/8/8/6, 10 partecipanti, 750 crediti",
    ],
)
def test_lo_stesso_contenuto_scritto_in_quattro_modi(frase):
    r = leggi(frase)
    assert (r.crediti, r.n_squadre) == (750, 10), frase
    assert r.slot == {"p": 3, "d": 8, "c": 8, "a": 6}, frase


def test_i_numeri_si_riconoscono_dalla_taglia():
    """Nessuna lega ha 50 squadre e nessuna ha 8 crediti."""
    r = leggi("1000 12")
    assert r.crediti == 1000
    assert r.n_squadre == 12


def test_la_rosa_non_viene_scambiata_per_crediti_o_squadre():
    r = leggi("3-8-8-6")
    assert r.slot == {"p": 3, "d": 8, "c": 8, "a": 6}
    assert r.crediti is None
    assert r.n_squadre is None


@pytest.mark.parametrize(
    "frase",
    ["con modificatore", "modificatore di difesa", "usiamo il mod", "difesa modificata"],
)
def test_il_modificatore_si_accende(frase):
    assert leggi(frase).modificatore_difesa is True


@pytest.mark.parametrize(
    "frase",
    ["senza modificatore", "no modificatore", "niente modificatore", "non usiamo il mod"],
)
def test_e_si_spegne_quando_lo_si_nega(frase):
    assert leggi(frase).modificatore_difesa is False


def test_non_nominato_non_vuol_dire_spento():
    """Tre stati, non due: acceso, spento, e non ancora deciso.

    Se "non detto" valesse "spento", scrivere <code>/setup 10 squadre</code>
    a modificatore gia' acceso lo spegnerebbe di nascosto.
    """
    assert leggi("500 8 3-8-8-6").modificatore_difesa is None


def test_una_frase_senza_niente_di_utile():
    r = leggi("ciao come va")
    assert r.vuote


def test_frase_vuota():
    assert leggi("").vuote
    assert leggi(None).vuote


def test_descrivi_dice_tutto_quello_che_serve_per_controllare():
    from fantabot.bot.regole import descrivi

    testo = descrivi(
        ParametriLega(crediti=750, n_squadre=10, modificatore_difesa=True), 1.0
    )
    assert "750" in testo and "10" in testo
    assert "3-8-8-6" in testo
    assert "sì" in testo
    # E spiega cosa cambia, perche' una riga "modificatore: sì" da sola non
    # dice a nessuno come comprare i difensori.
    assert "media voto" in testo


@pytest.mark.parametrize(
    "frase",
    ["a buste chiuse", "offerte segrete", "asta silenziosa", "si offre al buio"],
)
def test_le_buste_chiuse_si_riconoscono(frase):
    assert leggi(frase).offerte_segrete is True


def test_le_buste_si_possono_negare():
    assert leggi("senza buste, asta normale").offerte_segrete is False
    assert leggi("500 8 3-8-8-6").offerte_segrete is None


def test_due_regole_insieme():
    r = leggi("10 squadre 750 crediti con modificatore a buste chiuse")
    assert r.modificatore_difesa is True
    assert r.offerte_segrete is True
    assert (r.crediti, r.n_squadre) == (750, 10)


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        ("dalla 4a giornata", 4),
        ("si parte dalla 4 giornata", 4),
        ("giornata 4", 4),
        ("partiamo dalla 12ª giornata", 12),
        ("500 8 3-8-8-6", None),
    ],
)
def test_da_che_giornata_comincia_la_lega(frase, atteso):
    assert leggi(frase).prima_giornata == atteso


def test_la_giornata_non_viene_scambiata_per_il_numero_di_squadre():
    """Il 4 di «dalla 4a giornata» e' un numero piccolo come le squadre.

    Senza toglierlo prima dal testo, una lega da otto squadre che comincia
    dalla quarta diventava una lega da quattro squadre — e con meta' dei
    crediti in sala tutti i prezzi sarebbero stati sbagliati.
    """
    r = leggi("8 squadre 500 crediti dalla 4a giornata")
    assert r.n_squadre == 8
    assert r.crediti == 500
    assert r.prima_giornata == 4
