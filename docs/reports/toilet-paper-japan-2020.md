# Check against reality 1: the toilet-paper run, Japan, February 2020

Run on 26 November 2026. World: `hakoniwa/worlds/tp_2020/`. A reference only: one event, few real figures, one or two runs per setting.

## What happened

On 27 February 2020 a post on social media claimed toilet paper would run out because of the new coronavirus. The next day TV showed empty shelves. The makers' association and the government said stock was plentiful. Shops were stripped anyway.

## What was simulated

- **World (an automaton).** 240 households, six shops and a wholesaler. Each household uses rolls every day and follows a small rule: below how many rolls it buys, how many packs, how hard it tries.
- **Cast.** Every household has its own make-up, work, area, way of getting news (social media, TV, family and friends, hardly any), and character (how easily it worries, how much it follows others, how far it trusts official statements), plus a life sketch.
- **AI.** A household is asked only when it learns something new (the rumour, an empty shelf, the statement, a refilled shelf). The answer rewrites that household's rule. About four to five questions per household over six weeks.

This world was written by hand as a first trial of the method. The second check ([UK fuel, 2021](./uk-fuel-2021.md)) was built by the tool itself.

## Real figures used

| Target | Reality | Source |
|---|---|---|
| Unit sales on 28 Feb | about 6 times the January daily average; that day stands out alone | TrueData drugstore POS, reported by [ITmedia](https://www.itmedia.co.jp/business/articles/2003/27/news113.html) |
| Sales in the week of 24 Feb | about 2.4 times the same week a year earlier, then a sharp fall | drugstore POS, reported by [Toyo Keizai](https://toyokeizai.net/articles/-/338126?page=2) |

Week-by-week figures exist only as charts in those articles and could not be read.

## Results

A normal day = 100. "Wanted" counts what people came for, including what they could not get.

| Residents played by | Sold on 28 Feb | Wanted on 28 Feb | Peak day | Week of 24 Feb, then 4 weeks later | Trips that found nothing | AI cost |
|---|---|---|---|---|---|---|
| **Reality** | **about 600** | (at least 600) | **28 Feb** | **about 240, then a sharp fall** | – | – |
| Fixed rules only | 510 | 1,378 | 28 Feb | 253 → 204 | 2,970 | $0 |
| AI (thought and speech) | 510 | 782 | 28 Feb | 243 → 107 | 173 | $0.24 |
| AI, second random seed | 510 | 816 | 28 Feb | 236 → 119 | 146 | $0.26 |
| AI, country, year and disease hidden | 493 | 646 | 28 Feb | 248 → 119 | 113 | $0.25 |
| AI, decisions API only | 391 | 493–544 | 29 Feb – 1 Mar | 250 → 204 | 505–1,059 | $0.16 |

## Where it matched

- With AI residents the rush peaked on 28 February, the day after the rumour, as it did in reality.
- People came for about 8 times a normal day's amount on 28 February; real sales were about 6 times.
- With AI residents buying returned to normal in four to five weeks. With fixed rules alone it never did: households that failed kept coming back every day.
- Hiding the country, the year and the disease changed little, so the model was not simply recalling this event.

## Where it did not, and what cannot be said

- Sales on 28 February reached 510, not about 600. Shop stock was assumed to be six days of normal sales, which caps what can be sold in a day.
- The weekly total is **not** evidence. The amount shops and the wholesaler could supply was set so that the week could reach the real figure.
- After the peak, simulated sales fell over four weeks. Reports describe a sharp fall. Without weekly data the gap cannot be measured.
- Residents played through the decisions API calmed down too slowly. Asked for a number as an ordered scale, the answers drift to the middle.
- Household make-up and character come from assumed distributions, not a survey.

## After the residents' instructions were changed

The checks on [fuel](./uk-fuel-2021.md#after-the-residents-instructions-were-changed) and air travel led to new instructions for residents. Run again here, the result barely moved: sold 510 and wanted 731 on 28 February (816 with a second random seed), sales peak on 28 February, 238 for the week, back to normal in about four weeks. An in-between wording that hid the formula's answer from residents made them underreact here (357 sold on 28 February), which is why it was dropped.

## What-if branches

Forked from the AI run on the morning before the rumour. One run each: read the direction, not the size.

| What if | Wanted, week of 24 Feb | Trips that found nothing |
|---|---|---|
| (as it happened) | 369 | 173 |
| TV did not show the empty shelves | 219 | 5 |
| The statement came with the rumour | 323 | 92 |
| Extra shipments arrived within two days | 401 | 100 |
| Purchase limits from the first day | 386 | 150 |
