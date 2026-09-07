"""Il motore di valutazione deve reggere tre promesse.

Che i prezzi sommino il budget della lega, che il valore misuri il vantaggio
sul rimpiazzo e non i punti totali, e che un giocatore senza storico riceva
comunque una stima invece di uno zero.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fantabot.motore.valutazione import (
    RUOLI,
    Giocatore,
    Giudizi,
    ParametriLega,
    StagioneStat,
    valuta,
)


def test_i_prezzi_sommano_il_budget_della_lega(listone, parametri):
    v = valuta(listone, parametri)
    comprabili = [x for x in v.values() if x.fascia < 5]
    assert len(comprabili) == parametri.slot_totali
    somma = sum(x.prezzo_mercato for x in comprabili)
    assert abs(somma - parametri.budget_totale) < 1.0


def test_il_budget_cambia_con_le_regole_della_lega(listone):
    piccola = valuta(listone, ParametriLega(crediti=250, n_squadre=8))
    grande = valuta(listone, ParametriLega(crediti=1000, n_squadre=8))
    top_piccola = max(x.prezzo_mercato for x in piccola.values())
    top_grande = max(x.prezzo_mercato for x in grande.values())
    # Quattro volte i crediti, all'incirca quattro volte il prezzo: se il bot
    # non lo facesse, consiglierebbe le cifre di una lega che non e' la tua.
    assert 3.5 < top_grande / top_piccola < 4.5


def test_ogni_ruolo_ha_esattamente_i_suoi_slot_fra_i_comprabili(listone, parametri):
    v = valuta(listone, parametri)
    for ruolo in RUOLI:
        dentro = [
            x for x in v.values() if x.giocatore.ruolo == ruolo and x.fascia < 5
        ]
        assert len(dentro) == parametri.slot_ruolo_lega(ruolo), ruolo


def test_nessun_prezzo_sotto_un_credito(listone, parametri):
    v = valuta(listone, parametri)
    assert all(x.prezzo_mercato >= 1.0 for x in v.values())
    assert all(x.valore >= 1.0 for x in v.values())


def test_il_valore_premia_la_fantamedia_non_le_sole_presenze(listone, parametri):
    """Un fuoriclasse che gioca due terzi delle partite batte un onesto che le gioca tutte.

    E' la differenza fra sommare i punti di stagione e misurare il vantaggio
    su chi lo rimpiazza in panchina: la prima formula diceva il contrario.
    """
    from fantabot.motore.valutazione import StagioneStat

    fuoriclasse = Giocatore(
        id_fc=9001,
        nome="Fuoriclasse",
        squadra="TST",
        ruolo="c",
        quota=20,
        fvm=150,
        storico=(StagioneStat("2025-26", 25, 8.0, media_voto=7.0),),
    )
    onesto = Giocatore(
        id_fc=9002,
        nome="Onesto",
        squadra="TST",
        ruolo="c",
        quota=20,
        fvm=150,
        storico=(StagioneStat("2025-26", 38, 6.1, media_voto=6.0),),
    )
    v = valuta([*listone, fuoriclasse, onesto], parametri)
    assert v[9001].valore > v[9002].valore


def test_chi_non_ha_mai_giocato_in_serie_a_riceve_comunque_una_stima(listone, parametri):
    """Il colpo di mercato dall'estero non deve valere zero solo perche' e' nuovo."""
    nuovo = Giocatore(
        id_fc=9003,
        nome="Straniero",
        squadra="TST",
        ruolo="a",
        quota=30,
        fvm=300,
        storico=(),
    )
    v = valuta([*listone, nuovo], parametri)
    stima = v[9003]
    assert stima.fantamedia_attesa > 6.0
    assert stima.presenze_attese > 15
    assert stima.prezzo_mercato > 20


def test_il_listone_vuoto_non_esplode(parametri):
    assert valuta([], parametri) == {}


def test_un_ruolo_con_meno_giocatori_degli_slot_non_esplode(parametri):
    solo_pochi = [
        Giocatore(id_fc=i, nome=f"P{i}", squadra="TST", ruolo="p", quota=5, fvm=10)
        for i in range(1, 4)
    ]
    v = valuta(solo_pochi, parametri)
    assert len(v) == 3
    assert all(x.prezzo_mercato >= 1.0 for x in v.values())


