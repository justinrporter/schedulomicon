import math
import datetime
import logging

from functools import partial

from ortools.sat.python import cp_model

from . import csts, util, score
from . import model as mdl

logger = logging.getLogger(__name__)


def add_result_as_hint(model, grids, hint):

    for grid_name, grid in grids.items():
        for key, var in grid['variables'].items():
            model.AddHint(var, hint[grid_name][key])


def run_optimizer(model, objective_fn, n_processes=None, solution_printer=None,
                  max_time_in_mins=60):

    if n_processes is None:
        n_processes = util.get_parallelism()

    logger.info("Planning to use {n_processes} threads.")
    print(f"Planning to use {n_processes} threads.")

    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    if objective_fn is not None:
        model.Minimize(objective_fn)

    solver.parameters.enumerate_all_solutions = False
    solver.parameters.num_search_workers = n_processes

    if max_time_in_mins is not None:
        solver.parameters.max_time_in_seconds = max_time_in_mins * 60

    status = solver.Solve(model, solution_printer)

    status = ["UNKNOWN", "MODEL_INVALID", "FEASIBLE", "INFEASIBLE", "OPTIMAL"][status]

    return status, solver


def run_enumerator(model, solution_printer=None, objective_fn=None, score_pin=None):

    solver = cp_model.CpSolver()
    # solver.parameters.linearization_level = 2

    solver.parameters.enumerate_all_solutions = True
    status = solver.Solve(model, solution_printer)

    status = ["UNKNOWN", "MODEL_INVALID", "FEASIBLE", "INFEASIBLE", "OPTIMAL"][status]

    return status, solver


def solve(
        residents, blocks, rotations, groups_array, cst_list, soln_printer,
        cogrids, score_functions, max_time_in_mins, n_processes=None, hint=None,
        enumerate_all_solutions=False
    ):

    block_assigned, model = mdl.generate_model(
        residents, blocks, rotations, groups_array
    )

    grids = {
        'main': {
            'dimensions': {
                'residents': residents,
                'blocks': blocks,
                'rotations': rotations
            },
            'variables': block_assigned
        }
    }

    if 'backup' in cogrids and cogrids['backup']:
        grids['backup'] = {
            'dimensions': {
                'residents': residents,
                'blocks': blocks
            },
            'variables': mdl.generate_backup(
                model,
                residents,
                blocks,
                n_backup_blocks=cogrids['backup']['coverage']
            )
        }

    if 'vacation' in cogrids:
        blks = cogrids['vacation']['blocks']
        pools = cogrids['vacation']['pools']

        grids['vacation'] = {
            'dimensions': {
                'residents': residents,
                'blocks': blks,
                'pools': pools
            }
        }
        grids['vacation']['variables'] = mdl.generate_vacation(
            model,
            residents,
            rotations,
            blks
        )

    for cst in cst_list:
        cst.apply(
            model,
            block_assigned=grids['main']['variables'],
            residents=grids['main']['dimensions']['residents'],
            blocks=grids['main']['dimensions']['blocks'],
            rotations=grids['main']['dimensions']['rotations'],
            grids=grids
        )

    if hint is not None:
        add_result_as_hint(model, grids, hint)

    # instantiate the soln printer using the prototype passed in
    # eg soln_printer = partial(callback.JugScheduleSolutionPrinter,
    # scores=scs, solution_limit=1)

    solution_printer = soln_printer(grids=grids)

    start_time = datetime.datetime.now()
    print('Starting search:', start_time)

    objective_fn = None
    if score_functions:
        objective_fn = score.aggregate_score_functions(
            variables={k: grids[k]['variables'] for k in grids.keys()},
            grid_and_functions=score_functions
        )

    if enumerate_all_solutions:
        status, solver = run_enumerator(
            model=model,
            objective_fn=objective_fn,
            solution_printer=solution_printer,
        )
    else:
        status, solver = run_optimizer(
            model=model,
            n_processes=n_processes,
            objective_fn=objective_fn,
            solution_printer=solution_printer,
            max_time_in_mins=max_time_in_mins
        )


    # compare the actual runtime to the requested runtime and throw an
    # error if it doesn't kinda match
    end_time = datetime.datetime.now()
    runtime_in_minutes = (end_time - start_time).total_seconds() / 60

    return status, solver, solution_printer, model, runtime_in_minutes
