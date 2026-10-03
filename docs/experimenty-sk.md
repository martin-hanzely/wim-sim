# Ako sa experimenty púšťali a vyhodnocovali

Doplnok k [`simulacia-sk.md`](simulacia-sk.md), ktorý popisuje samotný model. Tento dokument je o
vrstve nad ním: ako sa z jedného behu stane sweep, ako sa sweep rozdelí na stroje, ako sa výsledky
spoja a ako sa z nich stane číslo, ktoré smie ísť do článku.

---

## 1. Čo je „beh“ a čo je „sweep“

**Beh** je jedna bunka mriežky: jeden scenár × jeden estimátor × jeden seed × jedna referenčná
frekvencia × jedno rameno regulátora. Vyprodukuje **jeden riadok** s 48 stĺpcami.

**Sweep** je deklaratívna mriežka v `configs/experiments/*.yaml`. Beží cez
`wimsim experiment <meno>` a zapíše `results.parquet`, `results.md`, `results.tex`,
`manifest.json` a adresár `figures/`.

```mermaid
flowchart TB
    Y["configs/experiments/sweep.yaml<br/>scenáre × estimátory × seedy<br/>× referenčné frekvencie × ramená"] --> SPEC

    SPEC["ExperimentSpec.grid()<br/>kartézsky súčin -> zoznam RunSpec"] --> LOOP

    subgraph LOOP["pre každú bunku"]
        CFG["load_run_config<br/>stanica + scenár + overrides"] --> WR["write_run<br/>vygeneruj do dočasného adresára"]
        WR --> CL["run_closed_loop<br/>hranová reťaz + regulátor"]
        CL --> SC["score_row<br/>pripoj pravdu"]
    end

    LOOP --> ROWS["riadky, vrátane tých zlyhaných"]
    ROWS --> PQ["results.parquet"]
    ROWS --> FIG["figures/*.png<br/>300 dpi"]
    ROWS --> MAN["manifest.json<br/>commit, hashe, čas"]

    style ROWS fill:#fff3cd,stroke:#b8860b
```

**Bunka, ktorá zlyhá, sa stane riadkom, ktorý to hovorí** — nezhodí sweep a ani ticho nezmizne.
Zahodiť ju by zmenilo, nad čím je každý priemer v tabuľke priemerom.

---

## 2. Rozdelenie na shardy a spätné spojenie

Sweep s 2 520 behmi trvá na tomto stroji desiatky hodín ako jeden proces. Jediná os, ktorá sa delí
**presne**, je os seedov: ten istý seed dá bajt po bajte rovnaký prúd vzoriek bez ohľadu na to, kde
beží, takže shardy sa zreťazia do presne toho, čo by vyprodukoval jeden proces.

```mermaid
flowchart LR
    S["sweep, 1260 behov"] --> SH1["shard 1<br/>seedy 1,2,3"]
    S --> SH2["shard 2<br/>seedy 4,5,6"]
    S --> SH3["shard 3<br/>seedy 7,8,9"]
    S --> SH4["shard 4<br/>seedy 10,11,12"]
    S --> SH5["shard 5<br/>seedy 13,14,15"]

    SH1 --> M
    SH2 --> M
    SH3 --> M
    SH4 --> M
    SH5 --> M

    M{"merge_shards<br/>ODMIETNE, ak:"}
    M --> C1["iné experiment_id"]
    M --> C2["iný git commit"]
    M --> C3["iný spec<br/>okrem osi seedov"]
    M --> C4["prekrývajúce sa seedy"]
    M --> OK["results.parquet<br/>+ manifest s merged_from"]

    style M fill:#ffe6e6,stroke:#c00
    style OK fill:#e6ffe6,stroke:#0a0
```

Kontrola prekrytia seedov je dôležitejšia, než vyzerá: **determinizmus robí duplikovaný beh
identickým**, a práve to spôsobuje, že by dvojité započítanie bolo neviditeľné. Žiadny medián by
nevyzeral podozrivo; iba by bol vážený smerom k zdvojenému seedu.

