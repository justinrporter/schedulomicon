import sys
import datetime
import math
import argparse
import yaml

from functools import partial

import pandas as pd
import numpy as np

from sched import csts, io, solve, callback

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
        '--score-list', nargs=2, default=None,
        append=True,
        metavar=('GRID', 'CSV_FILE'),
        help='A csv that specifies a score for particular combinations of '
             'variables for [GRID].'
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
        '--vacation',
        help='Where to write a vacation csv. Produces an error if there '
        'is no vacation cogrid.'
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

    residents, blocks, rotations, cogrids_avail, groups_array = io.process_config(config)

    cst_list = io.generate_constraints_from_configs(
        config, groups_array
    )

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
            csts.MinIndividualScoreConstraint(rankings, args.min_individual_rank)
        )

    cst_list.extend(
        io.generate_backup_constraints(config)
    )

    if args.hint is not None:
        hint = pd.read_csv(args.hint, header=0, index_col=0, comment='#')\
            .replace(r'\+', '', regex=True)
    else:
        hint = None

    print("Residents:", len(residents))
    print("Blocks:", len(blocks))
    print("Rotations:", len(rotations))

    if args.block_resident_ranking:
        block_resident_ranking = (
            args.block_resident_ranking[0],
            pd.read_csv(args.block_resident_ranking[1],
                        header=0, index_col=0, comment='#').T.to_dict())
    else:
        block_resident_ranking = None

    score_functions = []

    if args.rankings:
        scores = solve.score_dict_from_df(
            io.rankings_from_csv(args.rankings),
            residents, blocks, rotations, block_resident_ranking
        )
        score_functions.append(
            ('main', partial(score.objective_from_score_dict,
                             scores=scores)
            )
        )
    else:
        scores = None
        objective_fn = lambda x: 0

    for grid, score_file in args.score_list:
        df = pd.read_csv(score_file)
        sc_d = {
            i: row[0] for i, row in
            df.groupby([df.columns[0], df.columns[1], df.columns[2]]).sum().iterrows()
        }

        score_functions.append(
            (grid, partial(score.objective_from_score_dict, scores=sc_d))
        )

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents, blocks, rotations, groups_array, cst_list,
        soln_printer=partial(
            callback.JugScheduleSolutionPrinter,
            scores=scores,
            solution_limit=args.n_solutions,
        ),
        cogrids={c: config[c] for c in cogrids_avail},
        score_functions=score_functions,
        n_processes=args.n_processes,
        hint=hint,
        max_time_in_mins=None
    )

    # Statistics.
    print("status:", status)
    print('\nStatistics')
    print('  - conflicts      : %i' % solver.NumConflicts())
    print('  - branches       : %i' % solver.NumBranches())
    print('  - wall time      : %f s' % solver.WallTime())
    print('  - solutions found: %i' % solution_printer.solution_count())
    print('  - objective value: %i' % solver.ObjectiveValue())

    if status in ['OPTIMAL', 'FEASIBLE']:
        with open(args.results, 'w') as f:
            solution_printer._solutions[-1].to_csv(f)
        print("Best solution at ", args.results)

        if args.vacation:
            with open(args.vacation, 'w') as f:
                solution_printer._vacations[-1].to_csv(f)
            print("Vacation solution at ", args.vacation)

        return 1
    else:
        print("No best solution.")

        return 0


if __name__ == '__main__':
    main(sys.argv[1:])
