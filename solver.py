import math
import argparse
import csv

import yaml

from ortools.sat.python import cp_model

from sched import csts, io

def parse_args():
    parser = argparse.ArgumentParser(description='Process some integers.')

    parser.add_argument(
        '--config', required=True,
        help='A YAML file specifying the schedule to solve for.'
    )

    parser.add_argument(
        '--results', required=True,
        help='The place to write the schedule(s) as a csv.'
    )

    parser.add_argument(
        '-p', '--n_processes', default=1, type=int,
        help='The number of search workers for OR-Tools to use.'
    )

    parser.add_argument(
        '-n', '--n_solutions', default=1, type=int,
        help='The number of solutions to search for.'
    )

    parser.add_argument(
        '--objective', action='store', default='rank_sum_objective',
        help='subject the results to optimization to the objective'
    )

    parser.add_argument(
        '--min-individual-rank', type=int, default=None
    )

    args = parser.parse_args()

    return args

def handle_count_specification(count_config, n_items):

    if 'min' in count_config and 'max' in count_config:
        rmin = expand_to_length_if_needed(count_config['min'], n_items)
        rmax = expand_to_length_if_needed(count_config['max'], n_items)
    else:
        rmin = expand_to_length_if_needed(count_config[0], n_items)
        rmax = expand_to_length_if_needed(count_config[1], n_items)

    return rmin, rmax

def expand_to_length_if_needed(var, length):

    if not hasattr(var, '__len__'):
        return [var]*length
    else:
        assert len(var) == length
        return var


def resolve_group(group, rotation_config):

    rots = [
        r for r, params in rotation_config.items()
        if params and group in params.get('groups', [])
    ]

    return rots


def add_group_count_per_resident_constraint(
        model, block_assigned, residents, blocks,
        rotations, n_min, n_max):

    for res in residents:
        ct = 0

        for blk in blocks:
            for rot in rotations:
                ct += block_assigned[(res, blk, rot)]

        model.Add(ct >= n_min)
        model.Add(ct <= n_max)


def generate_model(residents, blocks, rotations, groups, rankings, constraints):

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

    for cst in constraints:
        cst.apply(model, block_assigned, residents, blocks, rotations)

    return block_assigned, model


def rank_sum_objective(block_assigned, rankings, residents, blocks, rotations):

    obj = 0
    for res in residents:
        for blk in blocks:
            for rot in rotations:
                if res in rankings and rot in rankings[res]:
                    obj += rankings[res][rot] * block_assigned[res, blk, rot]

    return obj


def process_config(config):

    residents = list(config['residents'].keys())
    blocks = list(config['blocks'].keys())
    rotations = list(config['rotations'].keys())

    groups = []
    for rot, params in config['rotations'].items():
        if not params:
            continue
        groups.extend(params.get('groups', []))
    groups = list(set(groups))

    rankings = {}

    for res in residents:
        rank_dicts = config['residents'][res].get('rankings', {})

        rankings[res] = {}
        for group, ranking in rank_dicts.items():
            assert group in groups

            for rank, rot in enumerate(ranking):
                assert rot not in rankings[res], "(%s, %s)" % (res, rot)
                rankings[res][rot] = rank

    return residents, blocks, rotations, rankings, groups


def generate_resident_constraints(config):

    cst_list = []

    for res, params in config['residents'].items():
        if not params:
            continue

        if 'pin_rotation' in params:
            for pinned_rotation, pinned_blocks in params['pin_rotation'].items():
                cst_list.append(
                    csts.PinnedRotationConstraint(res, pinned_blocks, pinned_rotation)
                )

    return cst_list


