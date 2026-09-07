"""La stagione dopo l'asta: giornata per giornata, formazione, scambi."""

from __future__ import annotations

import pytest

from fantabot.dati import andamento
from fantabot.motore import formazione as fmz
from fantabot.motore.asta import Acquisto, Squadra, StatoAsta
from fantabot.motore.valutazione import (
    Fermo,
    Giocatore,
    Giudizi,
    InCampo,
    ParametriLega,
    StagioneStat,
    valuta,
)

# -- la differenza fra due fotografie -------------------------------------


@pytest.fixture
def conn_andamento(conn):
    conn.execute(
        "INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo) "
        "VALUES (1, 'Malen', 'malen', 'ROM', 'a')"
    )
    conn.commit()
    return conn


def _foto(conn, giornata, presenze, fantamedia, gol=0, minuti=0, ammonizioni=0):
    conn.execute(
        "INSERT INTO andamento (id_fc, giornata, presenze, fantamedia, media_voto,"
        " gol, ammonizioni, minuti) VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        (giornata, presenze, fantamedia, fantamedia - 3, gol, ammonizioni, minuti),
    )
    conn.commit()


def test_la_differenza_fra_due_totali_e_la_giornata(conn_andamento):
    _foto(conn_andamento, 2, presenze=2, fantamedia=7.0, gol=1, minuti=180)
    _foto(conn_andamento, 3, presenze=3, fantamedia=9.0, gol=3, minuti=270)
    ultimo = andamento.turni(conn_andamento, 1)[0]
    assert ultimo.giornata == 3
    assert ultimo.gol == 2, "due gol in piu' fra le due fotografie"
    assert ultimo.minuti == 90
    assert ultimo.presenze == 1


def test_la_fantamedia_non_si_sottrae(conn_andamento):
    """Passare da 7,0 su 2 partite a 9,0 su 3 vuol dire una domenica da 13."""
    _foto(conn_andamento, 2, presenze=2, fantamedia=7.0)
    _foto(conn_andamento, 3, presenze=3, fantamedia=9.0)
    ultimo = andamento.turni(conn_andamento, 1)[0]
    assert ultimo.fantamedia == pytest.approx(13.0)


def test_una_giornata_saltata_si_dichiara_invece_di_spalmarla(conn_andamento):
    _foto(conn_andamento, 2, presenze=2, fantamedia=6.0)
    _foto(conn_andamento, 5, presenze=5, fantamedia=6.0)
    ultimo = andamento.turni(conn_andamento, 1)[0]
    assert ultimo.coperte == 3, "tre turni in una riga, e va detto"


def test_chi_non_ha_giocato_non_ha_una_fantamedia(conn_andamento):
    _foto(conn_andamento, 2, presenze=2, fantamedia=6.0)
    _foto(conn_andamento, 3, presenze=2, fantamedia=6.0)
    ultimo = andamento.turni(conn_andamento, 1)[0]
    assert not ultimo.giocata
    assert ultimo.fantamedia is None


def test_rileggere_la_stessa_giornata_non_raddoppia_niente(conn_andamento):
    conn_andamento.execute(
        "INSERT INTO statistiche (id_fc, stagione, presenze, fantamedia, gol, giornate)"
        " VALUES (1, '2026-27', 3, 9.0, 3, 3)"
    )
    conn_andamento.commit()
    andamento.fotografa(conn_andamento, 3)
    andamento.fotografa(conn_andamento, 3)
    righe = conn_andamento.execute("SELECT COUNT(*) FROM andamento").fetchone()[0]
    assert righe == 1


# -- la formazione --------------------------------------------------------