def _con_club(indice, ruolo, club, club_storico, fvm, fantamedia, presenze=32):
    """Un giocatore con uno storico costruito in un club preciso."""
    from fantabot.motore.valutazione import StagioneStat

    return Giocatore(
        id_fc=indice,
        nome=f"G{indice}",
        squadra=club,
        ruolo=ruolo,
        quota=max(1, fvm // 12),
        fvm=fvm,
        storico=(
            StagioneStat("2025-26", presenze, fantamedia, squadra=club_storico),
            StagioneStat("2024-25", presenze, fantamedia, squadra=club_storico),
        ),
    )


def _lega_finta_con_due_club():
    """Un campionato in miniatura dove il club conta *oltre* al giocatore.

    I due club hanno la stessa distribuzione di FVM - stessi giocatori sulla
    carta - ma nel club ricco tutti rendono mezzo voto in piu', e il club
    ricco ha una rosa piu' ampia, quindi una forza complessiva maggiore. E'
    lo scenario in cui il contesto porta informazione che il FVM non ha gia':
    se il modello non la trova qui, non la trova da nessuna parte.
    """
    giocatori = []
    indice = 1
    for club, quanti, bonus in (("RIC", 40, 0.5), ("POV", 15, 0.0)):
        for ruolo in RUOLI:
            for posizione in range(quanti):
                qualita = 1 - posizione / (quanti + 5)
                giocatori.append(
                    _con_club(
                        indice,
                        ruolo,
                        club,
                        club,
                        fvm=max(1, int(200 * qualita**2)),
                        fantamedia=5.6 + 1.8 * qualita + bonus,
                    )
                )
                indice += 1
    return giocatori


def test_chi_cambia_club_viene_riportato_al_contesto_di_adesso(parametri):
    """Lo storico di un trasferito e' stato costruito da un'altra parte.

    Due giocatori identici per FVM e rendimento passato: uno e' sempre stato
    nel club ricco, l'altro arriva dal club povero. Il secondo ha preso quei
    voti in una squadra peggiore, quindi in quella nuova ci si aspetta di piu'.
    """
    base = _lega_finta_con_due_club()
    fermo = _con_club(9101, "a", "RIC", "RIC", fvm=90, fantamedia=6.6)
    arrivato = _con_club(9102, "a", "RIC", "POV", fvm=90, fantamedia=6.6)
    v = valuta([*base, fermo, arrivato], parametri)
    assert v[9102].fantamedia_attesa > v[9101].fantamedia_attesa
    # E chi va nella direzione opposta perde qualcosa.
    ceduto = _con_club(9103, "a", "POV", "RIC", fvm=90, fantamedia=6.6)
    v2 = valuta([*base, fermo, ceduto], parametri)
    assert v2[9103].fantamedia_attesa < v2[9101].fantamedia_attesa


def test_la_correzione_del_club_resta_dentro_limiti_ragionevoli(parametri):
    base = _lega_finta_con_due_club()
    arrivato = _con_club(9104, "a", "RIC", "POV", fvm=90, fantamedia=6.6)
    v = valuta([*base, arrivato], parametri)
    # Il contesto sposta il rendimento, non riscrive il giocatore.
    assert abs(v[9104].fantamedia_attesa - 6.6) < 1.0


def test_senza_squadra_nello_storico_non_si_corregge_niente(listone, parametri):
    """Il listone di prova non ha club: il motore deve funzionare uguale."""
    v = valuta(listone, parametri)
    assert all(x.fantamedia_attesa > 0 for x in v.values())


def test_la_forza_dei_club_somma_i_fvm():
    from fantabot.motore.valutazione import ROSA_MINIMA_PER_CONTARE, forza_club

    rosa_vera = [
        _con_club(i, "c", "AAA", "AAA", fvm=10, fantamedia=6.0)
        for i in range(ROSA_MINIMA_PER_CONTARE)
    ]
    forze = forza_club(rosa_vera)
    assert forze == {"AAA": 10 * ROSA_MINIMA_PER_CONTARE}


def test_le_sigle_con_pochi_giocatori_non_sono_squadre():
    """Un residuo del listone non puo' fare da "squadra piu' debole".

    Con una sigla da due nomi dentro le forze, chi arrivava da un club fuori
    listone si ritrovava due punti di fantamedia regalati: un portiere da un
    credito finiva primo fra le occasioni.
    """
    from fantabot.motore.valutazione import ROSA_MINIMA_PER_CONTARE, forza_club

    giocatori = [
        _con_club(i, "c", "AAA", "AAA", fvm=10, fantamedia=6.0)
        for i in range(ROSA_MINIMA_PER_CONTARE)
    ]
    giocatori.append(_con_club(999, "c", "ZZZ", "ZZZ", fvm=1, fantamedia=5.0))
    forze = forza_club(giocatori)
    assert "AAA" in forze
    assert "ZZZ" not in forze


def test_la_correzione_di_club_non_supera_mai_mezzo_voto(parametri):
    """Il tetto sta sulla correzione, non sul coefficiente.

    Limitare il coefficiente non basta: un salto di club abbastanza grande lo
    moltiplica comunque fino all'assurdo, ed e' quello che succedeva a chi
    arrivava da una squadra retrocessa - fuori dal listone, quindi con forza
    sconosciuta e un salto enorme.
    """
    from fantabot.motore.valutazione import (
        MASSIMO_SPOSTAMENTO_CLUB,
        _storico_pesato,
        forza_club,
    )

    base = _lega_finta_con_due_club()
    forze = forza_club(base)
    # Arriva da un club che non esiste piu' nel listone.
    arrivato = _con_club(9301, "a", "RIC", "SPARITO", fvm=90, fantamedia=5.0)
    _, fantamedia, _, _ = _storico_pesato(arrivato, forze, (5.0, 5.0))
    assert abs(fantamedia - 5.0) <= MASSIMO_SPOSTAMENTO_CLUB + 1e-9


def test_i_prezzi_osservati_prendono_il_posto_della_stima(listone, parametri):
    """Un dato raccolto su migliaia di aste batte qualunque formula.

    Il motore il prezzo lo puo' solo stimare dal FVM; un tool che osserva le
    aste vere lo sa. Quando arriva, la stima si fa da parte - e chi non ha il
    dato resta sulla stima, con le due scale riportate l'una sull'altra.
    """
    v = valuta(listone, parametri)
    comprabili = [x for x in v.values() if x.fascia < 5]
    piu_caro = max(comprabili, key=lambda x: x.prezzo_mercato)
    meno_caro = min(comprabili, key=lambda x: x.prezzo_mercato)

    # Un listino che ribalta la gerarchia: il bot deve seguirlo, non il FVM.
    osservati = {
        piu_caro.giocatore.id_fc: 5.0,
        meno_caro.giocatore.id_fc: 200.0,
    }
    for x in comprabili[:40]:
        osservati.setdefault(x.giocatore.id_fc, x.prezzo_mercato)

    dopo = valuta(listone, parametri, osservati)
    assert dopo[meno_caro.giocatore.id_fc].prezzo_mercato > (
        dopo[piu_caro.giocatore.id_fc].prezzo_mercato
    )
    # E il budget continua a tornare: e' il vincolo che non si tocca mai.
    somma = sum(x.prezzo_mercato for x in dopo.values() if x.fascia < 5)
    assert abs(somma - parametri.budget_totale) < 1.0


def test_pochi_prezzi_osservati_non_sballano_le_scale(listone, parametri):
    """Due dati non bastano: mescolare due scale diverse e' peggio che stimare."""
    prima = valuta(listone, parametri)
    caro = max(prima.values(), key=lambda x: x.prezzo_mercato)
    dopo = valuta(listone, parametri, {caro.giocatore.id_fc: 999.0})
    assert dopo[caro.giocatore.id_fc].prezzo_mercato == pytest.approx(
        caro.prezzo_mercato
    )


# -- la stagione in corso, che e' lunga tre giornate ------------------------


def _con_stagione_in_corso(g: Giocatore, **campi) -> Giocatore:
    """Lo stesso giocatore, con davanti allo storico la stagione che si gioca."""
    return replace(
        g,
        storico=(StagioneStat("2026-27", giornate=3, **campi),) + g.storico,
    )


def test_tre_giornate_non_diventano_una_stagione_in_infermeria(listone, parametri):
    """Tre presenze a settembre valgono trentotto, non tre."""
    g = next(x for x in listone if x.ruolo == "c" and x.storico[0].presenze > 25)
    prima = valuta(listone, parametri)[g.id_fc]

    sano = _con_stagione_in_corso(g, presenze=3, fantamedia=g.storico[0].fantamedia)
    dopo = valuta([sano if x.id_fc == g.id_fc else x for x in listone], parametri)
    assert dopo[g.id_fc].presenze_attese == pytest.approx(
        prima.presenze_attese, abs=0.6
    )


def test_i_bonus_di_adesso_entrano_nei_voti_ma_pesati_per_presenze(
    listone, parametri
):
    """Cinque gol in tre partite spostano la stima, non la ribaltano."""
    g = next(x for x in listone if x.ruolo == "a" and x.storico[0].presenze > 25)
    prima = valuta(listone, parametri)[g.id_fc]

    esplosivo = _con_stagione_in_corso(
        g, presenze=3, fantamedia=g.storico[0].fantamedia + 4.0, gol=5
    )
    dopo = valuta([esplosivo if x.id_fc == g.id_fc else x for x in listone], parametri)[
        g.id_fc
    ]
    assert dopo.fantamedia_attesa > prima.fantamedia_attesa
    # Tre presenze contro trentaquattro: al massimo un decimo dello scarto.
    assert dopo.fantamedia_attesa - prima.fantamedia_attesa < 0.5


def test_chi_in_serie_a_non_c_era_mai_stato_ora_ha_qualcosa_da_dire(parametri):
    """Malen: nessuno storico, e cinque gol in tre partite."""
    listone_finto = [
        Giocatore(
            id_fc=900 + i,
            nome=f"A{i}",
            squadra="TST",
            ruolo="a",
            quota=20,
            fvm=200,
            storico=(StagioneStat("2025-26", 30, 7.0, media_voto=6.2),),
        )
        for i in range(12)
    ]
    nuovo = Giocatore(
        id_fc=999, nome="Nuovo", squadra="TST", ruolo="a", quota=20, fvm=200
    )
    senza = valuta(listone_finto + [nuovo], parametri)[999]
    con = valuta(
        listone_finto
        + [_con_stagione_in_corso(nuovo, presenze=3, fantamedia=12.3, gol=5)],
        parametri,
    )[999]
    assert con.fantamedia_attesa > senza.fantamedia_attesa


# -- i giudizi di un listino esterno --------------------------------------


def test_la_titolarita_dichiarata_sposta_le_presenze_attese(listone, parametri):
    """Ogni gradino vale meno partite del precedente, e il giudizio pesa meta'.

    Non si pretende che un 5 alzi sempre: per un titolarissimo che il modello
    gia' dava a trentasei presenze, "titolarita' 5" e' semmai un promemoria che
    anche i titolarissimi ne saltano qualcuna. Quello che deve valere sempre e'
    l'ordine.
    """
    g = next(x for x in listone if x.ruolo == "c")
    senza = valuta(listone, parametri)[g.id_fc].presenze_attese

    def con(voto):
        modificato = replace(g, giudizi=Giudizi(titolarita=voto))
        altri = [x if x.id_fc != g.id_fc else modificato for x in listone]
        return valuta(altri, parametri)[g.id_fc].presenze_attese

    assert con(5) > con(3) > con(1)
    assert con(1) < senza, "un giudizio basso deve poter smentire il modello"


def test_l_integrita_bassa_toglie_presenze_senza_azzerarle(listone, parametri):
    """Chi si fa male spesso gioca meno, non gioca zero."""
    g = next(x for x in listone if x.ruolo == "a")

    def con(voto):
        modificato = replace(g, giudizi=Giudizi(titolarita=5, integrita=voto))
        altri = [x if x.id_fc != g.id_fc else modificato for x in listone]
        return valuta(altri, parametri)[g.id_fc].presenze_attese

    fragile, solido = con(1), con(5)
    assert fragile < solido
    assert fragile > 0.7 * solido, "e' uno sconto, non una condanna"


def test_l_affidabilita_non_tocca_nessun_numero(listone, parametri):
    """Parla della varianza, e il motore stima medie: si mostra e basta."""
    g = next(x for x in listone if x.ruolo == "d")
    valori = []
    for voto in (1, 5):
        modificato = replace(g, giudizi=Giudizi(affidabilita=voto))
        altri = [x if x.id_fc != g.id_fc else modificato for x in listone]
        valori.append(valuta(altri, parametri)[g.id_fc].valore)
    assert valori[0] == valori[1]


def test_la_continuita_conta_le_domeniche_consegnate(listone, parametri):
    """Due stagioni a meta' valgono meno di due stagioni piene, e basta.

    Non si pretende che distingua l'infortunio dalla panchina: le presenze non
    lo sanno, e la funzione dichiara di misurare le domeniche consegnate.
    """
    from fantabot.motore.valutazione import continuita_stimata

    piene = (
        StagioneStat("2025-26", 34, 6.5),
        StagioneStat("2024-25", 33, 6.4),
    )
    mezze = (
        StagioneStat("2025-26", 18, 6.5),
        StagioneStat("2024-25", 17, 6.4),
    )
    assert continuita_stimata(piene, 34.0) > continuita_stimata(mezze, 34.0)


def test_con_una_sola_stagione_la_continuita_non_si_pronuncia():
    """Malen aveva diciotto presenze perche' e' arrivato a gennaio."""
    from fantabot.motore.valutazione import continuita_stimata

    una = (StagioneStat("2025-26", 18, 8.9),)
    assert continuita_stimata(una, 34.0) == 0, "zero vuol dire non lo so"
    assert continuita_stimata((), 34.0) == 0
