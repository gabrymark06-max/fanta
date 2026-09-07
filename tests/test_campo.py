"""Chi sta giocando davvero: aggancio dei nomi, lettura delle fonti, effetto.

Nessuno di questi test tocca la rete. Le due fonti hanno una forma precisa e
si rompono cambiando forma, quindi le risposte sono qui dentro nella stessa
forma in cui sono arrivate il 6 settembre 2026 — accorciate, non inventate.

I casi di nome non sono immaginati: sono i cinque che sono stati visti fallire
sul listone vero, uno per specie.
"""

from __future__ import annotations

import pytest

from fantabot.dati import campo
from fantabot.motore.valutazione import (
    GIORNATE_PER_CREDERCI,
    RUOLI,
    InCampo,
    _presenze_col_campo,
    disponibilita_osservata,
)

# -- i nomi ---------------------------------------------------------------


@pytest.mark.parametrize(
    "nostro, loro",
    [
        # Il caso semplice: cognome contro nome intero.
        ("Malen", "Donyell Malen"),
        # Iniziale puntata sola, da confermare sul nome proprio.
        ("Marin R.", "Rafa Marin"),
        # Due iniziali attaccate: "d.s." non deve diventare un cognome corto.
        ("Ederson D.S.", "Ederson De Souza"),
        # Il caso vero: loro scrivono SOLO il cognome, e le nostre iniziali
        # non hanno niente da confermare. Non e' una contraddizione.
        ("Ederson D.S.", "Éderson"),
        ("Esposito F.P.", "Francesco Pio Esposito"),
        # Il NOSTRO nome ha una parola in piu' del loro.
        ("Zambo Anguissa", "Frank Anguissa"),
        # Lettere che la scomposizione Unicode non separa.
        ("Hojlund", "Rasmus Højlund"),
        ("Ostigard", "Leo Østigard"),
        # Tre apostrofi diversi per la stessa persona.
        ("N'Dri", "Konan N’Dri"),
    ],
)
def test_aggancia_le_forme_di_nome_viste_fallire(nostro, loro):
    esito = campo.abbina(
        [(1, nostro, "NAP")], {"NAP": [campo.Rendimento(nome=loro, squadra="NAP")]}
    )
    assert 1 in esito, f"{nostro!r} non ha raggiunto {loro!r}"


def test_il_soprannome_piu_corto_arriva_solo_dopo_gli_esatti():
    """"Valde" e' Valdepenas, ma non deve rubare la riga a chi ha un esatto."""
    loro = {
        "FIO": [
            campo.Rendimento(nome="Valde", squadra="FIO", minuti=190),
            campo.Rendimento(nome="Nicolo Valentini", squadra="FIO", minuti=50),
        ]
    }
    esito = campo.abbina([(1, "Valdepenas", "FIO"), (2, "Valentini", "FIO")], loro)
    assert esito[1].minuti == 190
    assert esito[2].minuti == 50


def test_due_candidati_uguali_si_scartano_invece_di_indovinare():
    """Meglio nessun minuto che i minuti del compagno di squadra."""
    loro = {
        "MIL": [
            campo.Rendimento(nome="Thiago Silva", squadra="MIL", minuti=200),
            campo.Rendimento(nome="Bruno Silva", squadra="MIL", minuti=10),
        ]
    }
    assert campo.abbina([(1, "Silva", "MIL")], loro) == {}


def test_la_squadra_sbagliata_non_aggancia():
    loro = {"ROM": [campo.Rendimento(nome="Donyell Malen", squadra="ROM")]}
    assert campo.abbina([(1, "Malen", "JUV")], loro) == {}


# -- fotmob ---------------------------------------------------------------


def _lista(*righe: dict) -> dict:
    return {"TopLists": [{"StatList": list(righe)}]}


def _riga(nome: str, squadra: str, minuti: int, partite: int, valore=None) -> dict:
    return {
        "ParticipantName": nome,
        "TeamName": squadra,
        "MinutesPlayed": minuti,
        "MatchesPlayed": partite,
        "StatValue": valore if valore is not None else minuti,
    }


def test_legge_minuti_voti_e_giornate_per_squadra():
    frammenti = {
        campo.MINUTI: _lista(
            _riga("Alex Meret", "Napoli", 270, 3),
            _riga("Scott McTominay", "Napoli", 146, 2),
            # La Juventus ha giocato una partita in meno: e' il suo
            # denominatore, non quello del campionato.
            _riga("Kenan Yildiz", "Juventus", 69, 1),
            _riga("Manuel Locatelli", "Juventus", 180, 2),
        ),
        campo.VOTO: _lista(_riga("Alex Meret", "Napoli", 270, 3, valore=6.68)),
    }
    per_sigla = campo.leggi_minuti(frammenti=frammenti)

    meret = next(r for r in per_sigla["NAP"] if r.nome == "Alex Meret")
    assert meret.giornate_squadra == 3
    assert meret.quota_minuti == 1.0
    assert meret.voto_fotmob == 6.68

    yildiz = next(r for r in per_sigla["JUV"] if r.nome == "Kenan Yildiz")
    assert yildiz.giornate_squadra == 2, "la Juventus ha giocato due partite"
    assert yildiz.quota_minuti == pytest.approx(69 / 180)


