# Fantabot

Assistente d'asta per il fantacalcio Classic, su Telegram. Scrivi il nome di
un giocatore mentre il banditore aspetta e ti risponde **fino a quanto
offrire**, tenendo conto di quanto hai speso, di quanto hanno speso gli altri,
e di chi resta sul mercato.

---

## Quello che fa, e quello che non fa

**Non ti fa vincere il fantacalcio.** Nessuno strumento può: tra un infortunio
al 20', un rigore sbagliato e un allenatore che cambia idea il sabato, la
varianza di una stagione è enorme. Chiunque prometta il contrario ti sta
vendendo qualcosa.

Quello che questo bot fa davvero è impedirti di perdere per gli errori che
all'asta si fanno tutti, e che sono tutti evitabili:

- pagare 40 un giocatore che al tuo tavolo ne vale 22;
- arrivare all'ultimo reparto con 30 crediti e sei slot vuoti;
- lasciar passare a due crediti uno che vale venti volte tanto;
- non accorgersi che in sala sono rimasti troppi soldi e che *tutto*, da quel
  momento, costerà il 20% in più.

Quanto vale, misurato: in una simulazione d'asta contro sette avversari che
offrono attorno al prezzo di listino, seguire il bot dà circa **+2,6% di
fantamedia sull'undici titolare**. Su una stagione sono un paio di punti a
giornata: contano, ma non sono una garanzia. E quando tre avversari usano lo
stesso strumento, il vantaggio si assottiglia — la posizione media scende dal
primo posto al 2,4 su 8. Il margine viene dal sapere qualcosa che gli altri
non sanno; se lo sanno tutti, sparisce.

---

## Avvio in cinque minuti

```powershell
cd fantabot
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[sviluppo]"
```

