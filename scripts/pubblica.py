"""Legge il mondo qui, e lo spedisce dove il bot vive.

Si lancia da GitHub Actions, che internet ce l'ha tutto. In quattro passi:

  1. scarica da PythonAnywhere il pacco della volta scorsa, se c'e'. Serve a
     non ripartire da zero: le statistiche storiche non cambiano e riscaricarle
     ogni sei ore sarebbe cortese come bussare di notte;
  2. aggiorna tutte le fonti dentro quel database;
  3. ne esporta le sole tabelle rileggibili — la lega, le rose e il tuo foglio
     delle fasce non ci sono e non ci devono essere: quel file passa per la rete
     e finisce nei log di due sistemi;
  4. lo carica e chiede il reload della web app, che al riavvio lo assorbe.

Se un passo va storto **non si pubblica niente**: meglio dati di sei ore fa che
un listone nuovo accanto a minuti vecchi.

Variabili d'ambiente (i segreti del repository):

    PA_UTENTE     il tuo nome utente su PythonAnywhere
    PA_TOKEN      il token dalla pagina Account -> API Token
    PA_DOMINIO    utente.pythonanywhere.com
    PA_PERCORSO   dove sta il progetto, es. /home/utente/fanta
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fantabot.dati import calendario, coppie, sincronizza  # noqa: E402
from fantabot.dati.aggiorna import aggiorna_tutto  # noqa: E402
from fantabot.db import connetti  # noqa: E402

LAVORO = Path("lavoro")
LOCALE = LAVORO / "fantabot.sqlite3"
PACCO = LAVORO / "riferimento.sqlite3"


def _api(percorso: str) -> str:
    return f"https://www.pythonanywhere.com/api/v0/user/{os.environ['PA_UTENTE']}{percorso}"


def _intestazioni() -> dict[str, str]:
    return {"Authorization": f"Token {os.environ['PA_TOKEN']}"}


def scarica_precedente(client: httpx.Client) -> bool:
    """Il pacco della volta scorsa, per non ricominciare da capo."""
    percorso = f"{os.environ['PA_PERCORSO']}/dati/riferimento.sqlite3"
    risposta = client.get(_api(f"/files/path{percorso}"), headers=_intestazioni())
    if risposta.status_code != 200:
        print(f"· niente pacco precedente ({risposta.status_code}): riparto da zero")
        return False
    LOCALE.parent.mkdir(parents=True, exist_ok=True)
    LOCALE.write_bytes(risposta.content)
    print(f"· ripreso il pacco precedente, {len(risposta.content) // 1024} KB")
    return True


def carica(client: httpx.Client, file: Path) -> None:
    percorso = f"{os.environ['PA_PERCORSO']}/dati/riferimento.sqlite3"
    risposta = client.post(
        _api(f"/files/path{percorso}"),
        headers=_intestazioni(),
        files={"content": (file.name, file.read_bytes())},
    )
    # 200 = sovrascritto, 201 = creato la prima volta.
    if risposta.status_code not in (200, 201):
        raise SystemExit(f"caricamento fallito: {risposta.status_code} {risposta.text}")
    print(f"· caricato ({risposta.status_code})")


def ricarica(client: httpx.Client) -> None:
    dominio = os.environ["PA_DOMINIO"]
    risposta = client.post(
        _api(f"/webapps/{dominio}/reload/"), headers=_intestazioni()
    )
    if risposta.status_code != 200:
        raise SystemExit(f"reload fallito: {risposta.status_code} {risposta.text}")
    print(f"· {dominio} ricaricata: al riavvio assorbe il pacco")


def main() -> int:
    for chiave in ("PA_UTENTE", "PA_TOKEN", "PA_DOMINIO", "PA_PERCORSO"):
        if not os.environ.get(chiave):
            raise SystemExit(f"manca la variabile {chiave}")

    LAVORO.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0) as client:
        scarica_precedente(client)

        conn = connetti(LOCALE)
        coppie.carica_semi(conn)
        calendario.carica_seme(conn)
        esito = aggiorna_tutto(conn)
        print(
            f"· letto: {esito.get('giocatori', 0)} giocatori, "
            f"{esito.get('statistiche', 0)} righe di statistiche, "
            f"giornata {esito.get('giornate', 0)}, "
            f"{esito.get('fermi', 0)} infortunati, "
            f"{esito.get('squalificati', 0)} squalificati"
        )
        if not esito.get("giocatori"):
            raise SystemExit(
                "il listone e' arrivato vuoto: non pubblico niente. "
                "Meglio i dati di prima che nessun dato."
            )

        pacco = sincronizza.esporta(conn, PACCO)
        conn.close()
        if not pacco.riuscito:
            raise SystemExit(f"esportazione fallita: {pacco.errore}")
        print(
            f"· pacco da {PACCO.stat().st_size // 1024} KB: "
            + ", ".join(f"{t} {n}" for t, n in sorted(pacco.tabelle.items()))
        )

        carica(client, PACCO)
        ricarica(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
