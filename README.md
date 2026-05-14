# ManufacturingSim

ManufacturingSim is a Python-first walking skeleton for a desktop manufacturing simulator. It includes:

- `mfg_logic` for XML parsing, validation, and canonical models
- `mfg_des` for a headless study runner and CLI
- `mfg_viewport` for scene building and optional Qt viewport support
- `mfg_studio` for the integrated desktop shell

## Quick start

Run the headless CLI:

```bash
python3 -m mfg_sim_run tests/fixtures/sample_factory.xml --distribution
```

Export a replay JSONL alongside the headless run:

```bash
python3 -m mfg_sim_run tests/fixtures/sample_factory.xml --replay-out /tmp/likely.jsonl --replay-scenario likely
```

Run the optional desktop shell after installing PySide6:

```bash
python3 -m mfg_studio tests/fixtures/sample_factory.xml
```

The sample XML includes a sidecar registry file so it opens with a real DXF-backed machine immediately. In the viewport:

- `LMB` pans
- `Shift+LMB` orbits
- mouse wheel zooms
- double-click frames the full scene
- hover shows machine and transfer details
- the `Replay` dock can load a JSONL replay overlay produced by `mfg_sim_run`

Run the test suite with the standard library:

```bash
python3 -m unittest discover -s tests -v
```