def test_una_squadra_che_non_conosciamo_viene_ignorata():
    frammenti = {campo.MINUTI: _lista(_riga("Tizio", "Real Madrid", 270, 3))}
    assert campo.leggi_minuti(frammenti=frammenti) == {}


# -- sportsgambler --------------------------------------------------------


def _frammento(casa: list[str], ospiti: list[str]) -> str:
    def blocco(nomi):
        return "".join(
            f'<div class="player-profile">{i + 1}</div>'
            f'<div class="player-name">{n}</div>'
            for i, n in enumerate(nomi)
        )

    return (
        f'<div class="lineups-home">{blocco(casa)}</div>'
        f'<div class="lineups-away">{blocco(ospiti)}</div>'
    )


def test_i_due_lati_finiscono_alle_squadre_giuste():
    frammenti = [
        ("1", "Inter Milan", "AC Milan", _frammento(["Yann Sommer"], ["Mike Maignan"]))
    ]
    esito = campo.leggi_formazioni(frammenti=frammenti)
    assert esito.per_squadra["INT"] == {"yann sommer"}
    assert esito.per_squadra["MIL"] == {"mike maignan"}
    assert esito.squadre_lette == {"INT", "MIL"}


def test_una_partita_senza_formazione_non_dice_che_sono_tutti_in_panchina():
    esito = campo.leggi_formazioni(
        frammenti=[("1", "Napoli", "Roma", "<div>pubblicita'</div>")]
    )
    assert esito.squadre_lette == set()


def test_il_cartellone_lega_ogni_id_alle_sue_due_squadre():
    html = (
        '<span class="fxs-team home">Juventus</span>'
        '<span class="fxs-team">AC Milan</span>'
        '<a onClick="reply_click(5749667)">Predicted Lineups</a>'
        '<span class="fxs-team home">Napoli</span>'
        '<span class="fxs-team">Roma</span>'
        '<a onClick="reply_click(5749661)">Predicted Lineups</a>'
    )
    assert campo._cartellone(html) == [
        ("5749667", "Juventus", "AC Milan"),
        ("5749661", "Napoli", "Roma"),
    ]


def test_chi_non_ha_mai_giocato_ma_e_previsto_ottiene_una_riga():
    """Il titolare che rientra da un infortunio: nei minuti non esiste."""
    nostri = [(1, "Buongiorno", "NAP"), (2, "Contini", "NAP")]
    rendimenti: dict[int, campo.Rendimento] = {}
    previsti = campo.Formazioni(per_squadra={"NAP": {"alessandro buongiorno"}})
    campo.innesta_previsioni(nostri, rendimenti, previsti, {"NAP": 3})

    assert rendimenti[1].previsto_titolare is True
    assert rendimenti[1].minuti == 0
    assert rendimenti[1].giornate_squadra == 3
    # E chi non c'e' prende comunque la sua riga, con il "no" dentro: senza,
    # sarebbe indistinguibile da uno di cui non abbiamo guardato la partita.
    assert rendimenti[2].previsto_titolare is False


def test_una_squadra_di_cui_non_abbiamo_letto_la_formazione_resta_muta():
    nostri = [(1, "Dimarco", "INT")]
    rendimenti = {1: campo.Rendimento(nome="Federico Dimarco", squadra="INT")}
    campo.innesta_previsioni(
        nostri, rendimenti, campo.Formazioni(per_squadra={"NAP": {"alex meret"}}), {}
    )
    assert rendimenti[1].previsto_titolare is None


# -- l'effetto sul motore -------------------------------------------------


def test_il_subentrante_fisso_non_e_un_titolare():
    """Lucca: tre partite su tre e quaranta minuti in tutto."""
    dentro_sempre = InCampo(minuti=270, presenze=3, giornate=3)
    subentra = InCampo(minuti=40, presenze=3, giornate=3)
    assert disponibilita_osservata(dentro_sempre) == 1.0
    assert disponibilita_osservata(subentra) == pytest.approx(40 / 180)


def test_una_squalifica_costa_una_giornata_non_la_stagione():
    saltata = InCampo(minuti=180, presenze=2, giornate=3)
    assert disponibilita_osservata(saltata) == pytest.approx(2 / 3)


def test_previsto_titolare_alza_ma_non_esserlo_non_abbassa():
    fermo = InCampo(minuti=0, presenze=0, giornate=3, previsto_titolare=True)
    assert disponibilita_osservata(fermo) == pytest.approx(0.70)

    titolare_a_riposo = InCampo(
        minuti=270, presenze=3, giornate=3, previsto_titolare=False
    )
    assert disponibilita_osservata(titolare_a_riposo) == 1.0


def test_senza_dati_di_campo_le_presenze_non_si_toccano():
    assert _presenze_col_campo(30.0, None) == 30.0
    assert _presenze_col_campo(30.0, InCampo(minuti=0, presenze=0, giornate=0)) == 30.0