Výnimka pri kontrole špecifikácie je os seedov — `--seeds 1,2,3` a `--seeds 4,5,6` zapíšu odlišné
`spec.seeds`, a kontrola, ktorá by to nevyňala, by odmietla každý skutočný shard. Presne tak táto
kontrola aj zlyhala, keď prvýkrát stretla tri shardy, pre ktoré bola napísaná.

---

## 3. Od riadkov k tvrdeniu

```mermaid
flowchart TB
    PQ["results.parquet"] --> CMP["wimsim compare<br/>Wilcoxonov párový test<br/>+ Holmova korekcia"]
    PQ --> RC["wimsim reference-curve<br/>A1 a A2 tabuľky<br/>len pre sweep, ktorý menil frekvenciu"]
    PQ --> DT["wimsim detector-table<br/>len pre sweep, ktorý menil detektory"]
    PQ --> FG["write_figures<br/>obrázok sa NEnakreslí,<br/>ak preň niet dát"]

    CMP --> EXP
    RC --> EXP
    DT --> EXP
    FG --> EXP
    PQ --> EXP

    EXP["scripts/build_export.py"] --> OUT

    subgraph OUT["export/"]
        D1["data/*_long.csv<br/>jedno pozorovanie na riadok, na seed"]
        D2["data/manifest.json<br/>commit, hashe, verzie, dpi"]
        D3["figures/*.png + FIGURES.md"]
        D4["RESULTS.md, CONTRADICTIONS.md,<br/>OPEN.md, README.md"]
    end
```

### 3.1 Prečo párový test a nie t-test

Behy sú **párované podľa seedu**. Ten istý seed dá bajt po bajte identický prúd vzoriek, takže
rameno so zapnutým a vypnutým regulátorom sa líši presne v jednej veci. To je presne nastavenie,
pre ktoré je znamienkovo-poradový test stavaný.

Wilcoxon a nie t-test, lebo nič tu nie je známe ako normálne a viaceré rozdelenia viditeľne nie sú.
Holm a nie Bonferroni, lebo Holm je rovnomerne silnejší pri rovnakej rodinnej chybovosti.

**Rodinu deklaruje volajúci, explicitne.** Korigovať cez „všetky testy, ktoré som spustil“ a cez
„sedem scenárov v tejto tabuľke“ sú rôzne tvrdenia, a ktoré z nich sa robí, musí byť rozhodnutie,
nie náhoda.

### 3.2 Čo počet seedov vôbec dovoľuje

Najmenšie dosiahnuteľné obojstranné *p* je `2 / 2ⁿ`:

| seedy | podlaha *p* | čo z toho plynie |
|---:|---:|---|
| 3 | 0,25 | **nič nemôže dosiahnuť 0,05**, nech je efekt akokoľvek veľký. Tieto sweepy sú popisné a sú tak aj označené |
| 10 | 0,00195 | prejde cez korekciu v malej rodine |
| 15 | 6,1·10⁻⁵ | prejde cez 42-testovú rodinu |
| 30 | < 10⁻⁸ | pohodlne |

Toto nie je formalita. V tomto projekte sa už stalo, že trojseedový výsledok bol skreslený **a v
jednej bunke mal opačné znamienko**: `cintron_ladder` pri troch seedoch hlásil −13,66 kg tam, kde
tridsať seedov hlási +9,60 kg a signifikantne horšie. A pri poslednom sweepe trojseedová detekčná
recall 0,000 pri jednej referencii na dvadsať vyšla pri pätnástich seedoch ako 0,200 — tie nuly
boli **výberové**, nie štrukturálne.

Pravidlo, ktoré z toho platí: **ak silnejší beh protirečí slabšiemu, tá protirečivosť je ten
nález.**

### 3.3 Odmietnuť radšej než spriemerovať

Viaceré redukcie radšej vyhodia výnimku, než by vrátili číslo, ktoré vyzerá použiteľne:

- `compare` **odmietne** párovanie, ak je voľná os, ktorú párovanie nezohľadňuje — inak by sa
  rozdiel bral voči ľubovoľnému z dvoch riadkov.
