# 2nd Annual Rose Murphy Memorial Youth Scholarship

Weekend dry-run standings with stepladder champions.

| | |
|---|---|
| Event | 2nd Annual Rose Murphy Memorial Youth Scholarship |
| Preset | Rose Murphy Memorial Youth Scholarship (Forest Hill Lanes, Dec 6 2026) |
| Host | Forest Hill Lanes (FHL), 1 Maurice Drive, Forest Hill, MD 21050 |
| Date | Sunday, December 6, 2026, 10:00 AM |
| Format | Singles, 3 games, same pair |
| Handicap | 90% of 220, fraction dropped (`divisions.handicap_for` / `assign_all`) |
| Field | 40 youth |
| Fees | All 40 marked paid. The $30 entry is collected at the Forest Hill front desk (`fees_at_front_desk`). |
| Ranking | Division × Boys/Girls |
| Finals | Top 5 when the group has more than 25 bowlers; otherwise top 3 (`divisions.finalists_count`) |
| Lanes | Lanes 1–20, two bowlers per lane. `same_pair`: games 2 and 3 stay on the starting lane. |
| Database | Temporary SQLite through `db_state`. Practice Mode is off (`is_practice` = 0). |

This was a simulated dry run using Prism modules. It is not a live Streamlit Cloud session and it is not the December 6 tournament. Names, USBC IDs, SMART accounts, birth dates, and scores are fictional. Re-run `python scripts/rose_murphy_dry_run.py` (seed 20261206) to reprint this report.

Forty bowlers can fill one division × gender group past 25. This field puts 26 bowlers in Division 2 Boys so the top-5 stepladder runs. Every other group has 25 or fewer bowlers, so Prism uses top 3. When the field is smaller than that cut, every bowler with scores is a finalist.

## Stepladder champions

| Group | Field | Finals | Qualifying leader | Champion |
|---|---|---|---|---|
| Division 1 – Boys | 3 | Top 3 | Isaac Romero | Kai Moreno |
| Division 1 – Girls | 3 | Top 3 | Emma Ruiz | Chloe Bennett |
| Division 2 – Boys | 26 | Top 5 | Henry Diaz | Ryan Foster |
| Division 2 – Girls | 3 | Top 3 | Isla Donovan | Hannah Kim |
| Division 3 – Boys | 3 | Top 3 | Marcus Webb | Marcus Webb |
| Division 3 – Girls | 2 | Top 3 | Sophia Alvarez | Maya Chen |

The champion is the stepladder winner. The qualifying leader is rank 1 on the handicap series before the ladder.

## Finals cut

| Group | Bowlers | Rule (`finalists_count`) | In the ladder |
|---|---|---|---|
| Division 1 – Boys | 3 | Top 3 (cut 3) | 3 |
| Division 1 – Girls | 3 | Top 3 (cut 3) | 3 |
| Division 2 – Boys | 26 | Top 5 (cut 5) | 5 |
| Division 2 – Girls | 3 | Top 3 (cut 3) | 3 |
| Division 3 – Boys | 3 | Top 3 (cut 3) | 3 |
| Division 3 – Girls | 2 | Top 3 (cut 3) | 2 (field smaller than the cut) |

## Qualifying standings

HDCP is pins per game, stored on the bowler by `divisions.assign_all`. Total = G1 + G2 + G3 + HDCP × 3, which is the `grouped_results` handicap series. Finalist follows that series and any cut roll-off. Lane, lineup, USBC ID, SMART account, birth date, and age group are in `artifacts/rose_murphy_dry_run_qualifying.csv`.

### Division 1 Boys (average 160 and above) · 1st place: $500 SMART scholarship

3 bowlers. Top 3. 3 finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Isaac Romero | 185 | 183 | 192 | 169 | 31 | 544 | 637 | Yes |
| 2 | Hunter Ellis | 168 | 158 | 153 | 176 | 46 | 487 | 625 | Yes |
| 3 | Kai Moreno | 201 | 201 | 186 | 182 | 17 | 569 | 620 | Yes |

### Division 1 Girls (average 160 and above) · 1st place: $500 SMART scholarship

3 bowlers. Top 3. 3 finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Emma Ruiz | 194 | 172 | 200 | 200 | 23 | 572 | 641 | Yes |
| 2 | Chloe Bennett | 176 | 160 | 192 | 162 | 39 | 514 | 631 | Yes |
| 3 | Ava Sinclair | 162 | 149 | 182 | 143 | 52 | 474 | 630 | Yes |

### Division 2 Boys (average 126–159) · 1st place: $300 SMART scholarship