**1. Crea il bot.** Su Telegram scrivi a [@BotFather](https://t.me/BotFather),
manda `/newbot`, scegli un nome. Ti risponde con un token tipo
`123456789:AAF...`.

**2. Scopri il tuo id.** Scrivi a [@userinfobot](https://t.me/userinfobot), ti
dice un numero.

**3. Crea il file `.env`** accanto a questo README (copia `.env.example`):

```
TELEGRAM_BOT_TOKEN=123456789:AAF...
UTENTI_AMMESSI=il_tuo_id
```

`UTENTI_AMMESSI` non è un dettaglio: senza, chiunque conosca il nome del bot
può leggere la tua strategia e registrare acquisti finti durante l'asta.

**4. Scarica il listone e avvia:**

```powershell
.venv\Scripts\python.exe -m fantabot.dati.aggiorna
.venv\Scripts\python.exe -m fantabot.bot.main
```

**5. Su Telegram**, apri il tuo bot e digli le regole. Scrivile come
vengono, in qualunque ordine — le regole di una lega si decidono spesso dieci
minuti prima di cominciare:

```
/setup 500 crediti 8 squadre 3-8-8-6
/setup 10 squadre, 750 crediti, con modificatore
/setup a buste chiuse
/squadre Marco, Luca, Giulia, Dario, Sara, Nico, Ale
```

Cambia solo quello che nomini: a metà configurazione `/setup con modificatore`
non azzera crediti e rose. `/regole` ti rilegge quello che il bot ha capito,
da controllare prima che parta l'asta.

---

## Come si usa durante l'asta

Quattro modi di scrivere, in ordine di fretta:

| Scrivi | Succede |
|---|---|
| `vlahovic` | la scheda, **la cifra che dovrebbe bastare** e il tuo limite |
| `+vlahovic 25` | l'ho preso io a 25 — registrato, ti dice cosa ti resta |
| `vlahovic 25 marco` | l'ha preso Marco: un messaggio, zero tap |
| `vlahovic 25 3` | come sopra, ma per numero: la terza squadra dell'elenco |
| `vlahovic 25` | l'ha preso un altro: un tap per dire chi |

I nomi si possono sbagliare: `donnaruma`, `vla`, `martinez` funzionano tutti.
Se il nome è ambiguo, il bot ti fa scegliere con un bottone. Sotto ogni scheda
ci sono due bottoni per mettere il giocatore fra gli obiettivi o fra quelli da
evitare, senza digitare niente.

Registrare in fretta **anche gli acquisti degli altri** non è pignoleria: se
non lo fai, il bot crede che gli avversari abbiano ancora tutti i crediti e ti
consiglia offerte troppo basse. È per questo che la forma con la squadra nel
messaggio esiste.

**Comandi utili tra un giocatore e l'altro**

| Comando | Cosa dice |
|---|---|
| `/chiama` | chi conviene chiamare adesso, e quanti possono contendertelo |
| `/piano` | il foglio completo di tutti i reparti, come file da stampare |
| `/budget` | quanto spendere per reparto, e se il mercato è caro o a sconto |
| `/occasioni` | chi rende più della cifra che serve per prenderlo |
| `/campo` | chi sta giocando davvero, e chi non ha ancora messo piede in campo |
| `/infortunati` | chi è fermo, per quanto, e chi rientra fra due giornate |
| `/coppie p` | come si abbinano i portieri sul calendario (`/coppie p con napoli`) |
| `/turno` | a chi tocca chiamare; se tocca a te, cosa chiamare |
| `/reparto p` | apri il reparto portieri, per le leghe che chiamano a ruolo |
| `/liberi d` | i migliori difensori ancora liberi |
| `/mercato` | crediti e slot di tutte le squadre, chi resta di valido |
| `/rosa` | la tua rosa (o `/rosa Marco` per quella di un altro) |
| `/riepilogo` | quanto valore hai comprato, e quanto l'hai pagato |
| `/prudenza 1.2` | offerte più caute (o `0.8` per più aggressive) |
| `/regole` | rileggi le regole che il bot ha capito |
| `/importa` | usare i prezzi d'asta veri di FantaLab (o simili) |

**Durante la stagione**

| Comando | Cosa dice |
|---|---|
| `/formazione` | gli undici da schierare e il modulo che rende di più |
| `/scambi` | gli scambi uno-a-uno che convengono anche all'altro |
| `/scambio malen marco` | registra un passaggio di proprietà (non tocca i crediti) |
| `/andamento malen` | bonus, malus e minuti giornata per giornata |

Il bot **si aggiorna da solo ogni sei ore**: infortuni e formazioni probabili
cambiano ogni giorno, e cambiano soprattutto fra il venerdì e la domenica —
cioè quando si schiera. `/aggiorna` resta lì per quando non vuoi aspettare.

**La tua lista.** `/target vlahovic` lo segna come obiettivo e alza le tue
offerte del 15%; `/evita vlahovic` le abbassa. `/lista` te li mostra tutti con
lo stato: chi è ancora libero e a quanto lo prenderesti adesso.

**Quando sbagli** — e all'asta si sbaglia. `/annulla` cancella l'ultima
assegnazione, `/annulla vlahovic` cancella quella lì anche se non è l'ultima,
`/correggi vlahovic 32` cambia solo la cifra senza rifare l'acquisto.

---

## Come ragiona

Il bot tiene separate due cose che di solito vengono confuse.

**Il prezzo** è quanto un giocatore costerà davvero al tuo tavolo. Nasce dal
FVM di fantacalcio.it — il consenso di mercato — compresso verso la
quotazione ufficiale e normalizzato sul budget della *tua* lega, in modo che
la somma dei prezzi di tutti i giocatori che verranno comprati sia esattamente
il budget totale. Se comprassi tutti al prezzo, finiresti con la rosa piena e
zero crediti: è la definizione di prezzo giusto.

**Il valore** è quanto ti rende. Non sono i punti che fa in stagione, ma
quanti ne fa **più del giocatore che schiereresti al suo posto**, moltiplicati
per le domeniche in cui c'è. Un trequartista da 7,3 che gioca 24 partite vale
più di un mediano da 6,2 che le gioca tutte — e la somma dei punti stagionali
diceva il contrario, perché è la formula di un gioco senza panchina.

La differenza tra i due è il margine, ed è l'unica cosa che fa vincere
un'asta: comprare al prezzo di mercato produce la rosa che il listone aveva
già scritto.

Il rendimento atteso di ogni giocatore combina due stagioni di storico
(pesate per presenze, la più recente conta di più) con la relazione tra FVM e
rendimento, stimata ogni volta con una regressione ruolo per ruolo. Chi ha
uno storico solido parla da solo; chi non ce l'ha — uno straniero appena
arrivato, un giovane di ritorno dal prestito — viene descritto dal mercato
invece di valere zero.

**E poi il bot guarda chi sta giocando.** È la cosa che il listone non può
sapere: è una fotografia di agosto, e il mercato, gli infortuni e le scelte
dell'allenatore succedono dopo. Senza, il 6 settembre 2026 il bot consigliava
Milinkovic-Savic come seconda occasione del listone a un credito — e
Milinkovic-Savic aveva **zero minuti**: Meret li aveva giocati tutti e
duecentosettanta.

Quanto uno gioca si misura prendendo **la più severa fra due misure**, perché
sbagliano in direzioni opposte: le presenze contano uguale chi gioca novanta
minuti e chi entra all'85' (Lucca aveva tre partite su tre e quaranta minuti
in totale), i minuti puniscono chi ha saltato una giornata per squalifica pur
essendo il titolare indiscusso. Il minimo delle due non ha il difetto di
nessuna.

Quel numero non sostituisce la stima, la corregge: è una media pesata con
quello che si credeva ad agosto, e **il peso di quello che si vede cresce da
solo con le giornate** — a tre vale metà, a dieci due terzi. Per i portieri
pesa di più, e non è un'opinione: una squadra schiera un portiere e lo tiene
in campo tutti e novanta i minuti, quindi nei suoi minuti non c'è turnover a
fare rumore. Tre giornate a zero per un centrocampista possono essere un
fastidio muscolare; per un portiere vogliono dire che il titolare è un altro.

L'undici previsto della prossima giornata **alza** chi è dato titolare e non
abbassa chi non lo è: serve a vedere il titolare che rientra da un infortunio,
che nei minuti è indistinguibile da una riserva. Il contrario lo dicono già i
minuti, che il turnover lo contengono.

**Chi non gioca, e perché.** I minuti dicono che un giocatore non scende in
campo; non dicono se è una riserva o un infortunato, e le due cose portano a
decisioni opposte. La pagina degli infortunati di fantacalcio.it le separa, e
il testo di ogni scheda viene letto per ricavarne le giornate di stop — «rientro
in campo da fine novembre» sono dodici. La stima è una lettura di una frase,
quindi **la frase si mostra sempre accanto al numero**.

L'infortunio agisce due volte, in due direzioni:

- toglie le giornate che salta, e **solo da quelle che restano**: dieci
  giornate a settembre sono un pezzo di stagione, ad aprile sono tutta quella
  che c'era;
- e *protegge* dal giudizio dei minuti, ma solo verso il basso. Buongiorno ha
  zero minuti ed è il centrale titolare del Napoli: leggere quello zero come
  una gerarchia vorrebbe dire scambiare un infortunio per una bocciatura, e
  scartarlo proprio quando costa meno. Chi invece ha giocato più del previsto
  si tiene i suoi minuti per intero — l'infortunio spiega le partite saltate,
  non quelle giocate.

**Titolarità e continuità, il bot le ricava da solo.** Non servono file: la
titolarità è la presenza attesa riportata su cinque gradini, la continuità è
quante domeniche un giocatore consegna rispetto a uno del suo livello di
mercato — Dybala ne dà 20 e 21 dove il mercato ne prevedeva 34.

Si chiama continuità e non integrità apposta: **le presenze non sanno dire
perché** uno ha giocato poco. Provate le due regole possibili su dati veri,
ognuna sbagliava qualcuno — la media puniva Malen, che ha 18 presenze perché è
arrivato a gennaio; il massimo assolveva Bremer, che una stagione l'ha passata
col crociato rotto. Non c'è una terza formula: la causa non è nel dato. Quello
che si misura senza ambiguità è quante partite ti consegna, ed è anche quello
che serve per decidere. Con una sola stagione conclusa il bot non si pronuncia.

**I tre giudizi di FantaLab, se glieli dai.** L'export porta per ogni giocatore
*titolarità*, *integrità* e *affidabilità* da 1 a 5. La titolarità è
esattamente la quantità che il motore fatica di più a stimare — quante partite
giocherà — detta da chi il campionato lo guarda e sa già del mercato estivo:
pesa metà del prior, e quello che succede in campo la supera comunque. L'integrità
è la propensione a farsi male, che nei minuti non si vede finché non è successa,
e vale uno sconto fino al 20%. L'affidabilità **non entra in nessun conto**:
parla di varianza e il motore stima medie, quindi si mostra e basta. Delle
sedici etichette a parole (`titolarissimo`, `cartellini`, `scommessa`…) ne
entra nei conti **una sola: `rigorista`**, +0,35 di fantamedia. Le altre
quindici o sono già nei numeri o parlano di varianza; chi tira i rigori
quest'anno invece non sta in nessuna statistica dell'anno scorso, perché
spesso è cambiato. Dybala e
Zaniolo hanno entrambi titolarità 5 e integrità 1, ed è una frase che il numero
da solo non racconta.

E la **stagione in corso** entra sui voti — non sulle presenze, che le sa già
il campo, e farlo dire due volte alla stessa evidenza vorrebbe dire che tre
giornate parlano con due voci. È lì che si legge perché Malen costa
duecentoquarantacinque crediti: cinque gol in tre partite, fantamedia 12,33.
Pesata per presenze, tre contro trentaquattro, sposta la stima di un decimo —
e cresce da sola giornata dopo giornata.

**E chi ha cambiato maglia viene riportato al contesto di adesso.** Sono
sessantaquattro giocatori: il loro storico è stato costruito da un'altra
parte, e un portiere che arriva dal fondo classifica in una squadra da primi
posti prenderà voti diversi da quelli che ha in archivio. Quanto pesa il club
non è deciso a tavolino ma stimato dai dati, togliendo prima l'effetto del
FVM da entrambe le variabili — altrimenti al club verrebbe attribuito merito
che è del giocatore. Il risultato è la gerarchia che il fantacalcio conosce,
ricavata senza suggerirla: **portieri +0,80** per unità di forza del club
(dipendono quasi solo dalla difesa davanti a loro), **attaccanti +0,57**,
difensori e centrocampisti circa +0,26.

### Se hai FantaLab (o un tool simile)

C'è un dato che questo bot può soltanto stimare e che un tool con migliaia di
aste alle spalle invece **sa**: a quanto quel giocatore viene pagato davvero.
Se ce l'hai, daglielo — la stima si fa da parte.

L'API di FantaLab è tutta dietro login (ogni endpoint risponde `403`), quindi
la strada non è scavalcarla ma l'export che loro stessi offrono: da
**Strategia → Esporta in Excel**, poi allega il file in chat.

Il formato vero è stato tarato su un export reale: quattro fogli (`P`, `D`,
`C`, `A`), colonna dei prezzi chiamata solo `Prezzo`, fasce scritte a parole
(`Top`, `Semi-Top`, `Outsider`…). Il bot legge tutti i fogli, riconosce le
colonne dai nomi invece che dalla posizione — `Prezzo`, `Prezzo medio`,
`Costo medio`, `Media asta` vanno tutte bene, in qualunque ordine — traduce le
fasce in numeri, e abbina i giocatori al listone perdonando le differenze di
scrittura: *Lautaro Martinez* trova *Martinez L.*. Su un export reale da 532
righe ne ha riconosciute 530.

Due colonne diverse, tenute separate: **`PMA` è quanto il giocatore viene
pagato davvero** (una quota del budget — la somma su tutto il listone fa circa
100% per squadra, ed è la verifica che dice se la colonna è quella giusta),
mentre `Prezzo` è quanto il tool consiglia di spendere. Il motore usa la
prima: è un'osservazione, non un'opinione.

Poi **dichiara cosa ha capito**: quali colonne ha usato, quanti nomi ha
riconosciuto e quali no. Un import che sbaglia in silenzio la sera dell'asta è
peggio di un import che non parte.

#### Il foglio decide anche chi non esiste più

Il listone di fantacalcio.it è una fotografia che non si aggiorna quando uno
cambia campionato: a mercato chiuso **Leao risultava ancora al Milan** con il
suo FVM da 75, e il bot lo consigliava come partner d'attacco. Il file delle
fasce è compilato da chi il mercato l'ha seguito, quindi la sua assenza vale
come smentita: **si nomina solo chi sta in tutte e due le liste.**

Il danno non era il nome sbagliato in un consiglio. Un giocatore che non esiste
entra fra i comprabili, si prende la sua fetta del budget della lega e **rende
tutti gli altri più economici di quanto siano** — sull'export reale sono
sessantatré nomi su cinquecentonovantaquattro, e uno di loro era il quinto FVM
del campionato. Adesso restano fuori dai prezzi, dai consigli, dagli
abbinamenti e dal turno di chiamata.

Restano invece **cercabili**: se il banditore lo chiama, scrivere `leao` apre
la scheda con scritto sopra `FUORI LISTA` e il motivo. E chi è già stato
comprato non sparisce mai — cancellarlo a metà asta cancellerebbe i crediti
spesi, e la rosa non tornerebbe più.

Due protezioni, perché una regola che cancella giocatori la sera dell'asta è
pericolosa quanto il problema che risolve:

- **sotto metà listone coperto non si filtra niente.** Trenta nomi su seicento
  sono un import rotto, non una lista più corta;
- **`/fuorilista` mostra chi è stato tolto**, con i minuti giocati accanto. È
  quella colonna il controllo: chi è andato via ha zero minuti, e vedere
  `Norton-Cuffy 180'` vuol dire che nel foglio quel nome è scritto in un altro
  modo, non che ha cambiato campionato.

Da lì in avanti i prezzi osservati sostituiscono la stima per chi ce li ha, e
al bot resta il mestiere che il foglio non fa: dire **quanto vale per te**,
**chi te lo può contendere** e **quanto ti resta in tasca**. `/importa` ti
dice cosa c'è già dentro.

**E il bot impara il carattere del tuo tavolo mentre gioca.** Ogni lega ha
il suo: da qualche parte i campioni si pagano molto sopra il listino e la
fascia media si svende, altrove i crediti si spalmano. È un fatto che nessun
listone può sapere in anticipo — ma dopo una decina di chiamate l'asta lo ha
già scritto da sola, confrontando quello che è stato pagato con quello che era
previsto. Da lì in poi i prezzi si piegano di conseguenza: in un tavolo caro
il bot ti dirà cifre più alte sui big e, più spesso, di lasciar perdere,
perché in quel tipo di asta il valore si raccoglie nella fascia media.
`/mercato` te lo dice in una riga.

**Durante l'asta tutto si ricalcola.** Dopo ogni assegnazione i crediti
rimasti in sala si ridistribuiscono sui giocatori ancora liberi: se i big sono
andati via a poco, in sala restano soldi che *devono* essere spesi e tutto il
resto rincara; se sono andati a cifre folli, i prezzi crollano. `/budget` te
lo dice in una riga.

Il massimo che ti consiglia parte dal prezzo corrente e lo muove con quattro
spinte — quanto il giocatore vale più di quanto costa, quanti crediti hai per
slot rispetto agli altri (e conta pochissimo all'inizio, quando avere più
soldi degli altri vuol dire solo che non hai ancora comprato, e moltissimo
alla fine, quando i crediti che avanzano valgono zero), quanti giocatori
validi restano nel suo ruolo, e quanto lo vuoi tu se l'hai messo fra gli
obiettivi — e poi lo taglia con due
tetti che non si superano mai: tenere un credito per ogni slot vuoto, e tenere
abbastanza da non finire l'asta con un reparto fatto di scarti.

**Le regole che il bot sa seguire.** Crediti, numero di squadre e
composizione della rosa sono liberi. Poi ci sono le due varianti che cambiano
davvero i consigli, e che spesso si decidono la sera stessa:

- **il modificatore di difesa**, che sposta cosa vale un difensore;
- **l'asta a buste chiuse**, che cambia quale numero devi guardare — senza
  rilancio non esiste "il secondo più uno", quindi il bot ti dà il tuo
  massimo invece della cifra che sarebbe bastata.

**Il modificatore di difesa, se la tua lega lo usa, cambia il reparto.** Con
`/setup con modificatore` il motore smette di guardare solo la fantamedia dei
difensori e comincia a pesare la loro **media voto**, che è ciò su cui il
modificatore si calcola. L'effetto è quello giusto: la difesa passa dal 29% al
35% del budget, e soprattutto si separano due tipi di difensore che senza
questa regola valgono uguale — quello che prende 6,5 tutte le domeniche sale,
quello che prende 5,9 e ogni tanto segna scende.

**Ma il numero che leggi per primo non è quel massimo: è la cifra che dovrebbe
bastare.** Sono due cose diverse e confonderle costa crediti a ogni giocatore
che prendi. In un'asta a rilancio si paga il secondo miglior offerente più
uno, quindi il bot guarda chi può ancora contenderti quel giocatore — chi ha
ancora uno slot libero in quel ruolo *e* i crediti per arrivarci — e da lì
ricava la cifra realistica. Se metà lega ha già chiuso l'attacco, il centravanti
che il listino dà a 60 lo prendi a 12, e il bot te lo dice invece di lasciarti
offrire 60. Se non ti può contendere nessuno, parti dalla base e basta.

---

### Gli abbinamenti di calendario

Portieri e attaccanti hanno un problema che difensori e centrocampisti non
hanno: ne schieri pochi, e quindi il calendario conta quanto il giocatore. Due
portieri che affrontano le grandi nella stessa giornata sono un portiere e
mezzo.

Il bot importa la matrice venti-per-venti di FantaLab e la traduce in coppie di
giocatori veri, con i prezzi:

```
voto  coppia                     costo
  94  Falcone + Meret               33
  91  Carnesecchi + Muric           38
  90  Palmisani + Mascardi           3
```

Due dettagli che sembrano piccoli e non lo sono. La matrice deve essere
**simmetrica** — Lecce-Napoli e Napoli-Lecce sono lo stesso abbinamento — e una
che si contraddice **non entra nemmeno a metà**: importarne la parte buona
nasconderebbe l'errore. E ogni squadra è rappresentata **da chi gioca, non da
chi vale**: nel ruolo del portiere le valutazioni si schiacciano tutte, e
ordinando per valore il Genoa usciva rappresentato da Sommariva, zero minuti,
invece che da Bijlow che li ha giocati tutti.

**In attacco le fasce si incrociano.** Un Top si abbina a un Semi-Top e una
Terza a una Quarta: due Top costano mezzo budget e due Quarte non fanno una
domenica. Il vincolo viene prima del punteggio — un abbinamento da 99 fra un
Top e una Terza non viene proposto, perché non è quello il reparto che stai
componendo. La fascia è quella del tuo file di strategia (`Top`, `Semi-Top`…),
non quella che il bot calcola da solo: quando una regola è detta a parole va
rispettata con le parole di chi l'ha detta.

**E parte da quello che hai già comprato**, non dalla sua squadra: la Roma ha
Malen e Dybala, che sono due fasce e due domande diverse. Subito dopo ogni tuo
acquisto il bot aggiunge da solo i tre nomi con cui completare il reparto, con
**il prezzo del solo che manca** — il momento in cui hai appena preso un
portiere è l'unico in cui la domanda "e adesso il secondo?" ha ancora tutte le
risposte disponibili.

```
hai Meret: chi ci metti accanto
voto  chi manca            costa
  94  Falcone                4
  90  Mascardi               1
```

Il voto è di stagione, non di domenica: dice quali due squadre stanno bene
insieme, non quale dei due schierare la prossima giornata.

### Il calendario, e la domenica giusta

Le matrici di abbinamento dicono che Lecce e Napoli si alternano bene su
trentotto turni. Non dicono **quale dei due schierare adesso** — e quella è la
domanda che si fa ogni settimana, mentre l'altra si fa una volta sola all'asta.
Il calendario è il pezzo che le collega.

Le 380 partite stanno in `dati/calendario/serie-a-2026-27.csv`, copiate a mano
dal PDF ufficiale. Una trascrizione così non si rilegge: si verifica. Tre
condizioni, e insieme non lasciano passare quasi niente —

- ogni giornata ha venti squadre, **una volta sola** ciascuna;
- ognuna delle 380 coppie ordinate `(casa, ospite)` esiste **esattamente una
  volta** in tutta la stagione;
- le date non tornano mai indietro.

Ne hanno trovati due al primo colpo: un `INTER vs MILAN` alla tredicesima e un
`INTER vs COMO` alla trentasettesima, tutti e due già presenti altrove. E
avendo detto *quale* coppia mancava, hanno detto anche come correggerli —
`INTER vs GENOA` e `INTER vs LAZIO`. Un calendario che non supera i tre
controlli **non viene importato affatto**: un buco fa dire al bot che una
squadra riposa quando invece gioca, e chi ha il dato sbagliato non lo sa.

**Cosa cambia nei consigli.** `/formazione` non ordina più solo per fantamedia
e minuti: somma l'avversario. Fra la partita più facile del campionato e la più
difficile ci sono tre decimi di fantamedia per lato — abbastanza da scegliere
fra due portieri equivalenti, non abbastanza da mettere una riserva davanti a
un titolare, che è esattamente il confine che quel numero deve tenere. La
colonna `contro` usa la convenzione dei giornali: **`CAG`** in casa,
**`cag`** in trasferta.

```
3-4-3 — 4ª giornata
   nome          contro  attesi
P  Carnesecchi   CAG       5.8  previsto titolare
A  Malen         tor       9.6  previsto titolare
...
P  Meret         BOL       5.5  previsto titolare   ← in panchina
```

`/giornata` mostra il calendario con dentro i tuoi, e segnala **i tuoi contro i
tuoi**: un tuo difensore e un tuo attaccante nella stessa partita si tolgono i
punti a vicenda, ed è una cosa che si vede solo guardando il calendario.

**Se la tua lega non parte dalla prima**, diglielo: `/setup dalla 4a giornata`.
Il numero viene tolto dalla frase *prima* di cercare crediti e squadre —
altrimenti «8 squadre dalla 4a giornata» diventava una lega da quattro squadre,
con metà dei crediti in sala e tutti i prezzi sbagliati.

### Squalificati e diffidati

Due cose diverse che portano a decisioni opposte, e per questo restano
separate: uno **squalificato** domenica non gioca — è già deciso dal giudice
sportivo, e vale zero qualunque cosa dica la fantamedia; un **diffidato** gioca
eccome, ma un altro giallo e salta quella dopo. Il primo cambia la formazione
di adesso, il secondo è l'unica cosa che ti avvisa di una formazione che non
hai ancora fatto.

Le squalifiche **non toccano il valore d'asta**: una giornata su trentotto è
rumore, e scontarla vorrebbe dire pagare meno un giocatore per una cosa che
sarà finita prima che tu lo schieri.

### Il turno di chiamata

Il bot tiene il conto di **chi tocca**, e soprattutto di chi va saltato: una
squadra che ha completato quel reparto — o che è rimasta senza crediti — passa
la mano, e il turno avanza da solo dopo ogni assegnazione, perché all'asta un
contatore da aggiornare a mano è un contatore sbagliato.

`/reparto p` apre il reparto portieri per le leghe che chiamano a ruolo;
`/reparto libero` toglie il vincolo. `/turno` dice chi chiama, chi è stato
saltato e perché, e — se tocca a te — cosa chiamare.

La riga che vale più di tutte è questa: **«sei l'unico che cerca ancora i
difensori»**. Da quel momento in quel reparto nessuno può rilanciare, ogni
chiamata si chiude al prezzo di base, e conviene prendere i migliori rimasti
invece dei più economici. È una situazione che vale decine di crediti e passa
inosservata, perché succede mentre si sta guardando un altro giocatore.

---

## Da dove vengono i dati

Dalle pagine pubbliche di fantacalcio.it: il listone
(`/quotazioni-fantacalcio`) e il riepilogo statistico delle due stagioni
precedenti **e di quella in corso**. L'export Excel ufficiale richiede un
account e risponde 401, per cui non lo usiamo; le pagine pubbliche contengono
già tutto.

E da due fonti che guardano il campo, perché il listone è una fotografia di
agosto e non sa chi gioca a settembre:

| Fonte | Cosa dà | Perché serve |
|---|---|---|
| **fotmob** | minuti e presenze di ogni giocatore, per squadra | chi è titolare *davvero* — le presenze da sole contano uguale chi gioca 90' e chi entra all'85' |
| **sportsgambler** | l'undici previsto della prossima giornata | l'unico modo di vedere un titolare che rientra da un infortunio: nei minuti è identico a una riserva |
| **fantacalcio.it/infortunati** | chi è fermo, per cosa, e fino a quando | separa la riserva dall'infortunato: i minuti dicono che non gioca, non perché |

Nessuna delle due ha una chiave o un login. Le usa anche il progetto
`pronostici`, da cui vengono gli indirizzi; qui il codice è riscritto su httpx
perché i due progetti non condividono l'ambiente.

`/aggiorna` riscarica tutto, listone e campo insieme. Ogni pagina viene anche
salvata in `dati/cache/`: se la sera dell'asta il sito è lento o
irraggiungibile, il bot lavora sull'ultima copia invece di non rispondere.

L'aggancio fra i nomi del listone (`Marin R.`, `Zambo Anguissa`,
`Esposito F.P.`) e quelli delle altre fonti (`Rafa Marín`, `Frank Anguissa`,
`Francesco Pio Esposito`) passa **sempre dalla squadra**: dentro una rosa i
candidati sono venti, e un aggancio ambiguo si scarta invece di indovinarlo —
attribuire i minuti di uno al compagno produce un numero plausibile sulla
persona sbagliata. Misurato il 6 settembre 2026: 376 giocatori su 385
agganciati, zero ambigui, e i nove rimasti fuori non sono nel listone.

Il collegamento tra listone e statistiche usa l'id numerico della scheda
giocatore, mai il nome: due giocatori possono chiamarsi "Pereira".

---

## Manutenzione

Le stagioni sono in `src/fantabot/config.py`
(`STAGIONE_CORRENTE`, `STAGIONE_PRECEDENTE`): si aggiornano una volta l'anno,
lì e in nessun altro posto. La stagione di fotmob invece non si scrive mai a
mano — il suo identificativo cambia ogni anno e si rilegge dall'indice a ogni
chiamata, perché cablarlo vorrebbe dire leggere i minuti dell'anno scorso
senza che niente diventi rosso.

Se fantacalcio.it cambia il markup, l'aggiornamento si ferma con un errore
esplicito («il listone ha solo N righe») invece di svuotare il database. I
test del parser girano su una fixture e non sulla rete, così quando qualcosa
si rompe sai subito se è colpa del sito o tua.

```powershell
.venv\Scripts\python.exe -m pytest      # 193 test
```

---

## Metterlo online (o non metterlo)

Il bot **fa polling**: un processo che resta acceso e chiede a Telegram se c'è
posta, più un lavoro ogni sei ore che rilegge le fonti. Da questo discende
tutto il resto, e la forma sbagliata di hosting non è più lenta — è impossibile.

**La sera dell'asta: il portatile.** `python -m fantabot.bot.main`, e basta. Non
è un ripiego: è il modo per cui il database è SQLite invece di Postgres. Zero
costo, internet pieno, e nessun deploy da fare nell'ora in cui serve.

**Per la stagione, gratis: GitHub Actions legge, PythonAnywhere risponde.**
È la strada che il progetto implementa, ed è gratuita perché gira i vincoli
invece di pagarli.

```
GitHub Actions            PythonAnywhere (free)         Telegram
──────────────            ─────────────────────         ────────
ogni 6 ore
  legge le fonti  ──────► carica riferimento.sqlite3
  (internet pieno)        reload della web app
                            │
                            └─ all'avvio: assorbe    ◄──►  webhook
                               solo le tabelle
                               rileggibili
```

Tre fatti la reggono, e vanno letti insieme:

- **la whitelist blocca le uscite, non le entrate.** Telegram arriva senza
  problemi, e la sola uscita che serve — `api.telegram.org`, per rispondere —
  è l'unica che la whitelist permette;
- **le web app non consumano CPU-seconds**, mentre consoles e task sì. Il bot
  vive nella sola parte del piano gratuito che non ha un contatore;
- **le fonti le legge Actions**, che esce ovunque e su un repository pubblico
  non costa niente.

Il prezzo è che non si può fare polling: senza always-on task, il bot dev'essere
*chiamato*. Quindi `wsgi.py` + `src/fantabot/bot/web.py` servono i webhook,
autenticati con `X-Telegram-Bot-Api-Secret-Token` — l'indirizzo non è una
password, e chi lo indovina trova un 403.

#### La trappola, che è il motivo per cui non basta un `scp`

Il database contiene due cose nello stesso file: quello che si **rilegge** dal
mondo (listone, statistiche, minuti, infortuni, squalifiche, calendario,
abbinamenti) e quello che **esiste solo lì** — la tua lega, le rose, i prezzi
pagati, i tuoi obiettivi, e il foglio delle fasce che hai caricato da Telegram.

Sovrascrivere il file intero avrebbe funzionato benissimo per undici giorni e
poi, il dodicesimo, avrebbe **cancellato l'asta a metà asta**. Quindi
`dati/sincronizza.py` sostituisce solo le tabelle rileggibili, in una
transazione sola, e le altre non le apre nemmeno. Ogni tabella dello schema
deve stare in esattamente uno dei due elenchi, e **un test lo verifica**: una
migrazione futura che ne aggiunge una senza classificarla fa fallire la suite,
invece di far sparire dei dati sei mesi dopo.

Due dettagli che nascono dalla stessa logica: una tabella che arriva **vuota**
non sostituisce quella di prima (è una lettura andata male dall'altra parte,
non un aggiornamento), e `andamento` — la storia giornata per giornata — non
viaggia affatto: si ricostruisce sul posto appena arrivano statistiche nuove,
perché Actions riparte ogni volta da capo e la sua storia sarebbe lunga una
riga sola.

#### Il passaggio, se la web app la usava già un altro

Non si spegne il vecchio per accendere il nuovo: si mette un file WSGI che
prova prima il nuovo e, se non parte, lascia il posto al vecchio
(`deploy/wsgi_pythonanywhere.py`). Finché le librerie nuove non ci sono,
l'import fallisce e risponde ancora il progetto di prima; appena ci sono, al
primo reload il passaggio avviene da solo. **In mezzo non c'è nessun istante in
cui l'indirizzo è morto**, e il log della web app dice sempre quale dei due è
partito — una scelta automatica che non dichiara la strada presa è il modo più
rapido di perdere un'ora a chiedersi perché il bot non risponde.

#### Cosa serve configurare

Segreti del repository (`gh secret set`), tutti già impostabili senza toccare
il codice:

| Segreto | Cos'è |
|---|---|
| `PA_TOKEN` | PythonAnywhere → Account → API Token |
| `PA_UTENTE` | il tuo username lì |
| `PA_DOMINIO` | `utente.pythonanywhere.com` |
| `PA_PERCORSO` | dove sta il progetto, es. `/home/utente/fanta` |

Sul lato PythonAnywhere: `git clone`, un `.env` con token, `UTENTI_AMMESSI` e
`TELEGRAM_WEBHOOK_SECRET`, il file WSGI che importa `wsgi.py`, e una volta sola

```python
from fantabot.bot.web import registra_webhook
registra_webhook("https://utente.pythonanywhere.com/telegram/")
```

**Tre cose da sapere del piano gratuito.** La web app va **rinnovata a mano ogni
tre mesi** da un bottone sulla dashboard, altrimenti si spegne. Ne hai **una
sola**: se ci gira già un altro progetto, `affianca()` in `wsgi_fanta.py` monta
il fantabot sotto un prefisso e lascia tutto il resto all'app che c'era — che
non va toccata, né un import né una rotta.

E la terza, che è quella che morde: **i pacchetti sono condivisi**. Due
progetti sulla stessa web app girano nello stesso interprete e leggono lo
stesso `~/.local/lib/pythonX.Y/site-packages`, quindi non possono usare due
versioni maggiori diverse della stessa libreria. Questo bot vuole
`python-telegram-bot` 21.x; un progetto che ne usa la 13 fa `from telegram
import ParseMode`, che nella 21 non esiste più, e l'aggiornamento lo spegne
all'import. Prima di affiancare due bot, **guarda cosa importano tutti e due**:
se uno dei due parla con Telegram via HTTP grezzo (`requests`, `httpx`) non c'è
nessun conflitto, se usa PTB a una versione diversa non c'è nessuna
convivenza.

**A pagamento è più semplice, se un giorno vuoi:** PythonAnywhere Developer
($10/mese — il vecchio Hacker da $5 non esiste più) dà una always-on task e
internet senza restrizioni, e allora `python -m fantabot.bot.main` in polling
basta e avanza, senza Actions e senza webhook.

**Vercel non è la forma giusta**, e lo dicono i suoi stessi limiti: le funzioni
durano al massimo 300 secondi (niente processo che resta acceso), il
filesystem non è scrivibile (niente SQLite), e i cron del piano Hobby girano
**una volta al giorno** invece che ogni sei ore. Ci si può arrivare — webhook al
posto del polling, Postgres al posto di SQLite — ma è riscrivere persistenza,
avvio e schedulazione per ottenere qualcosa di peggio.

## Limiti noti

- **Solo Classic.** I ruoli Mantra vengono letti e salvati, ma il motore
  ragiona sui quattro ruoli classici.
- **Sul mercato estivo il bot crede al tuo foglio, non al listone.** Chi manca
  nelle fasce non viene più nominato (`/fuorilista` dice chi), ma il contrario
  non lo sa vedere: uno *aggiunto* a una rosa di Serie A e non ancora presente
  nel listone non esiste per il bot finché non esce nell'export nuovo.
- **Le squalifiche non le vede.** Gli infortuni sì, con la data di rientro
  quando la fonte la scrive; una giornata di squalifica arriva identica a un
  turno di riposo.
- **La forza dei club è quella di adesso, anche per le stagioni passate.**
  Il listone dice com'è composta ogni rosa oggi, non com'era l'anno scorso: la
  correzione per il cambio maglia usa quindi un'approssimazione, e per chi
  arriva da una squadra retrocessa assume la peggiore della Serie A. La
  correzione non supera mai mezzo voto di fantamedia, qualunque sia il salto.
- **Le presenze attese restano la stima più fragile**, anche adesso che il
  bot guarda i minuti giocati. A settembre le giornate sono tre: contano per
  metà (per un portiere per tre quarti, perché lì non c'è turnover a fare
  rumore) e il resto viene ancora da storico e FVM. Il peso di quello che si
  vede cresce da solo giornata dopo giornata, senza che nessuno cambi una
  riga. Quando una stima poggia su troppe poche partite la scheda lo dichiara,
  invece di far finta di saperlo.
- **Le formazioni previste sono previsioni.** Arrivano fino a due settimane
  prima e cambiano: il bot le usa per *alzare* chi è dato titolare, mai per
  abbassare chi non lo è — quella parte la dicono già i minuti, che il
  turnover lo contengono.
- **Il bot sa solo quello che gli dici.** Se non registri gli acquisti degli
  avversari crede che abbiano ancora tutti i crediti, e ti consiglia offerte
  più basse del dovuto: è l'errore d'uso che fa più danni, ed è il motivo per
  cui registrare costa un messaggio solo.
- **Chi ti contende un giocatore è dedotto, non saputo.** Il bot sa chi *può*
  permetterselo, non chi lo vuole: se un avversario ha una fissazione per un
  giocatore, la cifra "dovrebbe bastare" sarà bassa e il tuo limite resta lì
  apposta.
- **Gli abbinamenti restano di stagione**, anche ora che il calendario c'è: la
  matrice dice quali due squadre si alternano bene su trentotto turni, e serve
  a decidere *chi comprare*. Chi schierare domenica lo dice `/formazione`, che
  guarda l'avversario vero.
- **Le squalifiche non sono mai state lette con qualcuno dentro.** La pagina è
  quella giusta e ha la struttura giusta — venti schede lette, zero
  squalificati — ma dopo tre giornate non poteva essercene nessuno: quattro
  gialli in tre partite non li prende nessuno. La prima lettura piena sarà
  anche la prima prova sul campo.

---

## Struttura

```
fantabot/
├── src/fantabot/
│   ├── config.py            percorsi, stagioni, token
│   ├── db.py                schema SQLite e migrazioni numerate
│   ├── servizio.py          il ponte fra database e motore
│   ├── dati/
│   │   ├── fantacalcio.py   lettura delle pagine pubbliche
│   │   ├── aggiorna.py      scrittura nel database
│   │   ├── esterno.py       import di listini da FantaLab e simili
│   │   └── magazzino.py     lettura verso il motore, ricerca per nome
│   ├── motore/
│   │   ├── valutazione.py   prezzo e valore di ogni giocatore
│   │   └── asta.py          il mercato che cambia, il massimo da offrire
│   └── bot/
│       ├── main.py          comandi e bottoni Telegram
│       └── formato.py       i numeri che diventano messaggi
└── tests/                   117 test, nessuno tocca la rete
```