def generate_rotation_constraints(config):

    constraints = []

    for rotation, params in config['rotations'].items():

        if not params:
            continue
        if 'coverage' in params:
            rmin, rmax = handle_count_specification(params['coverage'], len(config['blocks']))
            constraints.append(csts.RotationCoverageConstraint(rotation, rmin, rmax))
        if 'must_be_followed_by' in params:
            following_rotations = []
            for key in params['must_be_followed_by']:
                if key in config['rotations']:
                    following_rotations.append(key)
                else:
                    following_rotations.extend(
                        resolve_group(key, config['rotations']))

            constraints.append(csts.MustBeFollowedByRotationConstraint(
                rotation=rotation, following_rotations=following_rotations
            ))

        if 'prerequisite' in params:
            constraints.append(csts.PrerequisiteRotationConstraint(
                rotation=rotation, prerequisites=params['prerequisite']
            ))

        if params.get('always_paired', False):
            constraints.append(
                csts.AlwaysPairedRotationConstraint(rotation)
            )

        if 'rot_count' in params:
            rmin, rmax = handle_count_specification(
                params['rot_count'], len(config['residents']))
            constraints.append(
                csts.RotationCountConstraint(rotation, rmin, rmax)
            )

        if 'not_rot_count' in params:
            ct = params['not_rot_count']
            constraints.append(
                csts.RotationCountNotConstraint(rotation, ct)
            )

    return constraints


def generate_block_constraints(config):

    constraints = []

    for block, params in config['blocks'].items():
        if not params:
            continue

        for key in params:
            if key in config['rotations']:
                bval = params[key]
                if not bval:
                    constraints.append(
                        BanRotationBlockConstraint(block, rotation=key)
                    )
                else:
                    print(f"In {block}, {key}: Yes has no effect")
            if key in config['groups']:
                grp = resolve_group(key, config['rotations'])
                bval = params[key]

                if not bval:
                    for grp_memb in grp:
                        constraints.append(
                            BanRotationBlockConstraint(block, rotation=grp_memb)
                        )
                else:
                    print(f"In {block}, {key}: Yes has no effect")

    return constraints


def generate_constraints_from_configs(config):

    constraints = []

    constraints.extend(generate_rotation_constraints(config))

    constraints.extend(generate_resident_constraints(config))

    for cst in config['group_constraints']:
        if cst['kind'] == 'group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResident(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1])
            )

    return constraints


def run_optimizer(model, objective_fn, solution_printer=None,  n_processes=None):

    if n_processes is None:
        n_processes = 1

    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = False
    solver.parameters.num_search_workers = n_processes

    # solver.parameters.enumerate_all_solutions = True

    solver.Solve(model, solution_printer)
    # solver.SearchForAllSolutions(model, solution_printer)

    return solver


def run_enumerator(model, solution_printer=None):

    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    model.Minimize(objective_fn)
    solver.parameters.enumerate_all_solutions = True

    solver.SearchForAllSolutions(model, solution_printer)

    return solver


def main():

    args = parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    residents, blocks, rotations, rankings, groups = process_config(config)
    cst_list = generate_constraints_from_configs(config)

    if args.min_individual_rank is not None:
        cst_list.append(
            csts.MinIndividualRankConstraint(rankings, args.min_individual_rank)
        )

    block_assigned, model = generate_model(
        residents, blocks, rotations, rankings, groups, cst_list
    )

    solution_printer = io.BlockSchedulePartialSolutionPrinter(
        block_assigned,
        residents,
        blocks,
        rotations,
        outfile=args.results
    )

    if args.objective == 'rank_sum_objective':
        objective_fn = rank_sum_objective(block_assigned, rankings, residents, blocks, rotations)

        solver = run_optimizer(
            model,
            objective_fn,
            solution_printer=solution_printer,
            n_processes=args.n_processes
        )
    else:
        raise NotImplementedError("Still working on enumerator mode.")
        solver = run_enumerator(
            model,
            solution_printer=solution_printer
        )

    # Statistics.
    # print('\nStatistics')
    # print('  - conflicts      : %i' % solver.NumConflicts())
    # print('  - branches       : %i' % solver.NumBranches())
    print('  - wall time      : %f s' % solver.WallTime())
    print('  - solutions found: %i' % solution_printer.solution_count())
    # print('  - objective value: %i' % solver.ObjectiveValue())


if __name__ == '__main__':
    main()
