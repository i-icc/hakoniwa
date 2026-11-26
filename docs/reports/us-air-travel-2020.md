# Check against reality 3: the collapse of US air travel, March 2020

Run on 26 November 2026. World: `hakoniwa/worlds/the_unused_ticket/`. A reference only: one event, one run per setting.

## What happened

In the first week of March 2020 companies began to ban business travel. On 11 March the WHO declared a pandemic and travel from Europe was banned. A national emergency followed on 13 March, federal guidance against discretionary travel on 16 March, and stay-at-home orders from 19 March. The number of people passing through airport security fell from about the level of a year before to about 5% of it within four weeks.

## How the world was made

The tool built this world from a scenario of about 400 words and a table of real daily figures. The world-building model (GPT-6.2 Astra) wrote the rules, the recipe for a cast of 490 travellers and their life sketches. It passed the sandbox trial on the first attempt, in about 6 minutes, for $2.94.

- **World (an automaton).** Each traveller holds a trip with a date, a purpose, a fare and refund terms. Employers ban trips, events are called off, airlines withdraw flights, new bookings slow.
- **Cast.** 490 travellers with their own purpose, age, health, vulnerable relatives, news habits and character.
- **AI.** A traveller is asked what to do with a coming trip (fly as planned, move it, give it up) when news reaches them.
- **Real data used only as a test.** The daily count at security checkpoints as a percentage of the same weekday a year earlier. The world's own notes say: "No coefficients were fitted to checkpoint counts or indices."

## Real figures

[TSA checkpoint travel numbers](https://www.tsa.gov/travel/passenger-volumes), 2020 against the same weekday in 2019, 17 February to 26 April.

## Results

Weekly averages of the index (100 = the same week a year earlier). Weeks start on 17 February.

| Week starting | 17 Feb | 24 Feb | 2 Mar | 9 Mar | 16 Mar | 23 Mar | 30 Mar | 6 Apr | 13 Apr | 20 Apr |
|---|---|---|---|---|---|---|---|---|---|---|
| **Reality** | **102** | **100** | **91** | **74** | **34** | **12** | **8** | **6** | **5** | **6** |
| Fixed rules only | 100 | 100 | 94 | 96 | 67 | 10 | 4 | 2 | 0 | 8 |
| AI residents | 100 | 96 | 65 | 39 | 47 | 8 | 4 | 0 | 2 | 0 |
| AI residents, country and year hidden | 100 | 96 | 55 | 31 | 51 | 6 | 4 | 0 | 2 | 0 |

| | Seven-day average first below 75 | below 50 | below 25 | Weekly error (points) | Weekly correlation |
|---|---|---|---|---|---|
| **Reality** | **12 Mar** | **17 Mar** | **21 Mar** | – | – |
| Fixed rules only | 19 Mar | 21 Mar | 22 Mar | 7.7 | 0.96 |
| AI residents | 3 Mar | 10 Mar | 22 Mar | 10.3 | 0.95 |
| AI residents, country and year hidden | 2 Mar | 6 Mar | 22 Mar | 12.7 | 0.91 |

One AI run cost $0.36 (2,154 questions).

## Where it matched

- Travel collapsed to almost nothing by the last week of March in every run, and stayed there through April.
- The date by which travel had fallen below a quarter of normal was within a day of the real one (21–22 March).
- Residents were varied. Of 392 travellers asked, 238 first chose to carry on and 154 to move the trip. On 13 March, 53 of the 126 asked carried on, 67 moved the trip and 6 gave it up. 109 never changed their plans in any answer.

## Where it did not

- **AI residents pulled back too early.** They were below 75% nine days before real travellers were. Real travel in the week of 9 March was still at 74%; the AI residents were at 39%.
- **Fixed rules pulled back too late.** They held at 96% in the week of 9 March.
- The floor is 0–4% in the simulation against 5–8% in reality.
- The daily figure is coarse. Only about seven simulated travellers fly on a normal day, so one person is 14 points. The weekly averages above are the fair comparison. The tool's instructions now ask for at least 50 actions a day.

## After the residents' instructions were changed

The residents' instructions were then changed (see the [fuel report](./uk-fuel-2021.md#after-the-residents-instructions-were-changed)): most people change nothing on most days, and the world's own formula is the likely answer unless this person has a real reason to differ. Same world, two runs with different random seeds.

| Week starting | 17 Feb | 24 Feb | 2 Mar | 9 Mar | 16 Mar | 23 Mar | 30 Mar | 6 Apr | 13 Apr | 20 Apr |
|---|---|---|---|---|---|---|---|---|---|---|
| **Reality** | **102** | **100** | **91** | **74** | **34** | **12** | **8** | **6** | **5** | **6** |
| AI, instructions as above | 100 | 96 | 65 | 39 | 47 | 8 | 4 | 0 | 2 | 0 |
| **AI, new instructions (now the default)** | 100 | 96 | 84 | 67 | 53 | 4 | 4 | 2 | 4 | 8 |
| The same, second random seed | 100 | 96 | 78 | 65 | 59 | 2 | 0 | 6 | 16 | 0 |

| | Seven-day average first below 75 | below 50 | below 25 | Weekly error (points) | Weekly correlation |
|---|---|---|---|---|---|
| **Reality** | **12 Mar** | **17 Mar** | **21 Mar** | – | – |
| Fixed rules only | 19 Mar | 21 Mar | 22 Mar | 7.7 | 0.96 |
| AI, instructions as above | 3 Mar | 10 Mar | 22 Mar | 10.3 | 0.95 |
| **AI, new instructions** | **11 Mar** | **20 Mar** | **22 Mar** | **5.8** | **0.98** |
| The same, second random seed | 4 Mar | 21 Mar | 23 Mar | 8.8 | 0.96 |

The early pull-back is smaller, and not reliably gone: the slide starts one day early in one run and eight days early in the other. The week of 16 March is still too high (53 and 59 against 34). The gain over the earlier instructions is about the size of the spread between the two runs, and fixed rules alone are in the same range (7.7). The instructions were written after looking at the fuel check and were not tuned on this one.

## What this says about the method

- The overall path (hold, slide, collapse, stay down) came out of a world the tool built alone.
- As in the fuel check, AI residents first moved sooner than real people did, and the fixed rules erred the other way. Changing how residents are asked brought them closer, to about where the fixed rules are.
- One run is one sample. Two runs that differ only in the random seed were eight days apart on when the slide began.
