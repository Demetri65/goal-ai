# SMART-GoT (lean prototype)

A minimal research prototype for interactive SMART goal decomposition into workstreams.

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Start an interactive session:

```bash
smartgot run --goal "Plan a 10k charity run"
```

By default the graph is written to `./out/graph.json`. Override with `--graph`:

```bash
smartgot run --goal "Plan a 10k charity run" --graph /tmp/graph.json
```

Debug helpers:

```bash
smartgot status --graph ./out/graph.json
smartgot show root --graph ./out/graph.json
```

Use `--json` on `run`, `status`, or `show` for machine-readable output.
