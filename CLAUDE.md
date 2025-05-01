# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
- Run tests: `pytest schedulomicon/test_*.py`
- Run single test: `pytest schedulomicon/test_solve.py::test_small_puzzle`
- Run solver: `python -m schedulomicon.solver --config config.yml --results results.csv`

## Code Style
- **Imports**: Standard Python imports at top, grouped by stdlib → third-party → local
- **Type annotations**: No strict type annotations used in this codebase
- **Naming**: snake_case for variables/functions, CamelCase for classes
- **Error handling**: Custom exceptions defined in exceptions.py
- **Frameworks**: Uses Google OR-Tools CP-SAT solver for constraint programming
- **Testing**: Uses pytest for constraint verification
- **Documentation**: Limited docstrings, write clear code

This package provides constraint-based scheduling optimization primarily for medical resident rotation assignments.