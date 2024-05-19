import math
import datetime
import logging

from ortools.sat.python import cp_model

from . import csts, util

logger = logging.getLogger(__name__)


def accumulate_score_res_block_scores(score_dict, resident_block_scores, rotation):
    for resident, block_scores in resident_block_scores.items():
        for block, score in block_scores.items():
            score_dict[(resident, block, rotation)] += score


def accumulate_score_res_rot_scores(score_dict, resident_rot_scores):

    blocks = set([b for (re, b, ro) in score_dict.keys()])

    for resident, rot_scores in resident_rot_scores.items():
        for rot, score in rot_scores.items():
            for block in blocks:
                score_dict[(resident, block, rot)] += score


def objective_from_score_dict(block_assigned, scores):

    assert set(block_assigned.keys()) == set(scores.keys())

    obj = 0

    for k in block_assigned:
        obj += block_assigned[k] * scores[k]

    return obj


def score_dict_from_df(rankings, residents, blocks, rotations, block_resident_ranking):

    for res, rnk in rankings.items():
        for rot in rnk:
            assert rot in rotations, f"Rotation '{rot}' not found in YAML specification."

    scores = {}
    for res in residents:
        for block in blocks:
            for rot in rotations:
                scores[(res, block, rot)] = 0

    accumulate_score_res_rot_scores(scores, rankings)

    if block_resident_ranking is not None:
        rotation, rot_blk_scores = block_resident_ranking
        accumulate_score_res_block_scores(scores, rot_blk_scores, rotation)

    return scores


def generate_model(residents, blocks, rotations, groups_array):
    model = cp_model.CpModel()

    # Creates shift variables.
    block_assigned = {}
    for res in residents:
        for blk in blocks:
            for rot in rotations:
                block_assigned[(res, blk, rot)] = model.NewBoolVar(
                    f'block_assigned-r{res}-b{blk}-{rot}')

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

    # the number of backup blocks per resident is n_backup_blocks
    for resident in residents:
        ct = 0
        for block in blocks:
            ct += block_backup[(resident, block)]
        model.Add(ct == n_backup_blocks)

    return block_backup


def add_result_as_hint(model, block_assigned, residents, blocks, rotations, hint):

    for res in residents:
        for block in blocks:
            for rot in rotations:
                model.AddHint(
                    block_assigned[res, block, rot],
                    hint[res][block] == rot
                )


def run_optimizer(model, objective_fn, n_processes=None, solution_printer=None, max_time_in_mins=60):

    if n_processes is None:
        n_processes = util.get_parallelism()

    logger.info("Planning to use {n_processes} threads.")
    print(f"Planning to use {n_processes} threads.")

    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = False
    solver.parameters.num_search_workers = n_processes

    if max_time_in_mins is not None:
        solver.parameters.max_time_in_seconds = max_time_in_mins * 60

    status = solver.Solve(model, solution_printer)

    status = ["UNKNOWN", "MODEL_INVALID", "FEASIBLE", "INFEASIBLE", "OPTIMAL"][status]

    return status, solver


def run_enumerator(model, objective_fn, solution_printer=None):

    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = True

    solver.SearchForAllSolutions(model, solution_printer)

    return solver


def solve(
        residents, blocks, rotations, groups_array, cst_list, soln_printer,
        objective_fn, max_time_in_mins, n_processes=None, hint=None,
    ):

    block_assigned, model = generate_model(
        residents, blocks, rotations, groups_array
    )

    block_backup = generate_backup(model, residents, blocks, n_backup_blocks=2)

    for cst in cst_list:
        cst.apply(model, block_assigned, residents, blocks, rotations, block_backup)

    if hint is not None:
        add_result_as_hint(model, block_assigned, residents, blocks, rotations, hint)

    # instantiate the soln printer using the prototype passed in
    # eg soln_printer = partial(callback.JugScheduleSolutionPrinter, scores=scs, solution_limit=1)

    solution_printer = soln_printer(
        block_assigned=block_assigned,
        block_backup=block_backup,
        residents=residents,
        blocks=blocks,
        rotations=rotations,
    )

    start_time = datetime.datetime.now()
    print('Starting search:', start_time)

    if objective_fn:

        objective_fn = objective_fn(block_assigned)

        status, solver = run_optimizer(
            model,
            objective_fn,
            n_processes,
            solution_printer=solution_printer,
            max_time_in_mins=max_time_in_mins
        )
    else:
        raise NotImplementedError("Still working on enumerator mode.")

        status, solver = run_enumerator(
            model,
            objective_fn,
            solution_printer=solution_printer
        )

    # compare the actual runtime to the requested runtime and throw an
    # error if it doesn't kinda match
    end_time = datetime.datetime.now()
    runtime_in_minutes = (end_time - start_time).total_seconds() / 60

    return status, solver, solution_printer, model, runtime_in_minutes