- `reference-curve` **odmietne** sweep, ktorý bežal na jednej referenčnej frekvencii: obe
  relácie, ktoré hlási, sú tvary voči tej frekvencii, a jednobodová krivka by sa čítala ako trend.
- `detector-table` **odmietne** sweep s jedným ramenom detektora, lebo spriemerovaný cez scenár by
  sa z piatich ramien stal jeden riadok opisujúci ensemble pod hlavičkou tvrdiacou, že ich
  porovnáva.
- Recall na scenári bez vloženej poruchy je **nedefinovaný, nie nulový**. Detektor nemôže minúť
  niečo, čo tam nikdy nebolo, a tabuľka, ktorá do tej bunky napíše 0,000, hovorí opak toho, čo sa
  stalo.

---

## 4. Čo sa reálne spustilo

Export stojí na **14 sweepoch a 4 454 behoch**, čo je 138 074 pozorovaní v dlhom formáte.

| sweep | behy | seedy | na čo |
|---|---:|---:|---|
| `ladder` | 63 | 3 | každý estimátor cez každý skórovateľný scenár |
| `ladder30` | 630 | 30 | to isté pri tridsiatich seedoch — prvé testy signifikancie |
| `cintron_ladder` | 63 | 3 | tie isté scenáre na fyzike **reálneho** prístroja |
| `cintron_ladder30` | 630 | 30 | to isté pri tridsiatich seedoch |
| `reference_rate` | 180 | 3 | referenčná frekvencia × rameno regulátora, Page-Hinkley 15,0 |
| `reference_rate_ph75` | 180 | 3 | to isté pri opravenom prahu 7,5 |
| `reference_rate30` | 1 260 | 15 | sedem frekvencií vrátane „každé vozidlo“, pri sile |
| `heldout30` | 360 | 30 | **štyri scenáre, na ktorých sa nič neladilo** |
| `ablation` | 150 | 10 | S6 s každou triedou poruchy postupne odstránenou |
| `governance` | 18 | 3 | slučka zapnutá/vypnutá na S6 |
| `detectors` | 100 | 10 | štyri detektory samostatne plus ensemble |
| `detector_thresholds` | 340 | 10 | 17 prahových ramien — zvyšok krivky recall/falošné poplachy |
| `recal_coverage` | 300 | 10 | frekvencia rekalibrácie proti pokrytiu intervalu |
| `theta2` | 180 | 30 | trojparametrická mapa proti dvojparametrickej |

Mimo sweepov: `wimsim validate-sim` — krížová validácia parametrov simulátora metódou „vynechaj
jeden záznam“ nad ôsmimi reálnymi nahrávkami.

---

## 5. Prahy Page-Hinkleyho, čiže prečo sa sweepy nedajú miešať

Odoslaná predvoľba bola **15,0** pre každý sweep okrem troch, a po `detector_thresholds` sa
presunula na **7,5**. Nič sa spätne nepreháňalo: **tá prahová krivka je sama výsledok**, a
prebehnúť všetko v jednom opravenom bode by zakrylo, ako sa našiel.

Dôsledok, ktorý treba povedať nahlas: konfigurácie starších sweepov stále hovoria
`edge_config: default`, a tá predvoľba sa dnes rozvinie na 7,5. **Ich spustenie dnes nezreprodukuje
uložené čísla.** Nesúlad je detegovateľný, nie tichý — každý riadok nesie `edge_config_hash` a ten
sa bude líšiť.

Preto novšie konfigurácie prah **pripínajú explicitne**: súbor, ktorý si zapíše vlastný pracovný
bod, znamená o rok to isté, čo znamená dnes.

---

## 6. Časy behu

Všetky čísla nižšie sú **namerané**, nie odhadnuté, a pochádzajú z `manifest.json` každého sweepu.

### 6.1 Ako čítať `elapsed_s`

Jedna vec sa dá ľahko prečítať zle. Pri sweepe, ktorý bežal po shardoch, je `elapsed_s` v
zlúčenom manifeste **súčet cez shardy**, nie hodiny na stenách — `merge_shards` ich jednoducho
spočíta. Shardy bežia súbežne, takže nástenný čas je približne `súčet / počet shardov`. Obe čísla
sú užitočné a nie sú to to isté: súčet hovorí, koľko strojového času to stálo, podiel hovorí, ako
dlho sa čakalo.

