"""Carica il progetto su PythonAnywhere con l'API, senza aprire una console.

Serve per il primo deploy e per gli aggiornamenti: manda i file che git
conosce piu' il `.env`, che git non conosce apposta. Poi ricarica la web app.

    PA_UTENTE=... PA_TOKEN=... PA_PERCORSO=/home/utente/fanta \
        python scripts/deploy.py

Quello che questo script NON puo' fare e' installare le dipendenze: per
`pip install` serve una console, e l'API non ne apre. La prima volta quindi
c'e' un comando da dare a mano, ed e' scritto in fondo all'output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

RADICE = Path(__file__).resolve().parents[1]

# Il `.env` non sta in git e deve stare sul server: e' l'unico file che si
# aggiunge a mano all'elenco.
IN_PIU = (".env",)

# Roba che sul server non serve e occuperebbe spazio: il piano gratuito ne ha
# 512 MB in tutto, e i test non li lancia nessuno da li'.
SALTA = ("tests/", ".github/", "dati/coppie/", "dati/calendario/")


def da_mandare() -> list[Path]:
    tracciati = subprocess.run(
        ["git", "ls-files"],
        cwd=RADICE,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    file = [
        Path(r) for r in tracciati if not any(r.startswith(s) for s in SALTA)
    ]
    # I semi (matrici e calendario) servono eccome: si mandano interi.
    file += [
        p.relative_to(RADICE)
        for p in (RADICE / "dati").rglob("*.csv")
    ]
    file += [Path(n) for n in IN_PIU if (RADICE / n).exists()]
    return sorted(set(file))


def main() -> int:
    for chiave in ("PA_UTENTE", "PA_TOKEN", "PA_PERCORSO"):
        if not os.environ.get(chiave):
            raise SystemExit(f"manca la variabile {chiave}")
    utente = os.environ["PA_UTENTE"]
    base = f"https://www.pythonanywhere.com/api/v0/user/{utente}"
    testa = {"Authorization": f"Token {os.environ['PA_TOKEN']}"}
    remoto = os.environ["PA_PERCORSO"].rstrip("/")

    file = da_mandare()
    print(f"{len(file)} file da mandare in {remoto}")
    with httpx.Client(timeout=120.0) as client:
        for relativo in file:
            locale = RADICE / relativo
            destinazione = f"{remoto}/{relativo.as_posix()}"
            risposta = client.post(
                f"{base}/files/path{destinazione}",
                headers=testa,
                files={"content": (locale.name, locale.read_bytes())},
            )
            if risposta.status_code not in (200, 201):
                raise SystemExit(
                    f"{relativo}: {risposta.status_code} {risposta.text[:200]}"
                )
            print(f"  {'creato' if risposta.status_code == 201 else 'aggiornato'}"
                  f"  {relativo.as_posix()}")

        dominio = os.environ.get("PA_DOMINIO")
        if dominio:
            r = client.post(f"{base}/webapps/{dominio}/reload/", headers=testa)
            print(f"reload {dominio}: {r.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
