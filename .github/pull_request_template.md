## What this changes

<!-- One or two sentences, and the requirement IDs it touches (for example UI-02, OPS-03). -->

## Definition of done

Tick what applies; leave a note for anything that does not.

- [ ] It matches its Figma frame in layout, titles and captions at 1366 × 768
- [ ] Every chart goes through the guard and has a Hidden state
- [ ] AppTest passes on the labelled and the unlabelled fixture
- [ ] No SQL outside `app/data/queries.py`, and no source column names outside `contracts/`
- [ ] The page logs a `page_render` event, and logs hold no secrets or row data
- [ ] CI is green, and after merge the change runs in development