| sweep | behov | shardov | súčet | nástenný čas | s/beh |
|---|---:|---:|---:|---:|---:|
| `ladder` | 63 | 1 | 1,0 h | 1,0 h | 59 |
| `ladder30` | 630 | 3 | 37,0 h | ~12,3 h | 211 |
| `cintron_ladder` | 63 | 1 | 4,2 h | 4,2 h | 238 |
| `cintron_ladder30` | 630 | 5 | 35,6 h | ~7,1 h | 204 |
| `reference_rate` | 180 | 1 | 1,7 h | 1,7 h | **35** |
| `reference_rate_ph75` | 180 | 3 | 7,4 h | ~2,5 h | 148 |
| `reference_rate30` | 1 260 | 5 | **28,3 h** | ~5,7 h | 81 |
| `heldout30` | 360 | 10 | **22,8 h** | ~2,3 h | 228 |
| `ablation` | 150 | 5 | **8,9 h** | ~1,8 h | 213 |
| `governance` | 18 | 1 | 0,6 h | 0,6 h | 111 |
| `detectors` | 100 | 1 | 7,4 h | 7,4 h | 268 |
| `detector_thresholds` | 340 | 5 | 21,8 h | ~4,4 h | 231 |
| `recal_coverage` | 300 | 1 | 17,6 h | 17,6 h | 211 |
| `theta2` | 180 | 1 | 15,9 h | 15,9 h | 318 |

**Stĺpec „s/beh“ sa nedá porovnávať naprieč riadkami** a je tu napriek tomu, lebo bez neho sa
nedá prečítať nič ostatné. Líšia sa v troch veciach naraz: dĺžkou scenára (S1 má 6 h, S6 má 48 h
simulovaného času), počtom súbežných shardov, a tým, či sweep bežal pred alebo po optimalizácii
z §6.3. Posledné tri sweepy — `reference_rate30`, `heldout30`, `ablation` — sú jediné, ktoré bežali
na optimalizovanom kóde.

### 6.2 Paralelizmus tu nefunguje a je to zmerané

Tento stroj udrží približne **2,8 behu za minútu bez ohľadu na počet shardov**:

| súbežných procesov | behov/min |
|---:|---:|
| 1 | 1,7 |
| 5 | 2,79 |
| 10 | 2,6 |

Desať shardov teda nie je rýchlejších ako päť — nameraný rozdiel 2,6 oproti 2,79 je síce v
pásme merania, ale **zrýchlenie z neho nevyšlo žiadne**, a to je tvrdenie, ktoré to meranie unesie.
Pri desiatich procesoch bolo vyťaženie 7,5 jadra z dvanástich logických a **disk nečinný na 0,5 %** — záťaž je teda viazaná šírkou pásma pamäte, nie
procesorom ani vstupom/výstupom. Pridávanie procesov iba rozdeľuje pevnú priepustnosť na menšie
kúsky.

To je dôvod, prečo sa posledný sweep púšťal na piatich shardoch a nie na desiatich, a prečo sa
`heldout30`, `ablation` a `reference_rate30` púšťali **sekvenčne za sebou** a nie súbežne: celková
práca je rovnaká, ale sekvenčne je prvý z nich hotový za dve hodiny namiesto za deväť.

Druhé pozorovanie z toho istého merania: **cena behu je plochá voči referenčnej frekvencii**.
Beh pri jednej referencii na vozidlo trvá rovnako dlho ako beh pri jednej na päťdesiat, hoci robí
päťdesiatnásobok kalibračnej práce. Cenu teda určuje **generovanie signálu**, nie estimátor ani
regulátor.

### 6.3 Kde ten čas sedel a čo sa s tým dalo urobiť

