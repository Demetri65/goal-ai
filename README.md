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

By default the graph is written to `./graph.json`. Override with `--graph`:

```bash
smartgot run --goal "Plan a 10k charity run" --graph /tmp/graph.json
```

The session will:
- baseline the root goal via Q&A,
- decompose into ~7±2 workstreams,
- baseline each workstream,
- update SMART fields as you answer.