def _rosa(parametri: ParametriLega) -> tuple[StatoAsta, Squadra]:
    """Una rosa piccola ma completa, con dentro i casi che contano."""
    listone: list[Giocatore] = []
    acquisti: list[Acquisto] = []
    for indice, (ruolo, quanti) in enumerate((("p", 2), ("d", 6), ("c", 6), ("a", 4))):
        for n in range(quanti):
            id_fc = indice * 100 + n
            listone.append(
                Giocatore(
                    id_fc=id_fc,
                    nome=f"{ruolo.upper()}{n}",
                    squadra="TST",
                    ruolo=ruolo,
                    quota=10,
                    fvm=200 - n * 20,
                    storico=(
                        StagioneStat("2025-26", 34, 6.5 - n * 0.1, media_voto=6.2),
                    ),
                    campo=InCampo(
                        minuti=270, presenze=3, giornate=3, previsto_titolare=True
                    ),
                )
            )
            acquisti.append(
                Acquisto(
                    id_fc=id_fc, nome=f"{ruolo.upper()}{n}", ruolo=ruolo,
                    id_squadra=1, prezzo=10,
                )
            )
    squadra = Squadra(id=1, nome="Io", e_mia=True, acquisti=acquisti)
    stato = StatoAsta(parametri, valuta(listone, parametri), [squadra])
    return stato, squadra


def test_sceglie_il_modulo_invece_di_subirlo():
    parametri = ParametriLega(crediti=500, n_squadre=1, slot={"p": 2, "d": 6, "c": 6, "a": 4})
    stato, squadra = _rosa(parametri)
    c = fmz.consiglia(stato, squadra)
    assert c is not None
    assert c.modulo in fmz.MODULI
    assert len(c.titolari) == 11
    assert sum(1 for s in c.titolari if s.ruolo == "p") == 1


def test_un_infortunato_non_finisce_in_campo():
    parametri = ParametriLega(crediti=500, n_squadre=1, slot={"p": 2, "d": 6, "c": 6, "a": 4})
    stato, squadra = _rosa(parametri)
    migliore = max(
        (v for v in stato.valutazioni.values() if v.giocatore.ruolo == "a"),
        key=lambda v: v.fantamedia_attesa,
    )
    rotto = migliore.giocatore
    stato.valutazioni[rotto.id_fc] = type(migliore)(
        **{
            **migliore.__dict__,
            "giocatore": type(rotto)(
                **{**rotto.__dict__, "fermo": Fermo(giornate_fuori=8)}
            ),
        }
    )
    c = fmz.consiglia(stato, squadra)
    assert rotto.id_fc not in {s.valutazione.giocatore.id_fc for s in c.titolari}


def test_la_probabilita_che_giochi_ha_una_gerarchia_di_fonti():
    """Un infortunio dichiarato batte tutto, poi la formazione, poi i minuti."""
    parametri = ParametriLega(crediti=500, n_squadre=1, slot={"p": 2, "d": 6, "c": 6, "a": 4})
    stato, _ = _rosa(parametri)
    v = next(iter(stato.valutazioni.values()))
    g = v.giocatore

    def con(**campi):
        nuovo = type(g)(**{**g.__dict__, **campi})
        return fmz.probabilita_che_giochi(type(v)(**{**v.__dict__, "giocatore": nuovo}))

    assert con(fermo=Fermo(giornate_fuori=3))[0] == 0.0
    assert con(campo=InCampo(270, 3, 3, previsto_titolare=True))[0] == 1.0
    assert con(campo=InCampo(90, 1, 3, previsto_titolare=False))[0] < 0.4
    assert con(campo=None)[0] == 0.5, "non sapere non e' sapere di no"


def test_la_forma_recente_sposta_il_rendimento_ma_non_lo_riscrive():
    parametri = ParametriLega(crediti=500, n_squadre=1, slot={"p": 2, "d": 6, "c": 6, "a": 4})
    stato, squadra = _rosa(parametri)
    v = next(iter(stato.valutazioni.values()))
    caldo = fmz.rendimento_atteso(v, v.fantamedia_attesa + 3.0)
    assert v.fantamedia_attesa < caldo < v.fantamedia_attesa + 3.0


# -- gli scambi -----------------------------------------------------------


