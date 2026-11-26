# Check against reality 2: the fuel rush, Great Britain, September 2021

Run on 26 November 2026. World: `hakoniwa/worlds/forecourt_evenings/`. A reference only: one event, one run per setting.

## What happened

There was no shortage of petrol in the country, only of tanker drivers. On the evening of 23 September 2021 the news reported that a large fuel company would close some stations. The next day drivers queued at forecourts across Britain, and many stations ran dry within two days.

## How the world was made

The tool built this world. It was given a scenario of about 400 words and a table of real daily figures. The world-building model (GPT-6.2 Astra) wrote the rules of the automaton, the recipe for a cast of 480 drivers, and each driver's life sketch. It passed the sandbox trial on the first attempt, in about 6 minutes, for $3.32.

- **World (an automaton).** Drivers use fuel every day and refuel at one of six stations by their own rule. A tank cannot hold more than its size. Stations hold about nine and a half days of normal sales and start 35% full.
- **Cast.** 480 drivers with their own district, job, car, mileage, refuelling habit, news habits and character.
- **AI.** A driver is asked when news reaches them or their situation changes, at most eight times in the run.
- **Real data used as input.** Daily deliveries to stations.
- **Real data used only as a test.** Daily sales and station stock. The world's own notes say: "Nothing is fitted to the supplied sales or stock series."

## Real figures

Daily averages per filling station from the UK government's [Average road fuel sales, deliveries and stock levels](https://www.gov.uk/government/statistics/average-road-fuel-sales-and-stock-levels) (sub-regional file for 2021, "Total" fuel, mean of 176 sub-regions). Sales are shown as an index: 100 is the average for the same weekday between 30 August and 19 September.

## Results

| | Peak day | Peak sales (normal = 100) | Next two days | Lowest station stock | Sales, weeks 4–6 | Sales shape (correlation) | Stock shape (correlation) |
|---|---|---|---|---|---|---|---|
| **Reality** | **Fri 24 Sep** | **191** | **155, 132** | **18%** | **93, 90, 93** | – | – |
| Fixed rules only | Fri 24 Sep | 208 | 178, 126 | 10% | 96, 91, 95 | 0.79 | 0.93 |
| AI residents | Fri 24 Sep | 305 | 146, 130 | 3% | 83, 87, 88 | 0.86 | 0.98 |
| AI residents, country and year hidden | Fri 24 Sep | 325 | 116, 130 | 3% | 74, 86, 92 | 0.83 | 0.98 |

One AI run cost $0.43 (2,616 questions) and took about 11 minutes.

## Where it matched

- The rush peaked on the right day in every run.
- Sales fell below normal in the following weeks and stayed there, as they did in reality. People who have filled their tanks need less for a while. The world reproduced this without being told.
- Station stock fell, stayed low for about a week, then climbed above its starting level, following the real curve closely.
- With fixed rules alone, the height of the peak was within 10% of the real one.

## Where it did not

- **AI residents overreacted.** They wanted 404 on the peak day and bought 305, against a real 191, and they emptied every station, where the real average stock only fell to 18%.
- With AI residents the dip in later weeks was a little too deep (83–88 against 90–93), because more people had filled up.
- Hiding the country and the year made no real difference, so the overreaction is not a memory of the event.

## After the residents' instructions were changed

The overreaction was followed up with a dozen more runs on the same world, changing one thing at a time. The table shows the ones that settled the question; one run each.

| Residents | Peak sales (real 191) | Wanted on the peak day | Next two days (real 155, 132) | Lowest stock (real 18%) | Mean daily error, sales / stock |
|---|---|---|---|---|---|
| Fixed rules only | 208 | 209 | 178, 126 | 10% | 12.3 / 4.8 |
| AI, instructions as above | 305 | 404 | 146, 130 | 3% | 15.3 / 7.0 |
| AI, without each person's own description | 332 | 605 | 116, 130 | 3% | 16.4 / 8.3 |
| **AI, new instructions (now the default)** | **233** | **244** | **190, 112** | **7%** | **12.6 / 6.4** |
| The same, second random seed | 249 | 249 | 138, 108 | 10% | 13.6 / 6.7 |
| AI, new instructions, half act on a change of mind | 164 | 164 | 147, 81 | 19% | 13.2 / 9.4 |

- **Personal descriptions matter.** Without them residents wanted half as much again (605 against 404). They are necessary, and not sufficient.
- **The instructions were part of the problem.** Each question shows what the world's own formula would do for that person. The old instructions said "do not copy the default", which pushed residents away from it. The new ones say that most people change nothing on most days, and that the formula's answer is the likely one unless this person has a real reason to differ.
- **Two more corrections were built and are off by default**: asking only people a decision model judges would stop to think, and letting only a share of residents act on a change of mind. With the new instructions the second one undershoots here (164).
- What is still wrong: the simulated rush is over in two days. The real one faded over a week (week three was still at 110; the simulation gives 88).

The tool also rebuilt this world a third time from the same scenario, with further instructions to the world-building model. That build was worse (peak 301 with fixed rules, 373 with AI residents). Worlds differ from build to build, so one build is one sample. The second build remains the sample world.

## The same event, before the tool was improved

The first world the tool built for this scenario did worse, and showed why.

| | First build | Second build (above) |
|---|---|---|
| Peak sales with AI residents | 322, every station dry on the first day | 305, every station dry on the first day |
| Peak sales with fixed rules | 322 | 208 |
| Choices on the evening of the news | 197 of 200 drivers asked chose the same option | 202 of 427 chose "carry on exactly as before"; the rest split four ways (73, 70, 46, 36) |
| Mean error in daily sales, AI residents | 24 points | 15 points |

In the first build the question to drivers had no option for doing nothing, and only some drivers were asked each day. Three instructions were then added to the world-building model: always offer "carry on exactly as before", ask everyone the news reached, and record what people wanted separately from what was sold. The second build is the result. Residents became far more varied, and the rules alone came close to reality, but AI residents still react more strongly than real drivers did.

## A what-if branch worth noting

In the first build, a branch with a £30 limit per customer came closer to reality (241 and 208 on the two peak days) than the run without it. Some retailers did impose that limit. One run only.

## What this says about the method

- Getting the timing and the shape right is achievable with a world built entirely by the tool.
- The size of people's reaction is the weak point. How the residents are asked changes it as much as who they are.
- A check like this is how such a bias is found. Without the real series, the first build would have looked plausible.
