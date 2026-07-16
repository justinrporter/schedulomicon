# Schedulomicon

A constraint-based optimization tool for medical resident rotation scheduling.

## Overview

Schedulomicon is a Python package that solves complex scheduling problems using constraint programming. It leverages Google OR-Tools CP-SAT solver to find optimal rotation assignments while allowing a balance multiple competing constraints and preferences.

## Features

- **Flexible constraint system**: Define hard and soft constraints with customizable weights
- **Preference handling**: Incorporate resident preferences and rankings
- **Coverage requirements**: Enforce minimum and maximum staffing levels
- **Rotation pinning**: Pre-assign specific rotations to certain residents
- **Vacation scheduling**: Handle time-off requests within the scheduling model
- **Incremental solving**: Use hints from previous solutions to improve results

## Installation

```bash
# Install from local directory
pip install -e .
```

## Usage

### Basic Example

```bash
schedulomicon solve --config config.yml --results results.csv
```

### Swap Example

Given a published schedule, find the minimal set of changes that satisfies a
new requirement, keeping blocks that already happened untouched:

```bash
schedulomicon swap \
  --config config.yml \
  --minimize-changes-from old_results.json \
  --freeze 'Block 1 or Block 2' \
  --require 'sum == 0: Resident A and Block 7 and Cardiology' \
  --results new_results.json
```

### Advanced Example

```bash
schedulomicon solve \
  --config big-preference-file.yml \
  --results results.pkl \
  --objective rank_sum_objective \
  --coverage-min minimum-coverage-per-block-and-rotation.csv \
  --coverage-max maximum-coverage-per-block-and-rotation.csv \
  --rankings rankings.csv \
  --block-resident-ranking 'Vacation' vacation-prefs.csv \
```

## Configuration

Create a YAML configuration file to define:
- Residents and their properties
- Rotations and requirements
- Time blocks
- Constraint weights and priorities
- Solver parameters

See `example_config.yml` for a template.

## Development

### Running Tests

```bash
# Run all tests
pytest schedulomicon/test_*.py

# Run specific test
pytest schedulomicon/test_solve.py::test_small_puzzle
```