def test_uno_scambio_che_conviene_a_uno_solo_non_e_uno_scambio():
    """Due rose identiche non hanno niente da scambiarsi."""
    parametri = ParametriLega(
        crediti=500, n_squadre=2, slot={"p": 1, "d": 2, "c": 2, "a": 2}
    )
    listone = [
        Giocatore(
            id_fc=i,
            nome=f"G{i}",
            squadra="TST",
            ruolo=r,
            quota=10,
            fvm=100,
            storico=(StagioneStat("2025-26", 34, 6.5, media_voto=6.2),),
        )
        for r in ("p", "d", "c", "a")
        for i in range(
            ("p", "d", "c", "a").index(r) * 10,
            ("p", "d", "c", "a").index(r) * 10 + 6,
        )
    ]
    valutazioni = valuta(listone, parametri)
    prima = Squadra(id=1, nome="Io", e_mia=True)
    seconda = Squadra(id=2, nome="Marco")
    for indice, squadra in enumerate((prima, seconda)):
        for r, quanti in (("p", 1), ("d", 2), ("c", 2), ("a", 2)):
            base = ("p", "d", "c", "a").index(r) * 10 + indice * 3
            for n in range(quanti):
                squadra.acquisti.append(
                    Acquisto(
                        id_fc=base + n, nome=f"G{base + n}", ruolo=r,
                        id_squadra=squadra.id, prezzo=10,
                    )
                )
    stato = StatoAsta(parametri, valutazioni, [prima, seconda])
    for s in fmz.scambi_possibili(stato, prima):
        assert s.guadagno > 0 and s.suo_guadagno > 0


# -- gli abbinamenti di calendario ----------------------------------------


MATRICE = """sigla,ATA,LEC,NAP
ATA,,84,89
LEC,84,,94
NAP,89,94,
"""


def test_una_matrice_si_legge_una_volta_sola_per_coppia(conn):
    from fantabot.dati import coppie

    esito = coppie.importa(conn, MATRICE, "p")
    assert esito.riuscito
    assert esito.coppie == 3, "tre squadre fanno tre coppie, non sei"
    tabella = coppie.leggi(conn, "p")
    assert coppie.punteggio(tabella, "LEC", "NAP") == 94
    assert coppie.punteggio(tabella, "NAP", "LEC") == 94, "e' lo stesso abbinamento"
    assert coppie.punteggio(tabella, "NAP", "NAP") is None


def test_una_matrice_che_si_contraddice_non_entra_a_meta(conn):
    """Le due meta' della tabella devono coincidere, o e' stata letta male."""
    from fantabot.dati import coppie

    storta = MATRICE.replace("NAP,89,94,", "NAP,89,77,")
    esito = coppie.importa(conn, storta, "p")
    assert not esito.riuscito
    assert ("LEC", "NAP") in esito.asimmetrie
    assert coppie.leggi(conn, "p") == {}, "niente entra, nemmeno la parte buona"


def test_la_matrice_vera_del_progetto_e_simmetrica():
    """Trascritta a mano da uno screenshot: la simmetria e' la controprova."""
    from fantabot.dati import coppie

    percorso = coppie.SEMI / coppie.NOMI_FILE["p"]
    if not percorso.exists():  # pragma: no cover - dipende dal checkout
        pytest.skip("la matrice dei portieri non e' nel progetto")
    lette, asimmetrie = coppie.leggi_matrice(percorso.read_text(encoding="utf-8"))
    assert not asimmetrie
    assert len(lette) == 190, "venti squadre fanno centonovanta coppie"


