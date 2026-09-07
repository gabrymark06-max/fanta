"""Il calendario, e i controlli che una trascrizione a mano deve superare.

Il file vero e' stato copiato da un PDF: 380 righe scritte a mano, dove un
errore non si vede rileggendo. Le tre condizioni qui sotto sono l'unica prova
che quella copiatura regge — e ne hanno gia' trovati due, che senza sarebbero
finiti dentro il bot come partite vere.
"""

from __future__ import annotations

from fantabot.dati import calendario as K


def _riga(giornata: int, casa: str, ospite: str, data: str = "2026-08-23") -> str:
    return f"{giornata},{data},{casa},{ospite}"


def _mini(coppie: list[tuple[str, str]], giornata: int = 1) -> str:
    """Un calendario giocattolo a quattro squadre, per i casi limite."""
    righe = ["giornata,data,casa,ospite"]
    righe += [_riga(giornata, a, b) for a, b in coppie]
    return "\n".join(righe)


# -- il calendario vero ---------------------------------------------------


def test_il_seme_e_un_calendario_valido():
    """Le tre condizioni sul file che il progetto si porta dietro."""
    partite = K.leggi_csv(K.SEME.read_text(encoding="utf-8"))
    assert len(partite) == 380
    assert K.controlla(partite) == []


def test_il_seme_copre_tutte_le_giornate():
    partite = K.leggi_csv(K.SEME.read_text(encoding="utf-8"))
    assert sorted({p.giornata for p in partite}) == list(range(1, K.GIORNATE + 1))


def test_ogni_coppia_si_incontra_due_volte():
    """Andata e ritorno, una volta per casa. E' la struttura del torneo."""
    partite = K.leggi_csv(K.SEME.read_text(encoding="utf-8"))
    incontri: dict[frozenset[str], int] = {}
    for p in partite:
        chiave = frozenset({p.casa, p.ospite})
        incontri[chiave] = incontri.get(chiave, 0) + 1
    assert set(incontri.values()) == {2}


# -- i controlli trovano davvero qualcosa ---------------------------------


def test_una_squadra_due_volte_nella_stessa_giornata(conn):
    """L'errore vero trovato nel PDF: MILAN due volte alla tredicesima."""
    problemi = K.controlla(
        K.leggi_csv(_mini([("AAA", "BBB"), ("CCC", "BBB")]))
    )
    assert any("due volte BBB" in p for p in problemi)


def test_la_stessa_partita_in_due_giornate():
    testo = "\n".join(
        [
            "giornata,data,casa,ospite",
            _riga(1, "AAA", "BBB"),
            _riga(2, "AAA", "BBB", "2026-08-30"),
        ]
    )
    problemi = K.controlla(K.leggi_csv(testo))
    assert any("giocata due volte" in p for p in problemi)


def test_le_date_non_tornano_indietro():
    testo = "\n".join(
        [
            "giornata,data,casa,ospite",
            _riga(1, "AAA", "BBB", "2026-09-20"),
            _riga(2, "CCC", "DDD", "2026-08-30"),
        ]
    )
    assert any("tornano indietro" in p for p in K.controlla(K.leggi_csv(testo)))


def test_un_calendario_rotto_non_si_importa_a_meta(conn):
    """Meglio nessun calendario che uno con un buco.

    Un buco fa dire al bot che una squadra riposa quando invece gioca, e chi
    ha il dato sbagliato non lo sa: e' un consiglio peggiore del silenzio.
    """
    esito = K.importa(conn, _mini([("AAA", "BBB"), ("CCC", "BBB")]))
    assert not esito.riuscito
    assert conn.execute("SELECT COUNT(*) FROM calendario").fetchone()[0] == 0


# -- leggerlo -------------------------------------------------------------


def test_importa_e_rilegge(conn):
    esito = K.importa(conn, K.SEME.read_text(encoding="utf-8"))
    assert esito.riuscito
    assert esito.partite == 380 and esito.giornate == 38
    quarta = K.per_squadra(conn, 4)
    assert quarta["NAP"].casa == "NAP" and quarta["NAP"].ospite == "BOL"
    assert quarta["BOL"].avversario_di("BOL") == "NAP"
    assert quarta["BOL"].in_casa("BOL") is False


def test_il_seme_non_sovrascrive_un_calendario_gia_caricato(conn):
    K.importa(conn, K.SEME.read_text(encoding="utf-8"))
    conn.execute("DELETE FROM calendario WHERE giornata > 1")
    conn.commit()
    assert K.carica_seme(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM calendario").fetchone()[0] == 10


def test_la_prossima_giornata_parte_da_dove_dici(conn):
    """Una lega che comincia dalla quarta non guarda mai le prime tre."""
    K.carica_seme(conn)
    assert K.prossima_giornata(conn, "2026-08-24", da=1) == 2
    assert K.prossima_giornata(conn, "2026-08-24", da=4) == 4
    # A stagione finita non si va oltre l'ultima.
    assert K.prossima_giornata(conn, "2027-12-31", da=1) == 38


# -- quanto e' dura una partita -------------------------------------------


def test_le_forze_normalizzate_stanno_fra_meno_uno_e_uno():
    forze = K.normalizza_forze({"FORTE": 3000.0, "MEDIA": 900.0, "DEBOLE": 300.0})
    assert forze["FORTE"] == 1.0
    assert forze["DEBOLE"] == -1.0
    assert -1.0 < forze["MEDIA"] < 1.0


def test_giocare_in_casa_rende_la_partita_piu_facile():
    forze = K.normalizza_forze({"AAA": 3000.0, "BBB": 300.0})
    in_casa = K.Partita(giornata=1, casa="BBB", ospite="AAA")
    fuori = K.Partita(giornata=2, casa="AAA", ospite="BBB")
    assert K.difficolta(in_casa, "BBB", forze) < K.difficolta(fuori, "BBB", forze)


def test_l_avversario_forte_alza_la_difficolta():
    forze = K.normalizza_forze({"AAA": 3000.0, "BBB": 300.0, "CCC": 900.0})
    contro_forte = K.Partita(giornata=1, casa="CCC", ospite="AAA")
    contro_debole = K.Partita(giornata=1, casa="CCC", ospite="BBB")
    assert K.difficolta(contro_forte, "CCC", forze) > K.difficolta(
        contro_debole, "CCC", forze
    )