def test_zero_minuti_abbassa_le_presenze_senza_azzerarle():
    """Tre giornate sono un indizio forte, non una sentenza."""
    corrette = _presenze_col_campo(
        30.0, InCampo(minuti=0, presenze=0, giornate=3), "c"
    )
    assert 0 < corrette < 30.0
    peso = 3 / (3 + GIORNATE_PER_CREDERCI["c"])
    assert corrette == pytest.approx(38.0 * (1 - peso) * (30.0 / 38.0))


def test_per_un_portiere_lo_stesso_zero_pesa_di_piu():
    """Una squadra schiera un portiere per novanta minuti: niente turnover."""
    fermo = InCampo(minuti=0, presenze=0, giornate=3)
    assert _presenze_col_campo(30.0, fermo, "p") < _presenze_col_campo(
        30.0, fermo, "c"
    )


def test_il_peso_del_campo_cresce_con_le_giornate():
    """A dicembre quello che si vede deve contare piu' che a settembre."""
    settembre = _presenze_col_campo(30.0, InCampo(0, 0, 3), "c")
    dicembre = _presenze_col_campo(30.0, InCampo(0, 0, 15), "c")
    assert dicembre < settembre


def test_chi_gioca_tutto_guadagna_presenze():
    sempre = InCampo(minuti=270, presenze=3, giornate=3)
    assert _presenze_col_campo(25.0, sempre, "d") > 25.0


# -- il turno di chiamata -------------------------------------------------


def _stato(slot=None, presi=None):
    """Uno stato d'asta minimo: quattro squadre, un listone finto."""
    from fantabot.motore.asta import Acquisto, Squadra, StatoAsta
    from fantabot.motore.valutazione import Giocatore, ParametriLega, valuta

    parametri = ParametriLega(
        crediti=100, n_squadre=4, slot=slot or {"p": 1, "d": 1, "c": 1, "a": 1}
    )
    listone = [
        Giocatore(
            id_fc=i,
            nome=f"G{i}",
            squadra="TST",
            ruolo=r,
            quota=5,
            fvm=50 - i,
        )
        for r in ("p", "d", "c", "a")
        for i in range(RUOLI.index(r) * 20, RUOLI.index(r) * 20 + 12)
    ]
    squadre = [
        Squadra(id=1, nome="Io", e_mia=True),
        Squadra(id=2, nome="Marco"),
        Squadra(id=3, nome="Luca"),
        Squadra(id=4, nome="Giulia"),
    ]
    for id_squadra, id_fc, ruolo, prezzo in presi or []:
        squadre[id_squadra - 1].acquisti.append(
            Acquisto(
                id_fc=id_fc,
                nome=f"G{id_fc}",
                ruolo=ruolo,
                id_squadra=id_squadra,
                prezzo=prezzo,
            )
        )
    return StatoAsta(parametri, valuta(listone, parametri), squadre)


def test_chi_ha_chiuso_il_reparto_viene_saltato():
    """La regola del tavolo: reparto pieno, si passa la mano."""
    stato = _stato(presi=[(2, 0, "p", 10), (3, 1, "p", 10)])
    # Il turno e' di Marco (indice 1), che pero' il portiere ce l'ha gia'.
    assert stato.chi_chiama(1, "p").nome == "Giulia"
    # Sui difensori invece Marco puo' ancora chiamare.
    assert stato.chi_chiama(1, "d").nome == "Marco"


def test_chi_ha_finito_i_crediti_e_fuori_dal_giro_quanto_chi_ha_la_rosa_piena():
    stato = _stato(presi=[(2, 0, "p", 100)])
    marco = next(s for s in stato.squadre if s.nome == "Marco")
    assert not stato.puo_chiamare(marco)


def test_il_turno_gira_e_torna():
    stato = _stato()
    assert stato.prossimo_turno(0) == 1
    assert stato.prossimo_turno(3) == 0


def test_sapere_di_essere_rimasto_solo_su_un_reparto():
    """E' la situazione che vale piu' crediti di tutta l'asta."""
    stato = _stato(presi=[(2, 0, "p", 5), (3, 1, "p", 5), (4, 2, "p", 5)])
    assert stato.reparti_solo_miei() == ["p"]
    assert [s.nome for s in stato.chi_cerca("p")] == ["Io"]


def test_finche_qualcuno_cerca_quel_reparto_non_sono_solo():
    stato = _stato(presi=[(2, 0, "p", 5), (3, 1, "p", 5)])
    assert "p" not in stato.reparti_solo_miei()


def test_ad_asta_finita_non_chiama_piu_nessuno():
    """Rose piene: non c'e' un "prossimo", e va detto invece di girare a vuoto."""
    tutte_piene = [
        (squadra, squadra * 10 + posto, ruolo, 5)
        for squadra in (1, 2, 3, 4)
        for posto, ruolo in enumerate(("p", "d", "c", "a"))
    ]
    assert _stato(presi=tutte_piene).chi_chiama(0) is None
