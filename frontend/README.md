# MobiMix frontend

React + Vite + TypeScript. Setup and run instructions are in the [root README](../README.md).

```powershell
npm install
npm run dev      # http://localhost:5173, proxies /api to the backend
npm run build    # type-check + production build
npm run lint
npm test         # pure logic only: questionnaire mapping, number formatting, results view model
```

## Layout

```text
src/form/       questionnaire logic (pure): state, rules, mapping to the profile
src/steps/      one component per questionnaire screen
src/results/    the results screen
  format.ts     how numbers are shown (Italian, rounded to what an estimate supports)
  view.ts       the analysis -> what the screen shows (labels, cards, chart rows); pure, tested
  Results.tsx   the layout: answer, today, alternatives, comparison, notes
  Charts.tsx    the comparison: three bar charts and the same numbers as a table
  scenario.ts   the what-if controls: bounds, wording, what is sent, change of answer (pure, tested)
  ScenarioPanel.tsx  the "E se...?" panel with its sliders
  results.css
src/api/        hand-written types of the API and the client
```

The screen reads `AnalysisResult` (`POST /api/analyze`). The logic lives in `view.ts` and the
components only lay it out, so it can be tested without a browser. The tests of the results read the
real analysis of each demo household, a JSON snapshot regenerated with
`python -m app.data.export_demo_fixture` from `backend/` (a backend test fails when it is stale).

## Development shortcuts (only with `npm run dev`)

- `/?demo=urban_single` loads a demo household and goes straight to its results
  (`urban_single`, `urban_couple`, `family_two_cars`, `peripheral_family`, `car_free_household`);
- `/?theme=light` or `/?theme=dark` overrides the system colour scheme;
- `&whatif=fuelPct:30,remoteDays:2` starts the results with those what-if assumptions (keys as in `scenario.ts`);
- a selector in the questionnaire loads a demo household into the form.

## Design

A consumer product, designed for the computer first (CLAUDE.md section 25): the answer on top, large
type, one blue accent, warm neutral surfaces; it adapts to a phone but is not designed around one.
Colours are tokens in `src/index.css`, with a dark scheme that follows the system. The charts follow the
data-visualisation rules: thin bars from a baseline, the current setup in grey and the alternatives in
one hue, direct labels, a tooltip on hover and focus, and a table with the same numbers.