26 bowlers. Top 5. 5 finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Henry Diaz | 148 | 150 | 169 | 167 | 64 | 486 | 678 | Yes |
| 2 | Lucas Bennett | 140 | 143 | 150 | 161 | 72 | 454 | 670 | Yes |
| 3 | Ryan Foster | 155 | 151 | 174 | 166 | 58 | 491 | 665 | Yes |
| T4 | Owen Price | 136 | 145 | 155 | 134 | 75 | 434 | 659 | Yes |
| T4 | Mason Hale | 128 | 147 | 126 | 140 | 82 | 413 | 659 | Yes |
| 6 | Jacob Nguyen | 138 | 156 | 156 | 125 | 73 | 437 | 656 | No |
| 7 | Nathan Cole | 153 | 148 | 163 | 163 | 60 | 474 | 654 | No |
| 8 | Parker Reid | 154 | 164 | 166 | 144 | 59 | 474 | 651 | No |
| 9 | Connor Blake | 133 | 141 | 136 | 139 | 78 | 416 | 650 | No |
| 10 | Leo Park | 151 | 159 | 130 | 169 | 62 | 458 | 644 | No |
| 11 | Tyler Jennings | 157 | 165 | 139 | 170 | 56 | 474 | 642 | No |
| 12 | Gavin Moore | 146 | 168 | 141 | 132 | 66 | 441 | 639 | No |
| 13 | Noah Keller | 132 | 111 | 139 | 150 | 79 | 400 | 637 | No |
| 14 | Miles Grant | 152 | 144 | 141 | 167 | 61 | 452 | 635 | No |
| 15 | Samuel Ortiz | 156 | 176 | 138 | 146 | 57 | 460 | 631 | No |
| 16 | Wyatt Lang | 158 | 141 | 180 | 143 | 55 | 464 | 629 | No |
| T17 | Jack Sullivan | 150 | 150 | 161 | 128 | 63 | 439 | 628 | No |
| T17 | Ethan Brooks | 130 | 130 | 132 | 123 | 81 | 385 | 628 | No |
| 19 | Aiden Walsh | 142 | 139 | 145 | 133 | 70 | 417 | 627 | No |
| 20 | Zachary Pitt | 159 | 164 | 143 | 156 | 54 | 463 | 625 | No |
| 21 | Caleb Brennan | 126 | 142 | 108 | 121 | 84 | 371 | 623 | No |
| 22 | Liam Hart | 134 | 131 | 115 | 141 | 77 | 387 | 618 | No |
| 23 | Finn Harper | 147 | 126 | 134 | 161 | 65 | 421 | 616 | No |
| 24 | Dylan Shaw | 141 | 143 | 130 | 120 | 71 | 393 | 606 | No |
| 25 | Eli Carter | 144 | 135 | 132 | 126 | 68 | 393 | 597 | No |
| 26 | Grayson Holt | 137 | 116 | 118 | 132 | 74 | 366 | 588 | No |

### Division 2 Girls (average 126–159) · 1st place: $300 SMART scholarship

3 bowlers. Top 3. 3 finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Isla Donovan | 157 | 174 | 156 | 166 | 56 | 496 | 664 | Yes |
| 2 | Hannah Kim | 143 | 147 | 136 | 145 | 69 | 428 | 635 | Yes |
| 3 | Grace Patel | 129 | 147 | 121 | 116 | 81 | 384 | 627 | Yes |

### Division 3 Boys (average 125 and under) · 1st place: $150 SMART scholarship

3 bowlers. Top 3. 3 finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Marcus Webb | 112 | 105 | 113 | 124 | 97 | 342 | 633 | Yes |
| 2 | Logan Pierce | 98 | 83 | 87 | 107 | 109 | 277 | 604 | Yes |
| 3 | Nolan Briggs | 124 | 114 | 102 | 115 | 86 | 331 | 589 | Yes |

### Division 3 Girls (average 125 and under) · 1st place: $150 SMART scholarship

2 bowlers. Top 3 (`finalists_count` is 3). The field is smaller than the cut, so both bowlers with scores are finalists.

| Rank | Name | Avg | G1 | G2 | G3 | HDCP | Scratch | Total | Finalist |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Sophia Alvarez | 119 | 141 | 124 | 132 | 90 | 397 | 667 | Yes |
| 2 | Maya Chen | 87 | 94 | 89 | 103 | 119 | 286 | 643 | Yes |

## Cut roll-offs

No group tied at the last finalist spot, so no roll-off was required.

## Stepladder

