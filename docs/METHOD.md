# Telltale — Scoring & Handicap Method

A precise statement of the maths Telltale uses. It follows a classic
club-handicap scoring tradition (base-100 corrected time with monthly personal
adjustments); the exact clauses below are configurable in `config/`.

## Scales

* Everything is on the club's **base-100** scale. A boat/helm/crew handicap near
  100 is "average"; **lower = stronger**.
* The reference spreadsheets are on a **modified RYA-PY** scale. The conversion is
  exact:

  ```
  base-100 value = round( PY value / 10 )
  ```

  e.g. Enterprise PY 1126 → 113; a helm at PY −126 → −13; crew PY −20 → −2.

## Per-race scoring

For each entry, `elapsed = finish − start` (per its own start group).

* **Net handicap**  `g = boat_HC + personal_HC + crew_HC`
* **Corrected time** `= round_half_up(elapsed × 100 / g)` — rank ascending,
  lowest wins. (`round_half_up` = round to nearest integer, halves away from zero,
  matching the old app.)

Three modes:

| mode | net handicap `g` | feeds handicap update? |
|------|------------------|------------------------|
| `standard`   | boat + personal + crew | yes |
| `boat_only`  | boat only              | no  |
| `one_design` | 100 for everyone (ranks on raw elapsed) | no |

## The handicap signal (standard mode only)

Crew is **excluded** here:

* `CT2 = elapsed × 100 / (boat_HC + personal_HC)`
* `median = ` median of all finishers' `CT2` (the race's "middle boat")
* `handicap_sailed = elapsed × 100 / median`
* `deviation = handicap_sailed − (boat_HC + personal_HC)`

A boat slower than the fleet middle (for its rating) gets a **positive**
deviation → its personal handicap rises (more advantage next time); faster boats
get a negative deviation. This is the self-correcting loop.

## Monthly personal-handicap update

Once per calendar month, for each helm:

* `average_deviation = mean(` that month's deviations `)`
* needs **≥ 2 races** that month to qualify, else no change;
* `change = round_half_up(average_deviation)`, then **capped at ±2**;
* `new_personal_HC = old_personal_HC + change`.

No fleet-wide normalisation; helms who didn't race don't move; a helm with no
club handicap starts at **0**. **Crew handicaps are never changed.** There is no
floor or ceiling on a personal handicap beyond the ±2 monthly cap.

## Series (low-point)

Points = finishing position; a non-finisher scores `(number of starters + 1)`.
Apply the configured number of discards; rank by net points (ties broken by count
of better finishes). A typical season trophy is the example: 12 races,
3 discards, 8 to count, boat handicaps only.

## Trophy scoring defaults

* **Boat handicaps only:** Peel Yates, Copenhagen, Lipton Tray, Lipton Tray (II),
  season medals, and crew-racing trophies (→ boat HC only).
* **One-design (committee-set starts):** Pakistan Challenge Cup, Tomtit Challenge
  Cup (Tindal trophies — handicap is applied via the start times).
* **Ilse Memorial:** standard handicap **plus +3 for a lady helm and +2 more if
  the crew is also a lady, capped at +5**.
* **Ladies-only entry but standard handicap:** Ladies Challenge Cup, Murray
  Challenge Cup.
* **Everything else:** standard club handicap.

Each trophy shows its recommended scheme before the race and the operator may
override it.

## Progressive series handicaps (task 12 — Commodore-style)

For a multi-race series the operator may pick a **progressive** handicap that
evolves race-by-race, instead of the saved monthly handicap. These are computed
for the **series only** — the club's normal monthly handicap process is untouched.

### Scheme A — ±1 per race from 0

* Every helm in the series starts at personal handicap **0** for race 1.
* Each race is scored on `corrected = round_half_up(elapsed × 100 / (boat_HC +
  crew_HC + series_personal))` and ranked.
* After the race, each finisher's series handicap moves **one point** toward the
  fleet: if their corrected time was **better** than the fleet mean corrected
  time they go **−1** (stronger), if **worse** they go **+1**; the per-race step
  is capped at **±1**. Non-finishers carry their handicap unchanged.
* This is intentionally simple and self-limiting; over a season it nudges the
  fastest series performers down and the slowest up by at most one per race.

### Scheme B — NHC-style, base 100

Adapted from the HalSail National Handicap (NHC) scheme to the club's base-100
scale. Everyone starts a race at **base 100** the first time; thereafter the
handicap from the previous race carries in. For each race with **≥ 3** finishers:

1. `corrected_i = elapsed_i × 100 / rating_i` for each finisher (base-100 form of
   the NHC `elapsed × 1000 / rating`).
2. Compute the mean `μ` and standard deviation `σ` of the finishers' corrected
   times. Clamp each `corrected_i` to `μ ± 1σ` (the NHC "extreme performer"
   rule) — this stops one runaway result from swinging the fleet.
3. **Per-boat achieved handicap** `Hₐ_i = H1_i × (CT_i_clamped / μ)`, where
   `H1_i` is the boat's handicap going into the race. (Using a per-boat achieved
   value is essential: a single fleet-wide achieved handicap never differentiates
   boats when they all start equal at 100.)
4. **Blend** toward the achieved value with `α = 0.3`:
   `Hₚ_i = (1 − α)·H1_i + α·Hₐ_i = 0.7·H1_i + 0.3·Hₐ_i`.
5. **Realign** so the fleet mean returns to base 100 (add `100 − mean(Hₚ)` to
   every boat), then **clamp** each handicap to **[90, 110]** (the ±10 % band).
6. Non-finishers, and every race with fewer than 3 finishers, **carry** the
   previous handicap unchanged.

Faster boats are driven toward 90 (less advantage), slower boats toward 110
(more), with the fleet always recentred on 100.

### Output

Both schemes feed the normal low-point series engine (positions → points,
discards, minimum-races) for the standings, and additionally produce a **per-race
digest**: for each race, the finishing order with the **handicap used** that race
and an **▲ / ▼ / —** flag versus the handicap used in the previous race. The sheet
is stamped **Provisional** or **Final**. This reproduces the layout of the club's
Sailwave Commodore Series PDF.
