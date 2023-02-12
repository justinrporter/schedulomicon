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
        '--block-resident-ranking', default=None, nargs=2,
        help='A csv file specifying a score for a particular rotation for '
             'all residents for all blocks.'
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
        '--min-individual-rank', type=float, default=None
    )

    parser.add_argument(
        '--hint', default=None,
        help='A csv file with a prior solution to use as a hint to the solver'
    )

    args = parser.parse_args(argv)

    return args

# def rank_sum_objective_old(block_assigned, rankings, residents, blocks, rotations):

#     # at least one resident from `residents` should appear in rankings dict
#     assert any([res in residents for res in rankings.keys()])

#     # at least one non-empty rankings dict for one of the residents
#     assert any([rankings[res] for res in residents])

#     obj = 0
#     for res in residents:
#         for blk in blocks:
#             for rot in rotations:
#                 if res in rankings and rot in rankings[res]:
#                     # print('rankings', res, rot, rankings[res][rot], type(rankings[res][rot]))
#                     obj += int(rankings[res][rot]) * block_assigned[res, blk, rot]
#                 else:
#                     obj += 0

#     return obj

# def rank_sum_objective_new(block_assigned, rankings, residents, blocks, rotations):

#     # at least one resident from `residents` should appear in rankings dict
#     assert any([res in residents for res in rankings.keys()])

#     # at least one non-empty rankings dict for one of the residents
#     assert any([rankings[res] for res in residents])

#     obj = 0
#     for resident, rnk in rankings.items():
#         for rotation, score in rnk.items():
#             for block in blocks:
#                 obj += score * block_assigned[(resident, block, rotation)]

#     return obj


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


def main(argv):

    args = parse_args(argv)

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    residents, blocks, rotations, groups = process_config(config)

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

    if args.hint is not None:
        hint = pd.read_csv(args.hint, header=0, index_col=0, comment='#')
    else:
        hint = None

    print("Residents:", len(residents))
    print("Blocks:", len(blocks))
    print("Rotations:", len(rotations))

    scores = io.score_dict_from_df(
        io.rankings_from_csv(args.rankings),
        residents, blocks, rotations,
        (block_resident_ranking[0],
         pd.read_csv(block_resident_ranking[1],
                     header=0, index_col=0, comment='#').T.to_dict())
    )
    
    objective_fn = partial(
        objective_from_score_dict,
        scores=scores
    )

    status, solver, solution_printer = solve.solve(
        residents, blocks, rotations, groups, cst_list,
        soln_printer=partial(
            io.BlockSchedulePartialSolutionPrinter,
            scores=scores,
            outfile=args.results,
            solution_limit=args.n_solutions,
        ),
        objective_fn=objective_fn,
        dump_model=args.dump_model,
        n_processes=args.n_processes,
        hint=hint
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
