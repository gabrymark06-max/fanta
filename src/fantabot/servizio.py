"""Il ponte fra il database e il motore: quello che il bot chiama davvero.

Tiene in memoria le valutazioni, che costano qualche decimo di secondo e non
cambiano finche' non cambia il listone o una regola della lega. Lo stato
dell'asta invece si ricostruisce sempre da zero, perche' cambia a ogni
assegnazione ed e' l'unica cosa che non ci si puo' permettere di leggere
vecchia.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .dati import calendario
from .dati.andamento import forma
from .dati.esterno import prezzi_esterni
from .dati.magazzino import carica_giocatori, fuori_lista
from .db import transazione
from .motore.asta import Acquisto, Squadra, StatoAsta
from .motore.formazione import Avversario
from .motore.valutazione import (
    RUOLI,
    ParametriLega,
    Valutazione,
    forza_club,
    valuta,
)

NOMI_SQUADRE_DEFAULT = "Avversario {n}"


@dataclass
class Lega:
    id: int
    chat_id: int
    nome: str
    parametri: ParametriLega
    prudenza: float
    # Chi ha il turno di chiamare (indice nell'ordine delle squadre) e, se la
    # lega gioca a reparti, quale reparto e' in ballo.
    turno: int = 0
    reparto: str = ""
    # Da quale giornata comincia questa lega. Chi fa l'asta a campionato
    # iniziato parte dalla quarta, e le prime tre non lo riguardano.
    prima_giornata: int = 1


class Servizio:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._valutazioni: dict[tuple, dict[int, Valutazione]] = {}

    # -- la lega ----------------------------------------------------------

    def lega(self, chat_id: int) -> Lega | None:
        r = self.conn.execute(
            "SELECT * FROM leghe WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return self._a_lega(r) if r else None

    @staticmethod
    def _a_lega(r: sqlite3.Row) -> Lega:
        return Lega(
            id=r["id"],
            chat_id=r["chat_id"],
            nome=r["nome"],
            parametri=ParametriLega(
                crediti=r["crediti"],
                n_squadre=r["n_squadre"],
                slot={
                    "p": r["slot_p"],
                    "d": r["slot_d"],
                    "c": r["slot_c"],
                    "a": r["slot_a"],
                },
                modificatore_difesa=bool(r["modificatore"]),
                offerte_segrete=bool(r["buste"]),
            ),
            prudenza=r["prudenza"],
            turno=r["turno"],
            reparto=r["reparto"],
            prima_giornata=r["prima_giornata"],
        )

    def imposta_prima_giornata(self, lega: Lega, giornata: int) -> None:
        with transazione(self.conn) as c:
            c.execute(
                "UPDATE leghe SET prima_giornata = ? WHERE id = ?",
                (max(1, min(giornata, calendario.GIORNATE)), lega.id),
            )

    def crea_lega(
        self,
        chat_id: int,
        *,
        crediti: int = 500,
        n_squadre: int = 8,
        slot: dict[str, int] | None = None,
        modificatore_difesa: bool = False,
        offerte_segrete: bool = False,
        nome_mia: str = "La mia squadra",
    ) -> Lega:
        """Crea o riconfigura la lega di questa chat.

        Riconfigurare a asta iniziata cancella gli acquisti: i prezzi
        dipendono dal budget, e tenere assegnazioni fatte con regole diverse
        darebbe consigli sbagliati senza dirlo. Il bot avvisa prima.
        """
        slot = slot or {"p": 3, "d": 8, "c": 8, "a": 6}
        with transazione(self.conn):
            self.conn.execute(
                """
                INSERT INTO leghe (chat_id, crediti, n_squadre, slot_p, slot_d,
                                   slot_c, slot_a, modificatore, buste)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    crediti = excluded.crediti,
                    n_squadre = excluded.n_squadre,
                    slot_p = excluded.slot_p,
                    slot_d = excluded.slot_d,
                    slot_c = excluded.slot_c,
                    slot_a = excluded.slot_a,
                    modificatore = excluded.modificatore,
                    buste = excluded.buste
                """,
                (
                    chat_id,
                    crediti,
                    n_squadre,
                    slot["p"],
                    slot["d"],
                    slot["c"],
                    slot["a"],
                    int(modificatore_difesa),
                    int(offerte_segrete),
                ),
            )
            lega = self.lega(chat_id)
            assert lega is not None
            self.conn.execute("DELETE FROM acquisti WHERE id_lega = ?", (lega.id,))
            self.conn.execute("DELETE FROM squadre WHERE id_lega = ?", (lega.id,))
            self.conn.execute(
                "INSERT INTO squadre (id_lega, nome, e_mia) VALUES (?, ?, 1)",
                (lega.id, nome_mia),
            )
            self.conn.executemany(
                "INSERT INTO squadre (id_lega, nome, e_mia) VALUES (?, ?, 0)",
                [
                    (lega.id, NOMI_SQUADRE_DEFAULT.format(n=n))
                    for n in range(1, n_squadre)
                ],
            )
        self._valutazioni.clear()
        return lega

    def rinomina_squadre(self, lega: Lega, nomi: list[str]) -> int:
        """Sostituisce i nomi degli avversari, nell'ordine dato."""
        avversari = self.conn.execute(
            "SELECT id FROM squadre WHERE id_lega = ? AND e_mia = 0 ORDER BY id",
            (lega.id,),
        ).fetchall()
        cambiati = 0
        with transazione(self.conn):
            # Meno nomi che avversari e' legittimo: rinomina quelli dati.
            for r, nome in zip(avversari, nomi, strict=False):
                self.conn.execute(
                    "UPDATE squadre SET nome = ? WHERE id = ?", (nome.strip(), r["id"])
                )
                cambiati += 1
        return cambiati

    def imposta_prudenza(self, lega: Lega, prudenza: float) -> None:
        with transazione(self.conn):
            self.conn.execute(
                "UPDATE leghe SET prudenza = ? WHERE id = ?", (prudenza, lega.id)
            )

    def imposta_turno(self, lega: Lega, indice: int) -> None:
        with transazione(self.conn):
            self.conn.execute(
                "UPDATE leghe SET turno = ? WHERE id = ?", (indice, lega.id)
            )

    def imposta_reparto(self, lega: Lega, ruolo: str) -> None:
        """Il reparto in asta adesso. Stringa vuota = chiamata libera."""
        with transazione(self.conn):
            self.conn.execute(
                "UPDATE leghe SET reparto = ? WHERE id = ?", (ruolo, lega.id)
            )

    def squadre(self, lega: Lega) -> list[Squadra]:
        righe = self.conn.execute(
            "SELECT id, nome, e_mia FROM squadre WHERE id_lega = ? ORDER BY e_mia DESC, id",
            (lega.id,),
        ).fetchall()
        squadre = {
            r["id"]: Squadra(id=r["id"], nome=r["nome"], e_mia=bool(r["e_mia"]))
            for r in righe
        }
        for a in self.conn.execute(
            """
            SELECT a.id_fc, a.id_squadra, a.prezzo, g.nome, g.ruolo
            FROM acquisti a JOIN giocatori g ON g.id_fc = a.id_fc
            WHERE a.id_lega = ? ORDER BY a.id
            """,
            (lega.id,),
        ):
            squadra = squadre.get(a["id_squadra"])
            if squadra is not None:
                squadra.acquisti.append(
                    Acquisto(
                        id_fc=a["id_fc"],
                        nome=a["nome"],
                        ruolo=a["ruolo"],
                        id_squadra=a["id_squadra"],
                        prezzo=a["prezzo"],
                    )
                )
        return list(squadre.values())

    # -- valutazioni e stato ----------------------------------------------

    def valutazioni(self, lega: Lega) -> dict[int, Valutazione]:
        p = lega.parametri
        # Ogni cosa che cambia i numeri entra nella chiave, comprese le due
        # regole: una cache che ignora una regola serve valutazioni vecchie
        # senza dirlo, ed e' il tipo di errore che non si vede mai.
        chiave = (
            p.crediti,
            p.n_squadre,
            tuple(sorted(p.slot.items())),
            p.modificatore_difesa,
            p.offerte_segrete,
            self._versione_dati(),
        )
        if chiave not in self._valutazioni:
            self._valutazioni.clear()
            self._valutazioni[chiave] = valuta(
                carica_giocatori(self.conn), p, prezzi_esterni(self.conn)
            )
        return self._valutazioni[chiave]

    def invalida_cache(self) -> None:
        """Da chiamare dopo un aggiornamento del listone."""
        self._valutazioni.clear()

    def _versione_dati(self) -> str:
        r = self.conn.execute(
            "SELECT max(aggiornato_il) AS v, count(*) AS n FROM giocatori"
        ).fetchone()
        e = self.conn.execute(
            "SELECT max(importato_il) AS v, count(*) AS n FROM mercato_esterno"
        ).fetchone()
        return f"{r['v']}|{r['n']}|{e['v']}|{e['n']}"

    def stato(self, lega: Lega) -> StatoAsta:
        return StatoAsta(
            lega.parametri,
            self.valutazioni(lega),
            self.squadre(lega),
            self.preferenze(lega),
            prezzi_esterni(self.conn),
        )

    # -- registrazione degli acquisti -------------------------------------

    def registra(self, lega: Lega, id_fc: int, id_squadra: int, prezzo: int) -> str | None:
        """Assegna un giocatore. Restituisce un messaggio d'errore, o None.

        Rifiuta quello che in asta non puo' succedere: un giocatore gia'
        assegnato, un reparto pieno, una squadra che non ha i crediti. Meglio
        un rifiuto secco adesso che una rosa che non torna alla fine.
        """
        gia = self.conn.execute(
            """
            SELECT s.nome, a.prezzo FROM acquisti a JOIN squadre s ON s.id = a.id_squadra
            WHERE a.id_lega = ? AND a.id_fc = ?
            """,
            (lega.id, id_fc),
        ).fetchone()
        if gia:
            return (
                f"Gia' assegnato a {gia['nome']} per {gia['prezzo']}. "
                "Usa /annulla se e' un errore."
            )

        g = self.conn.execute(
            "SELECT nome, ruolo FROM giocatori WHERE id_fc = ?", (id_fc,)
        ).fetchone()
        if g is None:
            return "Non trovo questo giocatore nel listone."
        if g["ruolo"] not in RUOLI:
            # Capita a inizio stagione: un arrivo dell'ultima ora entra nel
            # listone prima che gli assegnino il ruolo. Va detto, non fatto
            # esplodere in mezzo a un'asta.
            return (
                f"{g['nome']} e' nel listone senza un ruolo assegnato: "
                "non posso contarlo in nessun reparto. Riprova dopo /aggiorna."
            )

        stato = self.stato(lega)
        squadra = next((s for s in stato.squadre if s.id == id_squadra), None)
        if squadra is None:
            return "Non trovo questa squadra."
        if stato.slot_mancanti(squadra)[g["ruolo"]] <= 0:
            return f"{squadra.nome} ha gia' completato il reparto."
        residui = stato.crediti_residui(squadra)
        slot_dopo = stato.slot_mancanti_totali(squadra) - 1
        if prezzo > residui - slot_dopo:
            return (
                f"{squadra.nome} non puo' spendere {prezzo}: ha {residui} crediti "
                f"e {slot_dopo + 1} slot da riempire (max {max(0, residui - slot_dopo)})."
            )

        with transazione(self.conn):
            self.conn.execute(
                "INSERT INTO acquisti (id_lega, id_fc, id_squadra, prezzo) "
                "VALUES (?, ?, ?, ?)",
                (lega.id, id_fc, id_squadra, prezzo),
            )
        # IL TURNO AVANZA DA SOLO, ed e' l'unico modo perche' resti giusto:
        # all'asta nessuno si ricorda di aggiornare un contatore, e un turno
        # sbagliato e' peggio di nessun turno. Si ricalcola sullo stato DOPO
        # l'acquisto, cosi' chi ha appena completato il reparto e' gia' fuori
        # dal giro al momento di passare la mano.
        dopo = self.stato(lega)
        self.imposta_turno(
            lega, dopo.prossimo_turno(lega.turno, lega.reparto or None)
        )
        return None

    def annulla_ultimo(self, lega: Lega) -> str | None:
        r = self.conn.execute(
            """
            SELECT a.id, a.prezzo, g.nome, s.nome AS squadra
            FROM acquisti a
            JOIN giocatori g ON g.id_fc = a.id_fc
            JOIN squadre s ON s.id = a.id_squadra
            WHERE a.id_lega = ? ORDER BY a.id DESC LIMIT 1
            """,
            (lega.id,),
        ).fetchone()
        if r is None:
            return None
        with transazione(self.conn):
            self.conn.execute("DELETE FROM acquisti WHERE id = ?", (r["id"],))
        return f"{r['nome']} ({r['squadra']}, {r['prezzo']})"

    def annulla_giocatore(self, lega: Lega, id_fc: int) -> str | None:
        """Toglie un giocatore assegnato, anche se non e' l'ultimo.

        A meta' asta ci si accorge di aver battuto 45 invece di 4 tre chiamate
        prima: senza questo si dovrebbe disfare tutto quello che viene dopo.
        """
        r = self.conn.execute(
            """
            SELECT a.id, a.prezzo, g.nome, s.nome AS squadra
            FROM acquisti a
            JOIN giocatori g ON g.id_fc = a.id_fc
            JOIN squadre s ON s.id = a.id_squadra
            WHERE a.id_lega = ? AND a.id_fc = ?
            """,
            (lega.id, id_fc),
        ).fetchone()
        if r is None:
            return None
        with transazione(self.conn):
            self.conn.execute("DELETE FROM acquisti WHERE id = ?", (r["id"],))
        return f"{r['nome']} ({r['squadra']}, {r['prezzo']})"

    def correggi_prezzo(self, lega: Lega, id_fc: int, prezzo: int) -> str | None:
        """Cambia la cifra di un acquisto gia' registrato, senza rifarlo."""
        r = self.conn.execute(
            """
            SELECT a.id, a.id_squadra, a.prezzo, g.nome
            FROM acquisti a JOIN giocatori g ON g.id_fc = a.id_fc
            WHERE a.id_lega = ? AND a.id_fc = ?
            """,
            (lega.id, id_fc),
        ).fetchone()
        if r is None:
            return "Quel giocatore non risulta assegnato."
        stato = self.stato(lega)
        squadra = next((s for s in stato.squadre if s.id == r["id_squadra"]), None)
        if squadra is None:
            return "Non trovo la squadra a cui era assegnato."
        # I crediti disponibili tornano a comprendere quelli gia' impegnati su
        # questo giocatore: e' una correzione, non un secondo acquisto.
        residui = stato.crediti_residui(squadra) + r["prezzo"]
        slot_altri = stato.slot_mancanti_totali(squadra)
        if prezzo > residui - slot_altri:
            return (
                f"{squadra.nome} non puo' arrivare a {prezzo}: "
                f"il massimo e' {max(0, residui - slot_altri)}."
            )
        with transazione(self.conn):
            self.conn.execute(
                "UPDATE acquisti SET prezzo = ? WHERE id = ?", (prezzo, r["id"])
            )
        return None

    # -- preferenze --------------------------------------------------------

    def forma_recente(self, giornate: int = 3) -> dict[int, float]:
        """La fantamedia delle ultime giornate, per chi ne ha abbastanza."""
        righe = self.conn.execute(
            "SELECT DISTINCT id_fc FROM andamento"
        ).fetchall()
        esito: dict[int, float] = {}
        for r in righe:
            recente = forma(self.conn, r["id_fc"], giornate)
            if recente is not None and recente.fantamedia is not None:
                esito[r["id_fc"]] = recente.fantamedia
        return esito

    def sposta(self, lega: Lega, id_fc: int, id_squadra: int | None) -> str | None:
        """Un giocatore cambia proprietario a stagione in corso.

        Uno scambio nel fantacalcio non e' un acquisto: il prezzo pagato
        all'asta resta quello, perche' e' quello che ha consumato il budget e
        rifarlo cambierebbe i crediti di due squadre per un movimento che i
        crediti non li tocca. `id_squadra` a None significa svincolato.
        """
        riga = self.conn.execute(
            "SELECT a.id, g.nome, g.ruolo FROM acquisti a"
            " JOIN giocatori g ON g.id_fc = a.id_fc"
            " WHERE a.id_lega = ? AND a.id_fc = ?",
            (lega.id, id_fc),
        ).fetchone()
        if riga is None:
            return "Quel giocatore non risulta di nessuno."
        if id_squadra is None:
            with transazione(self.conn):
                self.conn.execute("DELETE FROM acquisti WHERE id = ?", (riga["id"],))
            return None
        stato = self.stato(lega)
        squadra = next((s for s in stato.squadre if s.id == id_squadra), None)
        if squadra is None:
            return "Non trovo questa squadra."
        if stato.slot_mancanti(squadra)[riga["ruolo"]] <= 0:
            return (
                f"{squadra.nome} ha gia' il reparto pieno: "
                "prima togli qualcuno con l'altra meta' dello scambio."
            )
        with transazione(self.conn):
            self.conn.execute(
                "UPDATE acquisti SET id_squadra = ? WHERE id = ?",
                (id_squadra, riga["id"]),
            )
        return None

    def imposta_preferenza(self, lega: Lega, id_fc: int, grado: int) -> None:
        with transazione(self.conn):
            self.conn.execute(
                """
                INSERT INTO preferenze (id_lega, id_fc, grado) VALUES (?, ?, ?)
                ON CONFLICT(id_lega, id_fc) DO UPDATE SET grado = excluded.grado
                """,
                (lega.id, id_fc, grado),
            )

    def preferenze(self, lega: Lega) -> dict[int, int]:
        return {
            r["id_fc"]: r["grado"]
            for r in self.conn.execute(
                "SELECT id_fc, grado FROM preferenze WHERE id_lega = ?", (lega.id,)
            )
        }

    # -- il calendario ----------------------------------------------------

    def giornata_di_oggi(self, lega: Lega) -> int:
        """La prima giornata non ancora giocata, mai prima dell'inizio della lega.

        Una lega che parte dalla quarta non ha nessun interesse per le prime
        tre: quelle partite sono gia' state giocate da altri.
        """
        oggi = datetime.now().strftime("%Y-%m-%d")
        return calendario.prossima_giornata(
            self.conn, oggi, da=max(1, lega.prima_giornata)
        )

    def avversari(self, stato: StatoAsta, giornata: int) -> dict[str, Avversario]:
        """Chi incontra ogni squadra di Serie A in quella giornata, e quanto pesa.

        La forza dei club esce dalle valutazioni gia' calcolate invece che da
        una lettura nuova: e' lo stesso numero che regge i prezzi, e due stime
        diverse della stessa cosa nello stesso messaggio sono un bug che si
        vede solo mesi dopo.
        """
        partite = calendario.per_squadra(self.conn, giornata)
        if not partite:
            return {}
        forze = calendario.normalizza_forze(
            forza_club([v.giocatore for v in stato.valutazioni.values()])
        )
        return {
            sigla: Avversario(
                sigla=p.avversario_di(sigla),
                in_casa=p.in_casa(sigla),
                difficolta=calendario.difficolta(p, sigla, forze),
            )
            for sigla, p in partite.items()
        }

    def conta_giocatori(self) -> int:
        return self.conn.execute("SELECT count(*) FROM giocatori").fetchone()[0]

    def fuori_lista(self) -> list[sqlite3.Row]:
        """Chi il bot ha smesso di consigliare, e da quale maglia arrivava.

        Non e' un dettaglio da nascondere: e' l'unico posto in cui si vede se
        il file delle fasce ha tolto chi doveva — uno andato via a mercato
        aperto — o se ha tolto un titolare solo perche' il suo nome li' dentro
        e' scritto in un altro modo. La differenza si vede solo leggendo
        l'elenco, quindi l'elenco deve esistere.
        """
        fuori = fuori_lista(self.conn)
        if not fuori:
            return []
        segnaposto = ",".join("?" * len(fuori))
        return self.conn.execute(
            f"""
            SELECT g.id_fc, g.nome, g.squadra, g.ruolo, g.quota_attuale, g.fvm,
                   COALESCE(c.minuti, 0) AS minuti
            FROM giocatori g LEFT JOIN campo c ON c.id_fc = g.id_fc
            WHERE g.id_fc IN ({segnaposto})
            ORDER BY g.fvm DESC, g.quota_attuale DESC
            """,
            tuple(sorted(fuori)),
        ).fetchall()
