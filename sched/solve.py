import datetime

from ortools.sat.python import cp_model

from . import csts


def generate_model(residents, blocks, rotations, groups, rankings):

    model = cp_model.CpModel()

    # Creates shift variables.
    block_assigned = {}
    for resident in residents:
        for block in blocks:
            for rot in rotations:
                block_assigned[(resident, block, rot)] = model.NewBoolVar(
                    f'block_assigned-r{resident}-b{block}-{rot}')

    # Each resident must work some rotation each block
    for res in residents:
        for block in blocks:
            model.AddExactlyOne(
                block_assigned[(res, block, rot)] for rot in rotations)

    return block_assigned, model


def generate_backup(model, residents, blocks, n_backup_blocks):

    block_backup = {}
    for resident in residents:
        for block in blocks:
            block_backup[(resident, block)] = model.NewBoolVar(
                f'backup_assigned-r{resident}-b{block}')

    for resident in residents:
        ct = 0
        for block in blocks:
            ct += block_backup[(resident, block)]
        model.Add(ct == n_backup_blocks)

    return block_backup



def run_optimizer(model, objective_fn, solution_printer=None, n_processes=None):

    if n_processes is None:
        n_processes = 1

    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = False
    solver.parameters.num_search_workers = n_processes

    status = solver.Solve(model, solution_printer)

    status = ["UNKNOWN", "MODEL_INVALID", "FEASIBLE", "INFEASIBLE", "OPTIMAL"][status]

    return status, solver


def run_enumerator(model, solution_printer=None):

    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = True

    solver.SearchForAllSolutions(model, solution_printer)

    return solver


def solve(
        residents, blocks, rotations, rankings, groups, cst_list, soln_printer,
        objective_fn, n_processes, dump_model=None
    ):

    block_assigned, model = generate_model(
        residents, blocks, rotations, rankings, groups
    )

    block_backup = generate_backup(model, residents, blocks, n_backup_blocks=2)

    for cst in cst_list:
        cst.apply(model, block_assigned, residents, blocks, rotations, block_backup)

    solution_printer = soln_printer(
        block_assigned,
        block_backup,
        residents,
        blocks,
        rotations,
    )

    print('Starting search:', datetime.datetime.now())

    if objective_fn:

        objective_fn = objective_fn(block_assigned, rankings, residents, blocks, rotations)

        if dump_model is not None:
            model.ExportToFile(dump_model)

        status, solver = run_optimizer(
            model,
            objective_fn,
            n_processes=n_processes,
            solution_printer=solution_printer,
        )
    else:
        raise NotImplementedError("Still working on enumerator mode.")

        if dump_model is not None:
            model.ExportToFile(dump_model)

        status, solver = run_enumerator(
            model,
            solution_printer=solution_printer
        )

    return status, solver, solution_printer
