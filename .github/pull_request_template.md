## What this changes

<!-- One or two sentences, and the requirement IDs it touches (for example UI-02, OPS-03). -->

## Definition of done

Tick what applies; leave a note for anything that does not.

- [ ] It follows the design it implements (name the document and section)
- [ ] For a page: usable at 1366 × 768, every chart goes through the guard and has a Hidden state, and AppTest passes on the labelled and the unlabelled fixture
- [ ] No SQL outside `app/data/queries.py`, and no source column names outside `contracts/`
- [ ] Logs hold no secrets or row data, and nothing here contains an email address
- [ ] Scripts are shellcheck-clean and templates cfn-lint-clean
- [ ] CI is green, and after merge the change runs in development
