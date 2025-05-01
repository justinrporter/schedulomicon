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
schedulomicon --config config.yml --results results.csv
```

### Advanced Example

```bash
schedulomicon \
  --config big-preference-file.yml \
  --results results.pkl \
  --objective rank_sum_objective \
  --coverage-min minimum-coverage-per-block-and-rotation.csv \
  --coverage-max maximum-coverage-per-block-and-rotation.csv \
  --rotation-pins rotation-pin.csv \
  --rankings rankings.csv \
  --block-resident-ranking 'Vacation' vacation-prefs.csv \
  --hint previous-results.pkl
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