"""Le regole che l'asta non puo' violare, qualunque cosa dica il modello.

Sono i test che contano davvero: un consiglio mediocre costa qualche punto a
fine stagione, un consiglio che ti lascia senza portiere costa la stagione.
"""

from __future__ import annotations

import random

import pytest

from fantabot.motore.asta import Acquisto, Squadra, StatoAsta
from fantabot.motore.valutazione import RUOLI, valuta


@pytest.fixture
def stato(listone, parametri):
    val = valuta(listone, parametri)
    squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
        Squadra(id=i, nome=f"Avv{i}") for i in range(1, parametri.n_squadre)
    ]
    return StatoAsta(parametri, val, squadre)


def _compra(stato, squadra, ruolo, quanti, prezzo):
    """Riempie una squadra senza passare dai controlli, per costruire scenari."""
    liberi = [
        v
        for v in stato.disponibili()
        if v.giocatore.ruolo == ruolo and v.giocatore.id_fc not in stato.presi
    ]
    for v in liberi[:quanti]:
        squadra.acquisti.append(
            Acquisto(v.giocatore.id_fc, v.giocatore.nome, ruolo, squadra.id, prezzo)
        )
        stato.presi[v.giocatore.id_fc] = squadra
    stato.invalida()


def test_non_si_offre_mai_tanto_da_non_poter_completare_la_rosa(stato, parametri):
    mia = stato.mia
    _compra(stato, mia, "a", 5, 80)  # ne restano 20 di slot e pochi crediti
    tetto = stato.tetto_liquidita(mia)
    residui = stato.crediti_residui(mia)
    slot_dopo = stato.slot_mancanti_totali(mia) - 1
    assert tetto == max(0, residui - slot_dopo)
    for v in stato.disponibili()[:40]:
        c = stato.consiglia(v.giocatore.id_fc)
        if c is not None:
            assert c.massimo <= tetto


def test_reparto_completo_significa_non_offrire(stato):
    mia = stato.mia
    _compra(stato, mia, "p", 3, 10)
    portiere = next(v for v in stato.disponibili() if v.giocatore.ruolo == "p")
    c = stato.consiglia(portiere.giocatore.id_fc)
    assert c.massimo == 0
    assert c.giudizio == "lascialo"


def test_il_tetto_dei_reparti_tiene_da_parte_per_gli_altri_ruoli(stato):
    mia = stato.mia
    attaccante = next(v for v in stato.disponibili() if v.giocatore.ruolo == "a")
    tetto_reparti = stato.tetto_reparti(mia, "a")
    tetto_liquidita = stato.tetto_liquidita(mia)
    # Con la rosa ancora tutta da fare, mettere da parte per i reparti e'
    # piu' severo che tenere un credito per slot.
    assert tetto_reparti < tetto_liquidita
    c = stato.consiglia(attaccante.giocatore.id_fc)
    assert c.massimo <= tetto_reparti


def test_i_prezzi_salgono_se_la_lega_spende_poco(stato):
    """Se i big vanno via a due lire, i crediti restano e tutto il resto rincara."""
    prima = dict(stato.prezzi_correnti())
    for squadra in stato.squadre:
        _compra(stato, squadra, "a", 3, 1)
    dopo = stato.prezzi_correnti()
    rimasti = [v for v in stato.disponibili() if v.fascia < 5]
    assert stato.inflazione() > 1.05
    campione = rimasti[0].giocatore.id_fc
    assert dopo[campione] > prima[campione]


def test_i_prezzi_scendono_se_la_lega_ha_speso_tutto(stato):
    for squadra in stato.squadre:
        _compra(stato, squadra, "a", 3, 90)
    assert stato.inflazione() < 1.0


def test_chi_ha_piu_crediti_degli_altri_offre_di_piu(listone, parametri):
    """L'agio e' il rapporto fra i miei crediti per slot e quelli degli altri.

    Non si misura sul massimo consigliato: quel numero e' anche tagliato dai
    tetti, e a inizio asta e' il tetto dei reparti a decidere.
    """
    val = valuta(listone, parametri)

    def scenario(spesa_altrui: int):
        squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
            Squadra(id=i, nome=f"Avv{i}") for i in range(1, parametri.n_squadre)
        ]
        stato = StatoAsta(parametri, val, squadre)
        for s in squadre[1:]:
            _compra(stato, s, "d", 4, spesa_altrui)
        obiettivo = next(v for v in stato.disponibili() if v.giocatore.ruolo == "c")
        return stato, stato.consiglia(obiettivo.giocatore.id_fc)

    _, consiglio_ricco = scenario(60)  # gli altri hanno svuotato la cassa
    _, consiglio_pari = scenario(2)  # gli altri hanno ancora tutto
    assert consiglio_ricco.agio > consiglio_pari.agio


