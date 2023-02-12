import datetime

from ortools.sat.python import cp_model

from . import csts


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
            assert rot in rotations, f"{rot} not in rotations"

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


def generate_model(residents, blocks, rotations, groups):

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

def add_result_as_hint(model, block_assigned, residents, blocks, rotations, hint):
    for res in residents:
        for block in blocks:
            for rot in rotations:
                if hint[res][block] == rot: 
                    model.AddHint(block_assigned[res,block,rot],1)
                else:
                    model.AddHint(block_assigned[res,block,rot],0) 

def run_optimizer(model, objective_fn, max_time_in_mins, solution_printer=None, n_processes=None):

    if n_processes is None:
        n_processes = 1

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


def run_enumerator(model, solution_printer=None):

    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = True

    solver.SearchForAllSolutions(model, solution_printer)

    return solver


def solve(
        residents, blocks, rotations, groups, cst_list, soln_printer,
        objective_fn, max_time_in_mins, n_processes, hint=None, dump_model=None
    ):

    block_assigned, model = generate_model(
        residents, blocks, rotations, groups
    )

    block_backup = generate_backup(model, residents, blocks, n_backup_blocks=2)

    for cst in cst_list:
        cst.apply(model, block_assigned, residents, blocks, rotations, block_backup)
    
    if hint is not None:
        add_result_as_hint(model, block_assigned, residents, blocks, rotations, hint)
    
    solution_printer = soln_printer(
        block_assigned,
        block_backup,
        residents,
        blocks,
        rotations,
    )

    print('Starting search:', datetime.datetime.now())

    if objective_fn:

        objective_fn = objective_fn(block_assigned)

        if dump_model is not None:
            model.ExportToFile(dump_model)

        status, solver = run_optimizer(
            model,
            objective_fn,
            n_processes=n_processes,
            solution_printer=solution_printer,
            max_time_in_mins=max_time_in_mins
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