def test_una_squadra_e_rappresentata_da_chi_gioca_non_da_chi_vale():
    """Un abbinamento di calendario ha senso solo fra chi il calendario lo gioca."""
    parametri = ParametriLega(
        crediti=100, n_squadre=2, slot={"p": 1, "d": 1, "c": 1, "a": 1}
    )
    listone = [
        Giocatore(
            id_fc=1, nome="Riserva", squadra="GEN", ruolo="p", quota=1, fvm=50,
            storico=(StagioneStat("2025-26", 30, 6.2, media_voto=6.2),),
            campo=InCampo(minuti=0, presenze=0, giornate=3),
        ),
        Giocatore(
            id_fc=2, nome="Titolare", squadra="GEN", ruolo="p", quota=1, fvm=10,
            campo=InCampo(minuti=270, presenze=3, giornate=3),
        ),
        Giocatore(
            id_fc=3, nome="Altro", squadra="NAP", ruolo="p", quota=1, fvm=30,
            campo=InCampo(minuti=270, presenze=3, giornate=3),
        ),
    ]
    stato = StatoAsta(
        parametri, valuta(listone, parametri), [Squadra(id=1, nome="Io", e_mia=True)]
    )
    coppie_finte = {("GEN", "NAP"): 90}
    trovati = fmz.abbinamenti(stato, coppie_finte, "p")
    assert len(trovati) == 1
    nomi = {trovati[0].primo.giocatore.nome, trovati[0].secondo.giocatore.nome}
    assert nomi == {"Titolare", "Altro"}, "la riserva non rappresenta il Genoa"


def test_l_attacco_si_compone_a_fasce_incrociate():
    """Top con Semi-Top, Terza con Quarta: due Top costano mezzo budget."""
    parametri = ParametriLega(
        crediti=500, n_squadre=2, slot={"p": 1, "d": 1, "c": 1, "a": 4}
    )
    fasce = {1: 1, 2: 2, 3: 3, 4: 4}
    listone = [
        Giocatore(
            id_fc=i,
            nome=f"A{i}",
            squadra=sigla,
            ruolo="a",
            quota=10,
            fvm=200,
            giudizi=Giudizi(fascia=fasce[i]),
        )
        for i, sigla in ((1, "ATA"), (2, "NAP"), (3, "LEC"), (4, "GEN"))
    ]
    stato = StatoAsta(
        parametri,
        valuta(listone, parametri),
        [Squadra(id=1, nome="Io", e_mia=True)],
    )
    tabella = {
        ("ATA", "NAP"): 90,  # Top + Semi-Top
        ("GEN", "LEC"): 95,  # Terza + Quarta
        ("ATA", "LEC"): 99,  # Top + Terza: piu' alto, e non deve uscire
    }
    alti = fmz.abbinamenti(stato, tabella, "a", fasce=(1, 2))
    assert [x.punteggio for x in alti] == [90], "il 99 incrocia le fasce sbagliate"
    assert alti[0].fasce == (1, 2), "il Top va per primo anche se la tabella no"

    bassi = fmz.abbinamenti(stato, tabella, "a", fasce=(3, 4))
    assert [x.punteggio for x in bassi] == [95]


def test_completare_parte_dal_giocatore_non_dalla_sua_squadra():
    """La Roma ha Malen e Dybala: sono due fasce e due domande diverse."""
    parametri = ParametriLega(
        crediti=500, n_squadre=2, slot={"p": 1, "d": 1, "c": 1, "a": 4}
    )
    listone = [
        Giocatore(id_fc=1, nome="Malen", squadra="ROM", ruolo="a", quota=10, fvm=300),
        Giocatore(id_fc=2, nome="Dybala", squadra="ROM", ruolo="a", quota=10, fvm=200),
        Giocatore(id_fc=3, nome="Altro", squadra="NAP", ruolo="a", quota=10, fvm=200),
    ]
    valutazioni = valuta(listone, parametri)
    stato = StatoAsta(
        parametri, valutazioni, [Squadra(id=1, nome="Io", e_mia=True)]
    )
    trovati = fmz.abbinamenti(
        stato, {("NAP", "ROM"): 90}, "a", partendo_da=valutazioni[1]
    )
    nomi = {x.primo.giocatore.nome for x in trovati} | {
        x.secondo.giocatore.nome for x in trovati
    }
    assert "Malen" in nomi
    assert "Dybala" not in nomi, "il compagno di squadra non lo rappresenta"