def test_l_agio_conta_poco_all_inizio_e_molto_alla_fine(listone, parametri):
    """I crediti che avanzano valgono zero, ma solo quando l'asta finisce.

    Alla terza chiamata avere piu' soldi degli altri vuol dire soltanto che
    non hai ancora comprato, e davanti hai tutto il mercato. All'ultima vuol
    dire che stai per buttarli. Senza questa scala il bot consigliava di
    pagare un attaccante molto sopra il suo valore al quarto d'asta.
    """
    val = valuta(listone, parametri)

    def agio_dopo(quanti_difensori: int) -> tuple[float, float]:
        squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
            Squadra(id=i, nome=f"Avv{i}") for i in range(1, parametri.n_squadre)
        ]
        stato = StatoAsta(parametri, val, squadre)
        for s in squadre[1:]:
            _compra(stato, s, "d", quanti_difensori, 40)
            _compra(stato, s, "c", quanti_difensori, 20)
        return stato.avanzamento(), stato._agio(stato.mia)

    inizio, agio_inizio = agio_dopo(2)
    tardi, agio_tardi = agio_dopo(8)
    assert inizio < tardi
    assert agio_inizio < agio_tardi
    # A inizio asta il fattore e' quasi neutro: non deve poter far pagare
    # sopra il valore quando c'e' ancora tutto il mercato davanti.
    assert agio_inizio < 1.15


def test_la_simulazione_chiude_sempre_la_rosa(listone, parametri):
    """La proprieta' che non si negozia: 25 giocatori, budget rispettato.

    Si gioca l'asta intera contro avversari che offrono a caso attorno al
    prezzo corrente. Con qualunque seme, seguendo il bot la rosa si chiude e
    i crediti bastano.
    """
    val = valuta(listone, parametri)
    for seme in range(5):
        random.seed(seme)
        squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
            Squadra(id=i, nome=f"Avv{i}") for i in range(1, parametri.n_squadre)
        ]
        for v in sorted(val.values(), key=lambda v: -v.prezzo_mercato):
            stato = StatoAsta(parametri, val, squadre)
            if stato.slot_mancanti_totali(stato.mia) == 0 and all(
                stato.slot_mancanti_totali(s) == 0 for s in squadre
            ):
                break
            ruolo = v.giocatore.ruolo
            prezzo = stato.prezzi_correnti().get(v.giocatore.id_fc, 1.0)
            offerte = []
            for s in squadre[1:]:
                if stato.slot_mancanti(s)[ruolo] <= 0:
                    continue
                offerte.append(
                    (
                        min(
                            int(prezzo * random.uniform(0.7, 1.3)),
                            stato.tetto_liquidita(s),
                        ),
                        s,
                    )
                )
            c = stato.consiglia(v.giocatore.id_fc)
            if c and c.massimo > 0:
                offerte.append((c.massimo, squadre[0]))
            offerte = [(p, s) for p, s in offerte if p >= 1]
            if not offerte:
                continue
            prezzo_finale, vincitore = max(offerte, key=lambda t: t[0])
            vincitore.acquisti.append(
                Acquisto(
                    v.giocatore.id_fc,
                    v.giocatore.nome,
                    ruolo,
                    vincitore.id,
                    max(1, prezzo_finale),
                )
            )

        mia = squadre[0]
        assert len(mia.acquisti) == parametri.slot_per_squadra, f"seme {seme}"
        assert mia.spesa() <= parametri.crediti, f"seme {seme}"
        for ruolo in RUOLI:
            assert mia.presi_per_ruolo(ruolo) == parametri.slot[ruolo]


def test_il_piano_di_spesa_distribuisce_tutti_i_crediti(stato):
    piano = stato.piano_spesa()
    assert abs(sum(piano.values()) - stato.crediti_residui(stato.mia)) <= 4


