# Changelog

## 0.3.2

- Describe a custom event at a saved point in a society or life run. Apply it using existing parameters, or rebuild the branch model and validate it against the saved state before continuing with the same history.

## 0.3.1 (2026-11-26)

- In life worlds, play one path, pick a point on its timeline, and branch from the same history. Choose a different direction in worlds that support it, or introduce an event.
- View every future on the same outcome chart, using the same colours as the world lines. Select a future to highlight it and open its details at the selected point.

## 0.3.0 (2026-11-26)

- **A second mode: one person's crossroads.** The top page asks what you would like to do. Besides watching a society, you can now say where you stand and what you are weighing ("should I change jobs?") and look at futures that could be. Same engine, different way in and different way of looking.
- **An interview first.** AI asks up to six questions about you (what matters, what you fear losing, money and other limits, the people involved, what you tend to regret), then writes the person, the paths and the scenario for you to read and change. Your story is not sent to a web search.
- **A world around one person.** The protagonist is taken from the interview word for word; the cast is the dozen or more people around them, who decide things that touch the protagonist and keep their own regard for them. Such a world must have a "path" to choose at the start, measures of satisfaction, regret and regard, and a deck of chance events; the tool checks that, and that the protagonist is really asked on every path.
- **Several futures at once.** One button runs every path a few times over, with chance events on. Every path gets the same strokes of luck, so future 2 of one path and future 2 of another meet the same outside events.
- **The crossroads page.** Futures side by side by path: how satisfaction moved, where it ended, what the person decided and what struck from outside, their last words. Any future opens in the ordinary run page.
- **Talk with a future self.** Each future's protagonist can be asked how it went; they answer from the life they lived in that future (the path, what happened, what they decided, what others said).
- **A report across all futures**: where each path tended to lead, where futures parted, what stayed the same whatever was chosen, the shape regret took, how others came to see them, and questions worth asking a future self. Saves as Markdown.
- A fifth sample world for this mode, built by the tool from a made-up person: *Eight years at the kitchen table*.

## 0.2.5 (2026-11-26)

