"""Leggere i tempi di rientro da una frase, e non sbagliare persona.

Le frasi qui dentro sono quelle vere della pagina del 6 settembre 2026,
accorciate. Sono la parte che si rompe quando il sito cambia modo di scrivere,
e l'unica che ha senso provare senza rete.
"""

from __future__ import annotations

from datetime import date

import pytest

from fantabot.dati.infortuni import analizza, giornate_fuori
from fantabot.motore.valutazione import Fermo, InCampo, _presenze_col_campo

OGGI = date(2026, 9, 6)


def quante(testo: str, giornata: int = 3) -> int:
    return giornate_fuori(testo, giornata=giornata, oggi=OGGI)[0]


def datato(testo: str, giornata: int = 3) -> bool:
    return giornate_fuori(testo, giornata=giornata, oggi=OGGI)[1]


# -- il mese giusto -------------------------------------------------------


def test_il_mese_dell_infortunio_non_e_quello_del_rientro():
    """La trappola: ogni scheda nomina il mese in cui si e' fatto male."""
    yildiz = (
        "l'attaccante turco, dopo la gara di Frosinone (23 agosto), ha lamentato un "
        "problema al piede. Operato il 31 agosto di osteosintesi della frattura, stop "
        "di circa tre mesi. Ipotesi di rientro in campo da fine novembre."
    )
    # Fine novembre da inizio settembre: dodici giornate. Preso "agosto" come
    # data di rientro faceva quaranta, cioe' tutta la stagione.
    assert quante(yildiz) == 12
    assert datato(yildiz)


def test_un_mese_gia_passato_e_l_anno_prossimo():
    """Il campionato scavalca il capodanno."""
    assert quante("Lungo stop, ipotizziamo un rientro da gennaio.") == 18


@pytest.mark.parametrize(
    "frase, giornate",
    [
        ("recuperabile da inizio ottobre", 4),
        ("Recuperabile dalla fine di settembre", 3),
        ("recuperabile dalla seconda meta' di settembre", 2),
        ("Recuperabile dalla meta' di settembre", 1),
        ("che lo terra' ai box fino alla prima meta' di ottobre", 5),
    ],
)
def test_i_qualificatori_del_mese(frase, giornate):
    assert quante(frase) == giornate


# -- la giornata nominata -------------------------------------------------


def test_la_giornata_di_rientro_si_conta_da_quella_in_corso():
    frase = "puo' tornare convocabile dalla 4a giornata di campionato."
    assert quante(frase, giornata=3) == 0
    assert quante(frase, giornata=1) == 2


def test_la_giornata_che_salta_non_e_quella_in_cui_rientra():
    """«out nella 3a di campionato» diceva che Patric rientrava ieri."""
    patric = (
        "il difensore ai box per un problema fisico e out nella 3a di campionato "
        "contro l'Udinese. Tempi di recupero da valutare."
    )
    assert quante(patric, giornata=3) == 1
    assert not datato(patric), "senza una data di rientro il numero e' una stima"


# -- quando non c'e' nessuna data ----------------------------------------


def test_una_durata_vale_piu_di_un_da_valutare():
    frase = "recupero da valutare, ma rischia uno stop di almeno due mesi."
    assert quante(frase) == 9
    assert not datato(frase)


def test_un_infortunio_lungo_senza_date_non_dura_una_giornata():
    assert quante("in ripresa dalla rottura del legamento crociato.") == 20


def test_da_valutare_e_da_valutare():
    assert quante("Da valutare.") == 1


# -- la pagina ------------------------------------------------------------


PAGINA = """
<div class="team-card"><span class="team-name">Juventus</span><ul>
  <li><strong class="item-name">Yildiz</strong>
      <div class="item-description"><p>rientro da fine novembre.</p></div></li>
  <li><strong class="item-name">Uno Che Non Esiste</strong>
      <div class="item-description"><p>rientro da ottobre.</p></div></li>
</ul></div>
<div class="team-card"><span class="team-name">Inter</span><ul>
  <li><strong class="item-name">Yildiz</strong>
      <div class="item-description"><p>omonimo di un'altra squadra.</p></div></li>
</ul></div>
"""


def test_aggancia_per_squadra_e_nome_e_ignora_chi_non_e_in_listone():
    listone = {("JUV", "yildiz"): 4200}
    esito = analizza(PAGINA, listone, giornata=3, oggi=OGGI)
    assert len(esito) == 1, "l'omonimo dell'Inter non e' nel listone della Juve"
    assert esito[0].id_fc == 4200
    assert esito[0].giornate_fuori == 12
    assert "novembre" in esito[0].testo


def test_il_testo_originale_viaggia_sempre_col_numero():
    """La stima e' una lettura di una frase: la frase deve restare leggibile."""
    esito = analizza(PAGINA, {("JUV", "yildiz"): 4200}, giornata=3, oggi=OGGI)
    assert esito[0].testo.strip() == "rientro da fine novembre."


# -- l'effetto sul motore -------------------------------------------------


def test_le_giornate_saltate_si_tolgono_solo_da_quelle_che_restano():
    """Lo stesso infortunio non vale lo stesso a settembre e ad aprile.

    A settembre dieci giornate sono un pezzo di stagione; ad aprile, quando ne
    restano quattro, sono tutto quello che c'era ancora da giocare.
    """
    fermo = Fermo(giornate_fuori=10)
    sano = _presenze_col_campo(30.0, InCampo(270, 3, 3), "c", None)
    settembre = _presenze_col_campo(30.0, InCampo(270, 3, 3), "c", fermo)
    aprile = _presenze_col_campo(30.0, InCampo(3060, 34, 34), "c", fermo)

    assert settembre == pytest.approx(sano * (35 - 10) / 35, rel=0.02)
    assert aprile == 0.0, "restano quattro giornate e ne salta dieci"


def test_un_infortunio_spiega_i_minuti_mancanti_invece_di_sommarsi():
    """Buongiorno: zero minuti, ma e' il centrale titolare che rientra.

    Senza questa distinzione lo zero verrebbe letto come una gerarchia, e il
    giocatore verrebbe scartato proprio quando costa meno.
    """
    fermo_a_zero = InCampo(minuti=0, presenze=0, giornate=3)
    riserva = _presenze_col_campo(30.0, fermo_a_zero, "d", None)
    infortunato = _presenze_col_campo(
        30.0, fermo_a_zero, "d", Fermo(giornate_fuori=10)
    )
    assert infortunato > riserva


def test_chi_non_e_infortunato_non_viene_toccato():
    sano = InCampo(minuti=270, presenze=3, giornate=3)
    assert _presenze_col_campo(30.0, sano, "c", None) == _presenze_col_campo(
        30.0, sano, "c", Fermo(giornate_fuori=0)
    )