def test_le_occasioni_non_propongono_reparti_gia_pieni(stato):
    mia = stato.mia
    _compra(stato, mia, "p", 3, 5)
    for c in stato.occasioni(limite=20):
        assert c.valutazione.giocatore.ruolo != "p"


def test_a_buste_chiuse_si_offre_il_proprio_massimo(listone):
    """Senza rilancio non esiste "il secondo piu' uno".

    Chi offre la cifra che sarebbe bastata scopre di aver perso il giocatore
    per un credito, e non ha un secondo giro per rimediare: la cifra giusta e'
    il proprio limite.
    """
    from fantabot.motore.valutazione import ParametriLega

    def consiglio(segrete: bool):
        par = ParametriLega(crediti=500, n_squadre=8, offerte_segrete=segrete)
        val = valuta(listone, par)
        squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
            Squadra(id=i, nome=f"Avv{i}") for i in range(1, par.n_squadre)
        ]
        stato = StatoAsta(par, val, squadre)
        obiettivo = max(stato.disponibili(), key=lambda v: v.valore)
        return stato.consiglia(obiettivo.giocatore.id_fc)

    rilancio = consiglio(False)
    buste = consiglio(True)
    assert rilancio.serve < rilancio.massimo
    assert buste.serve == buste.massimo
    assert any("offerta unica" in m for m in buste.motivi)


def _asta_con_prezzi(listone, parametri, quanto_paga):
    """Costruisce uno stato in cui la lega ha pagato secondo una regola data."""
    val = valuta(listone, parametri)
    squadre = [Squadra(id=0, nome="IO", e_mia=True)] + [
        Squadra(id=i, nome=f"Avv{i}") for i in range(1, parametri.n_squadre)
    ]
    stato = StatoAsta(parametri, val, squadre)
    venduti = sorted(val.values(), key=lambda v: -v.prezzo_mercato)[:16]
    for indice, v in enumerate(venduti):
        squadra = squadre[1 + indice % (len(squadre) - 1)]
        prezzo = max(1, int(quanto_paga(v.prezzo_mercato)))
        squadra.acquisti.append(
            Acquisto(
                v.giocatore.id_fc,
                v.giocatore.nome,
                v.giocatore.ruolo,
                squadra.id,
                prezzo,
            )
        )
        stato.presi[v.giocatore.id_fc] = squadra
    stato.invalida()
    return stato


def test_il_bot_impara_se_in_questa_lega_i_big_vanno_cari(listone, parametri):
    """La forma del mercato la detta il tavolo, non il listone.

    Se i campioni si pagano molto sopra il listino e la fascia media si
    svende, il listino iniziale sbaglia entrambi: la curva va resa piu'
    ripida, e l'unica fonte affidabile su questa lega e' questa lega.
    """
    fedele = _asta_con_prezzi(listone, parametri, lambda p: p)
    ripida = _asta_con_prezzi(listone, parametri, lambda p: (p**1.35) / 3)
    piatta = _asta_con_prezzi(listone, parametri, lambda p: 3 * p**0.6)

    assert 0.9 < fedele.pendenza_di_mercato() < 1.15
    assert ripida.pendenza_di_mercato() > 1.2
    assert piatta.pendenza_di_mercato() < 0.9


def test_una_lega_che_paga_caro_i_big_alza_il_prezzo_dei_big_rimasti(listone, parametri):
    ripida = _asta_con_prezzi(listone, parametri, lambda p: (p**1.35) / 3)
    migliore = max(ripida.disponibili(), key=lambda v: v.prezzo_mercato)
    corrente = ripida.prezzi_correnti()[migliore.giocatore.id_fc]
    assert corrente > migliore.prezzo_mercato


def test_prima_di_dieci_assegnazioni_non_si_stima_niente(listone, parametri):
    """Due nomi pagati a casaccio darebbero una curva ripidissima."""
    val = valuta(listone, parametri)
    squadre = [Squadra(id=0, nome="IO", e_mia=True), Squadra(id=1, nome="Avv")]
    stato = StatoAsta(parametri, val, squadre)
    caro = max(val.values(), key=lambda v: v.prezzo_mercato)
    squadre[1].acquisti.append(
        Acquisto(caro.giocatore.id_fc, caro.giocatore.nome, caro.giocatore.ruolo, 1, 300)
    )
    stato.presi[caro.giocatore.id_fc] = squadre[1]
    stato.invalida()
    assert stato.pendenza_di_mercato() == 1.0