- **A fuller report that is easier to read.** Numbers come from the program and words from AI. The report now covers the whole experiment: the main figures (start, highest, lowest, end), what the residents answered, the comparison with recorded figures, and the other runs of the same world side by side. Each section is short on purpose, borrowing from [i-have-adhd](https://github.com/ayghri/i-have-adhd): the answer first, lists of at most five, no preamble or recap, and one concrete next step as the last line. It is written in the language on screen; with no AI the tables are still laid out, in every language.
- **Save as Markdown.** The report, with the questions put to the analyst, downloads as one `.md` file.
- The report view renders numbered lists, quotations and rules.

## 0.2.4 (2026-11-26)

- **Data: take out and bring in.** The header has a Data menu. Chosen worlds and runs are saved as one SQLite file with the same tables (gzipped by default; a branch brings the run it came from), and such a file can be brought into another database. Nothing is replaced on the way in: runs get new ids, a world is matched by its slug or added under a free name, and a world that comes in runs only in an isolated sandbox.
- **A backup folder for machines that do not keep their files** (`HAKONIWA_BACKUP_DIR`, `HAKONIWA_BACKUP_MINUTES`). A whole compressed copy of the database is written there when something has just been completed (a run comes to rest, a world is built, a file is brought in), every few minutes when something changed, and once more on shutdown; a machine that finds no database starts from the copy. Meant for a Cloud Storage bucket mounted on Cloud Run; the live database stays off the mount.
- `docs/CLOUD_RUN.md` and `docs/CLOUD_RUN.ja.md`: deploying to Cloud Run behind Identity-Aware Proxy, keeping the data in a bucket, how much CPU and memory to give it (measured), and what it costs against the free tier (the guide scales to zero when idle).
- `docs/DESIGN.md`: the design notes in English. Both language versions now describe the current design and include the colour palette and the rules for using it.
- The header shows the version after the name.
- The Japanese README is now `README.ja.md` (it was `README.jp.md`): `ja` is the language code, like the other Japanese documents.

## 0.2.3 (2026-11-26)

- **A world has its page from the moment building starts.** It gets its id at once, so several worlds can be built side by side. The top page lists the ones being built; each one's page is the building site until it is ready, and the same address then shows the finished world. A build that fails stays as a page that says what went wrong, with the scenario ready to change and try again.
- The warning before leaving the page no longer appears while a world is being built: building goes on without the page, and nothing is lost. It still appears while AI is drafting a scenario, preparing its questions, or turning your thoughts on a world into a new theme.
- Chance events are on by default in the viewer, except in a world that replays a recorded event (where they would add things that did not happen). The start card says when they are on.

## 0.2.2 (2026-11-26)

- **Chance events.** A world carries a deck of things that may simply happen, to the world or in some people's own lives. The seed decides which happen and when; forks meet the same events. The designer writes the deck when it builds a world, and AI can write one for an existing world.
- **Checkup before the first run.** Free rehearsals with every answer tried on everyone in turn: answers that change nothing, people never asked, figures that never move, recorded figures in another unit. Runs while a world is built (defects go back to the designer) and on demand from a world's page.
- **The automaton as a state diagram.** For a state with a few values, a diagram under the board shows how many people are in each state and how many have moved between them, up to the tick on screen.
- **Against the record.** Where a world carries recorded figures, each run on screen gets its mean gap, correlation and peak timing in a small table.
- A fourth check against reality, built by the tool: sports betting in Great Britain when sport stopped in 2020 (`docs/reports/uk-betting-2020.md`).
- The feed keeps world news, interventions and chance events of long runs (they used to fall off behind thousands of lines of speech).

## 0.2.1 (2026-11-26)

- **Take a world further.** On a world's page, write what you think of it and where you want it to go. AI turns that into the scenario for a new world, shows it on the top page for you to change, and the new world remembers which one it grew out of.
- **Questions before building.** When a scenario leaves open something that would change the world (who is followed, what counts as the outcome, what to compare), the tool asks first: up to four questions, each with options and room for your own words. Skipping is one click; the answers go to the designer as decisions.
- **Step in on one resident.** Pick a person on the board at any tick, say something to them or decide for them, and a fork runs on from there. Told something, they are asked again and answer for themselves; the words stay with them. The original run is untouched.
- While a world is being created the top page turns into a building site: four steps (survey the land, lay down the rules, trial run, people move in) and the pixel-art town put together piece by piece. The raw log is one click away.
- Questions can be put to the analyst under the report: answers come from the run's data (every metric at every tick, the tally of choices, what residents thought), say so when the data cannot answer, and name the what-if event that would.

## 0.2.0 (2026-11-26)

- The designer builds the whole world: the rules (an automaton), the parameters and a recipe for the cast. The tool draws the individuals from the recipe, and the designer writes their life sketches.
- Real data can be pasted when creating a world. It is kept in the world as a test and drawn on the charts beside the simulated figures.
- Residents can be played through the OpenAI Decisions API ("AI, decisions only"): probabilities instead of text, cheaper, no speech. Not suited to free numbers.
- A model role for drafting scenarios. Defaults: world building `gpt-6.2-astra`, drafting and reports `gpt-6.2-sol`, residents `gpt-6-luna`.
- Sample worlds are now three checks against real events: toilet paper in Japan (2020), the fuel rush in Great Britain (2021) and US air travel (2020). The last two were built by the tool. Reports in `docs/reports/`.
- The earlier samples (Chuo Line, Izu Oshima, presales department) were removed.
- `python -m hakoniwa export <slug> <dir>` saves a world from the database as files.
- Residents' instructions were rewritten after the checks: most people change nothing on most days, and the world's own formula is the likely answer unless this person has a reason to differ. Closer to reality on the fuel and air-travel checks, unchanged on the toilet-paper one.
- Two optional corrections under "More settings", off by default: ask only those a decision model judges would stop to think, and let only a share of residents act on a change of mind (what they meant to do is kept and shown).
- The first option of a question is now the person's habit ("carry on exactly as before"); a number's `default` is its value now.
- The run page shows the cast as a board: one square per resident, coloured by their last answer, with a replay button. The map of places is one click away and now says what its circles and lines mean.
- The board can be coloured by the automaton's own state for each person (read from the stored snapshot of any run), picked from a menu.
- Interviews use the person's own description, earlier thoughts and words, and a brief that asks for conversation instead of a status report.
- Switching language keeps what was chosen on the page (runs to compare, the tick shown, tabs, settings, typed text, scroll position).
- `README.jp.md`: a Japanese README with Japanese screenshots.
- A sandbox outage while building is retried instead of being sent to the designer as a model error. The trial limit on questions per tick follows the size of the cast.
- Viewer: new top page (create a world first, plain list of worlds), history page, world lines (how runs branched), a fork dialog, automatic cost estimate, keyboard shortcuts.
- Draft a scenario from a rough idea with AI.
- Choose the model and effort for world design, residents and reports in the viewer; choices are saved and override `.env`.
- Every resident gets a name of its own when several share one description.
- A warning before leaving the page while AI is creating a world or drafting a scenario.
- Pixel-art icon and animated scene, built from blocks in the ten brand colours (`tools/make_icon.py`).
- README in an open-source layout; MIT license.
- Design notes for the next step, a world where residents live on their own: `docs/DESIGN-life.ja.md`.

## 0.1.0 (2026-11-25)

- Run engine, SQLite store with snapshots and forks, sandboxes for world models, OpenAI-compatible client.
- World designer: scenario text to parameters, residents and a math model, tested in a sandbox.
- Cost estimate before a run, written reports, interviews.
- Three sample worlds: the Chuo Line stoppage, Izu Oshima, a presales department.
