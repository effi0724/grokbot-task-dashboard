# Example data

Everything in this directory is synthetic. Bot names (Coordinator, Researcher, Coder, Ops, Writer), task titles, and durations were chosen so the dashboard and the calibration math have something to show. They are not a record of real work.

- `sample-state/` is the on-disk shape `st` writes under `$ST_ROOT/bots/`.
- `example-snapshot.json` is the payload `st push` would POST, including the `accuracy` block.
- The same snapshot is served by the static page as `site/public/example-state.json` when you open `/?example=1`.

Regenerate both from the CLI library:

```bash
python3 scripts/build_example_state.py
```