Profilovanie ukázalo **61 %** času behu vnútri `Preprocessor._track_zero`, a väčšina z toho nebola
aritmetika — bola to Pythonovská réžia `np.quantile`, volaného 230 000-krát na beh nad trojprvkovým
poľom kvantilov. Jedna particia teraz obsluhuje všetky štyri poradové štatistiky:

| ten istý 16-hodinový beh S4 | čas |
|---|---:|
| pred optimalizáciou, sólo | **61,1 s** |
| po optimalizácii, sólo | **38,7 s** |
| pod 10-násobnou záťažou | ~3,8 min |

Priepustnosť tým stúpla z ~2,8 na **~4,4 behu za minútu**. Detaily a dôkaz bitovej zhody sú v
[`simulacia-sk.md` §10](simulacia-sk.md#10-výkon).

Jedna poznámka k profilovaniu samotnému: prvý profil bol **nepoužiteľný**, pretože hodinový beh
trval 17,5 s, z toho ~14 s zabral import `scipy`. Pri sweepe sa import zaplatí raz na proces a
amortizuje sa cez stovky behov, takže v profile vyzeral ako dominantná položka a nebol ňou. Druhý
profil si importy zaplatil dopredu.

### 6.4 Testy

| beh testovej sady | čas |
|---|---:|
| voľný stroj | ~185 s |
| súbežne s desiatimi workermi | **884 s** (14 min 44 s) |

Raz ju systém pri tejto záťaži aj **zabil pre nedostatok pamäte** — desať workerov drží okolo
3,1 GB a pytest potrebuje svoje. Praktický záver: plná sada sa púšťa, keď je stroj voľný, a počas
sweepov sa púšťajú len cielené súbory.

### 6.5 Čo z toho plynie pre plánovanie

- **Odhadni nástenný čas ako `počet_behov × s/beh_podobného_sweepu ÷ počet_shardov`** a potom to
  vynásob 1,3, lebo kontencia nie je lineárna.
- **Viac ako päť shardov nemá zmysel.** Pevná priepustnosť znamená, že desiaty shard iba spomalí
  prvých deväť.
- **Shard zapisuje výsledky až na konci.** Zabitý shard na 90 % je zabitý shard na 0 %, takže
  pri nedostatku času je lepšie dobehnúť menej seedov úplne než viac seedov spolovice. Preto
  `reference_rate30` bežal pätnásť seedov a nie tridsať — pätnásť je hotových a použiteľných,
  tridsať by bolo rozbehnutých.
- **Keď optimalizácia stojí hodinu práce a ušetrí štyri hodiny strojového času, oplatí sa** — ale
  iba vtedy, ak sa dá dokázať, že nemení výsledky. Tu sa to dokázať dalo, a preto sa spravila.

---

## 7. Reprodukcia

```bash
# jeden sweep, jeden proces
wimsim experiment ladder30 --out data/results/ladder30

# ten istý sweep po shardoch, keď sa ponáhľa
wimsim experiment reference_rate30 --seeds 1,2,3   --out data/results/reference_rate30_s1
wimsim experiment reference_rate30 --seeds 4,5,6   --out data/results/reference_rate30_s2
# ...a potom spojiť cez wimsim.experiments.merge.merge_shards

# čo sa spustí, bez toho, aby sa čokoľvek spustilo
wimsim experiment reference_rate30 --dry-run

# analýzy nad hotovým sweepom
wimsim compare          data/results/reference_rate30
wimsim reference-curve  data/results/reference_rate30
wimsim detector-table   data/results/detector_thresholds

# krížová validácia simulátora proti reálnym nahrávkam
wimsim validate-sim data/real --channel Tenzo2 --out data/results/sim_crossval

# prestavba celého exportu
python scripts/build_export.py
```

Overenie determinizmu — vygeneruj ten istý beh dvakrát a porovnaj hashe súborov:

```bash
wimsim generate S1_nominal --out /tmp/a --seed 1
wimsim generate S1_nominal --out /tmp/b --seed 1
wimsim verify-determinism /tmp/a /tmp/b
```

Porovnáva `samples.parquet`, `truth_passes.parquet` a `truth_timeseries.parquet` po bajtoch, plus
`config_hash` a `output_hash` z oboch manifestov.