One game per match. The score entered is the handicap total (scratch near the bowler's average + the per-game handicap already stored on the bowler), capped by `stepladder.max_match_score`. Lowest seed bowls the next seed. The winner moves up. A tied game uses a one-game roll-off.

### Division 1 Boys (average 160 and above) · 1st place: $500 SMART scholarship

Top 3 · 2 matches.

Seeds (best qualifying first): #1 Isaac Romero, #2 Hunter Ellis, #3 Kai Moreno.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Match 1 (#3 seed vs #2 seed) | Kai Moreno | 240 | Hunter Ellis | 212 | Kai Moreno | — |
| Championship (vs #1 seed) | Kai Moreno | 203 | Isaac Romero | 199 | Kai Moreno | — |

**Champion: Kai Moreno**

### Division 1 Girls (average 160 and above) · 1st place: $500 SMART scholarship

Top 3 · 2 matches.

Seeds (best qualifying first): #1 Emma Ruiz, #2 Chloe Bennett, #3 Ava Sinclair.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Match 1 (#3 seed vs #2 seed) | Ava Sinclair | 189 | Chloe Bennett | 210 | Chloe Bennett | — |
| Championship (vs #1 seed) | Chloe Bennett | 231 | Emma Ruiz | 185 | Chloe Bennett | — |

**Champion: Chloe Bennett**

### Division 2 Boys (average 126–159) · 1st place: $300 SMART scholarship

Top 5 · 4 matches.

Seeds (best qualifying first): #1 Henry Diaz, #2 Lucas Bennett, #3 Ryan Foster, #4 Owen Price, #5 Mason Hale.

Tied handicap total 659: #4 Owen Price (scratch 434), #5 Mason Hale (scratch 413). Each of them is inside the cut, so each is a finalist. The better seed is the higher scratch series.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Match 1 (#5 seed vs #4 seed) | Mason Hale | 183 | Owen Price | 230 | Owen Price | — |
| Match 2 (winner vs #3 seed) | Owen Price | 179 | Ryan Foster | 240 | Ryan Foster | — |
| Match 3 (winner vs #2 seed) | Ryan Foster | 245 | Lucas Bennett | 237 | Ryan Foster | — |
| Championship (vs #1 seed) | Ryan Foster | 229 | Henry Diaz | 227 | Ryan Foster | — |

**Champion: Ryan Foster**

### Division 2 Girls (average 126–159) · 1st place: $300 SMART scholarship

Top 3 · 2 matches.

Seeds (best qualifying first): #1 Isla Donovan, #2 Hannah Kim, #3 Grace Patel.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Match 1 (#3 seed vs #2 seed) | Grace Patel | 178 | Hannah Kim | 220 | Hannah Kim | — |
| Championship (vs #1 seed) | Hannah Kim | 227 | Isla Donovan | 223 | Hannah Kim | — |

**Champion: Hannah Kim**

### Division 3 Boys (average 125 and under) · 1st place: $150 SMART scholarship

Top 3 · 2 matches.

Seeds (best qualifying first): #1 Marcus Webb, #2 Logan Pierce, #3 Nolan Briggs.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Match 1 (#3 seed vs #2 seed) | Nolan Briggs | 216 | Logan Pierce | 239 | Logan Pierce | — |
| Championship (vs #1 seed) | Logan Pierce | 217 | Marcus Webb | 222 | Marcus Webb | — |

**Champion: Marcus Webb**

### Division 3 Girls (average 125 and under) · 1st place: $150 SMART scholarship

Top 3 · 1 match.

Seeds (best qualifying first): #1 Sophia Alvarez, #2 Maya Chen.

| Match | Low seed | Score | High seed | Score | Winner | Roll-off |
|---|---|---|---|---|---|---|
| Championship (vs #1 seed) | Maya Chen | 235 | Sophia Alvarez | 233 | Maya Chen | — |

**Champion: Maya Chen**

## How this run used Prism

- Tournament: `create_tournament_from_template` with `Rose Murphy Memorial Youth Scholarship (Forest Hill Lanes, Dec 6 2026)`. The preset locks Forest Hill Lanes, 3 games, handicap 90% of 220, division × gender, same-pair lanes, youth-only, USBC, SMART, gender, and birth date.
- Roster: each bowler passed `divisions.entry_problems` (checked November 1, 2026, before the November 29 deadline) and was placed by `divisions.assign_all`, which calls `handicap_for`.
- Scores: three scratch games near the entering average. Each score row stores that scratch, the bowler's handicap, and scratch + handicap. Standings come from `divisions.grouped_results` (group standings plus `finalists_count`).
- Finals: `stepladder.initialize_stepladder` and `stepladder.record_stepladder_score` through the last match. Champions are `stepladder.champion`.
- This run did not call Practice Mode. `tournaments.is_practice` is 0. The database was a temporary SQLite file, not the live Streamlit Cloud desk.
