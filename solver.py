import sys
import datetime
import math
import argparse
import yaml

from functools import partial

import pandas as pd
import numpy as np

from sched import csts, io, solve

def parse_args(argv):
    parser = argparse.ArgumentParser(description='Process some integers.')

    parser.add_argument(
        '--config', required=True,
        help='A YAML file specifying the schedule to solve for.'
    )

    parser.add_argument(
        '--coverage-min', default=None,
        help="A CSV file specifying coverage minima for each block " +\
            "(column) and rotation (row)."
    )
    parser.add_argument(
        '--coverage-max', default=None,
        help="A CSV file specifying coverage maxima for each block " +\
            "(column) and rotation (row)."
    )
    parser.add_argument(
        '--rotation-pins', default=None,
        help='A csv file specifying rotations to pin'
    )
    parser.add_argument(
        '--rankings', default=None,
        help='A csv file with rankings of each resident for each rotation'
    )

    parser.add_argument(
        '--results', required=True,
        help='The place to write the schedule(s) as a csv.'
    )

    parser.add_argument(
        '--dump-model', default=None,
        help='A file to dump the final model to (immediatly prior to solving).'
    )

    parser.add_argument(
        '-p', '--n_processes', default=1, type=int,
        help='The number of search workers for OR-Tools to use.'
    )

    parser.add_argument(
        '-n', '--n_solutions', default=Ellipsis, type=int,
        help='The number of solutions to search for.'
    )

    parser.add_argument(
        '--objective', action='store', default='rank_sum_objective',
        help='subject the results to optimization to the objective'
    )

    parser.add_argument(
        '--min-individual-rank', type=int, default=None
    )

    args = parser.parse_args(argv)

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

def rank_sum_objective_old(block_assigned, rankings, residents, blocks, rotations):

    # at least one resident from `residents` should appear in rankings dict
    assert any([res in residents for res in rankings.keys()])

    # at least one non-empty rankings dict for one of the residents
    assert any([rankings[res] for res in residents])

    obj = 0
    for res in residents:
        for blk in blocks:
            for rot in rotations:
                if res in rankings and rot in rankings[res]:
                    # print('rankings', res, rot, rankings[res][rot], type(rankings[res][rot]))
                    obj += int(rankings[res][rot]) * block_assigned[res, blk, rot]
                else:
                    obj += 0

    return obj

def rank_sum_objective_new(block_assigned, rankings, residents, blocks, rotations):

    # at least one resident from `residents` should appear in rankings dict
    assert any([res in residents for res in rankings.keys()])

    # at least one non-empty rankings dict for one of the residents
    assert any([rankings[res] for res in residents])

    obj = 0
    for resident, rnk in rankings.items():
        for rotation, score in rnk.items():
            for block in blocks:
                obj += score * block_assigned[(resident, block, rotation)]

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
            constraints.append(csts.RotationCoverageConstraint(rotation, rmin=rmin, rmax=rmax))
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

        if params.get('cool_down', 0) != 0:
            if params.get('always_paired', False):
                constraints.append(
                    csts.CoolDownConstraint(rotation, params.get('cool_down') + 1, [0,2])
                )
            else: 
                constraints.append(
                    csts.CoolDownConstraint(rotation, params.get('cool_down') + 1, [0,1], suppress_for = "Yi, Yangtian")
                )

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


def generate_backup_constraints(
    config, n_residents_needed=2, backup_group_name='backup_eligible'):

    constraints = []

    for block, blk_params in config['blocks'].items():
        if blk_params.get('backup_required', True):
            constraints.append(
                csts.BackupRequiredOnBlockBackupConstraint(
                    block=block,
                    n_residents_needed=n_residents_needed
                )
            )

    for rotation, rot_params in config['rotations'].items():
        if 'backup_count' in rot_params:
            ct = int(rot_params['backup_count'])
            constraints.append(
                csts.RotationBackupCountConstraint(rotation, ct)
            )

    backup_eligible = {}
    for rotation, rot_params in config['rotations'].items():
        backup_eligible[rotation] = backup_group_name in rot_params.get('groups', {})
    constraints.append(
        csts.BackupEligibleBlocksBackupConstraint(backup_eligible)
    )

    return constraints


def generate_constraints_from_configs(config):

    constraints = []

    constraints.extend(generate_rotation_constraints(config))

    constraints.extend(generate_resident_constraints(config))

    for cst in config['group_constraints']:
        if cst['kind'] == 'all_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1], window_size = len(config['blocks']))
            )
        if cst['kind'] == 'window_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1], window_size = cst['window_size'])
            )

        if cst['kind'] == 'time_to_first':
            constraints.append(
                csts.TimeToFirstConstraint(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']), 
                    window_size = cst['window_size'])
            )
    return constraints


def main(argv):

    args = parse_args(argv)

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    residents, blocks, rotations, rankings, groups = process_config(config)

    if args.rankings is not None:
        for k, v in rankings.items():
            assert not v
        rankings = io.rankings_from_csv(args.rankings)

        for res, rnk in rankings.items():
            for rot in rnk:
                assert rot in rotations, f"{rot} not in rotations"

    cst_list = generate_constraints_from_configs(config)

    if args.coverage_min:
        cst_list.extend(
            io.coverage_constraints_from_csv(args.coverage_min, 'rmin')
        )
    if args.coverage_max:
        cst_list.extend(
            io.coverage_constraints_from_csv(args.coverage_max, 'rmax')
        )
    if args.rotation_pins:
        cst_list.extend(
            io.pin_constraints_from_csv(args.rotation_pins)
        )

    if args.min_individual_rank is not None:
        cst_list.append(
            csts.MinIndividualRankConstraint(rankings, args.min_individual_rank)
        )

    for c in generate_backup_constraints(config):
        cst_list.append(c)

    print("Residents:", len(residents))
    print("Blocks:", len(blocks))
    print("Rotations:", len(rotations))

    solver, solution_printer = solve.solve(
        residents, blocks, rotations, rankings, groups, cst_list,
        soln_printer=partial(
            io.BlockSchedulePartialSolutionPrinter,
            rankings=rankings,
            outfile=args.results,
            solution_limit=args.n_solutions
        ),
        objective_fn=(
            rank_sum_objective_new if args.objective == 'rank_sum_objective'
            else None
        ),
        dump_model=args.dump_model,
        n_processes=args.n_processes
    )

    # Statistics.
    print("status:", status)
    print('\nStatistics')
    print('  - conflicts      : %i' % solver.NumConflicts())
    print('  - branches       : %i' % solver.NumBranches())
    print('  - wall time      : %f s' % solver.WallTime())
    print('  - solutions found: %i' % solution_printer.solution_count())
    print('  - objective value: %i' % solver.ObjectiveValue())
    print("Best solution at ", args.results % solution_printer.solution_count())


if __name__ == '__main__':
    main(sys.argv[1:])
