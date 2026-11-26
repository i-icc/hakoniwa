# Check against reality 4: when the fixtures disappeared, Great Britain, spring 2020

Run on 26 November 2026. World: `hakoniwa/worlds/the_missing_fixtures/`. A reference only: one event, one run per setting, monthly figures.

## What happened

English football was suspended on 13 March 2020 and British horse racing stopped after 17 March. For two months a bookmaker could offer little more than Belarusian football, table tennis, virtual sports and esports. German football returned on 16 May, British racing on 1 June, the Premier League on 17 June.

## The hypothesis

When sport stopped, most sports bettors simply stopped betting and came back when sport returned. Only a small minority moved to slots, poker or virtual sports.

## How the world was made

The tool built it from a scenario of about 470 words and a table of real monthly figures. The world-building model (GPT-6.2 Astra) wrote the rules, the recipe for a cast of 500 people who had placed a sports bet that winter, and their life sketches. It passed the sandbox trial on the first attempt, in about 7 minutes, for $3.50.

- **World (an automaton).** One step is a week, 2 March to 30 August. The fixture calendar is an input. Each person has a weekly leisure wallet, a betting habit, and the products they already used.
- **AI.** A person is asked when the calendar changes for them or an offer reaches them: carry on, stop and keep the money, bet on unfamiliar sports, move to virtual sports, slots, casino games or poker.
- **Real data used only as a test.** All seven recorded series. The world's own notes say: "Nothing is fitted to the seven March–August outcome series."

## Real figures

The Gambling Commission's [operator data for March to August 2020](https://www.gamblingcommission.gov.uk/statistics-and-research/publication/gambling-business-data-on-gambling-during-covid-19-october-2020) (published 31 October 2020): active players and number of bets per product, from operators covering about 80% of the online market. Shown as indices, March = 100. The release carries a warning that one operator's figures were later corrected.

Real-event betting is the like-for-like comparison. The slots, casino, virtual and poker figures cover all online customers, not only sports bettors, so only their direction can be compared.

## Results

Month-end values, March = 100.

| | April | May | June | July | August |
|---|---|---|---|---|---|
| **Real-event betting, active players: reality** | **45** | **51** | **87** | **90** | **82** |
| Fixed rules only | 10 | 60 | 97 | 97 | 87 |
| AI residents | 10 | 49 | 76 | 77 | 69 |
| **Real-event bets placed: reality** | **34** | **54** | **133** | **139** | **123** |
| Fixed rules only | 8 | 48 | 174 | 247 | 114 |
| AI residents | 14 | 41 | 120 | 175 | 78 |
| **Slot spins: reality (all customers)** | **116** | **118** | **112** | **111** | **110** |
| Fixed rules only | 272 | 374 | 194 | 114 | 106 |
| AI residents | 103 | 109 | 136 | 108 | 107 |

One AI run cost $0.62 (3,997 questions).

## Where it matched

- **No rush to slots.** The fixed rules sent idle sports bettors to slots in large numbers (spins at 272 and 374). AI residents did not: their spins stayed between 103 and 136, close to the real 110 to 118. In the weeks after the suspension 83% of answers were "carry on as I am", 8% "stop and keep the money", and about 1% each for virtual sports, unfamiliar sports and casino games.
- **The shape of the return.** Betting came back in May and June in both the simulation and the record, with more bets per active player than before (the summer was packed with football).

## Where it did not

- **April.** In reality 45% of March's real-event players still placed a real-event bet in April. In the simulation 10% did, with or without AI. The world gives its people almost nothing to bet on in April; real bettors found more.
- **AI residents came back less than real bettors did** (76 to 77 against 87 to 90 in June and July). The fixed rules were closer there.
- **The April spikes in virtual betting (144) and poker (153) are missing.** Those figures include customers who are not in this cast, and the Virtual Grand National on 4 April is not in the scenario.

## The hypothesis

Half supported. The simulation agrees that there was no mass move from sports to slots. It cannot say much about "most simply stopped", because it stopped too many of them: real bettors kept betting on whatever sport was left far more than these residents did.

## What this says about the method

- Here the AI residents corrected the rules where it mattered most: a formula's guess that idle bettors would move to slots was wrong by a factor of three, and the residents did not follow it.
- Where the world itself is too thin (too little sport on offer in April), no resident can fix it. The checkup added after this run reports such gaps before anyone pays for a real run.
