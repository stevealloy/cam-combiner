# CAM Combiner

Assembles a directory of small, per-feature `.nc` (G-code) files into
combined, per-step output programs for a multi-unit CNC fixture run, driven
by a declarative `fixture_config.txt` and a set of parameter/feature choices.

## Running it

```
python cam_combiner_gui.py                       # interactive GUI (needs: pip install dearpygui)
python cam_combiner_cli.py --base <path-to-*-in>  # headless plan-only check
python -m pytest tests/ -q -k "not fail"          # run the test suite
```

## Documentation

See **[docs/GUIDE.md](docs/GUIDE.md)** for the full user guide, how-to
workflows, `fixture_config.txt` reference, and developer reference (module
map, planning algorithm, testing conventions).
