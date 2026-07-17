import sys
import datetime
import math
import argparse
import yaml
import json

from functools import partial

import pandas as pd
import numpy as np

from . import csts, io, solve, callback, score, swap

def add_common_args(parser):

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
        '--score-list', nargs=2, default=[], action='append',
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
        help='The place to write the solution. Format is chosen by '
             'extension: .csv (human-readable table), .pkl/.pickle (pickled '
             'solution dict), or .json (sparse machine-readable format, '
             'accepted by --hint).'
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
        '-n', '--n_solutions', '--n-solutions', default=Ellipsis, type=int,
        help='solve: the number of solutions to search for before stopping. '
             'swap: the number of distinct proposals to produce (default 1).'
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
        help='A .pkl or .json file with a prior solution to use as a hint '
             'to the solver'
    )

    parser.add_argument(
        '--require', action='append', default=[],
        metavar='SUM_EXPR: SELECTOR',
        help="An extra constraint of the form 'sum <op> N: <selector>', "
             "e.g. 'sum == 1: Resident A and Block 7 and Cardiology'. "
             "May be given multiple times."
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='schedulomicon')

    subparsers = parser.add_subparsers(dest='command', required=True)

    solve_parser = subparsers.add_parser(
        'solve', help='Solve a schedule from a YAML config.')
    add_common_args(solve_parser)

    swap_parser = subparsers.add_parser(
        'swap', help='Re-solve a schedule, staying as close as possible to '
                     'a prior solution.')
    add_common_args(swap_parser)
    swap_parser.add_argument(
        '--minimize-changes-from', required=True,
        help='A .pkl or .json prior solution; the solver minimizes the '
             'number of changes from this schedule.'
    )
    swap_parser.add_argument(
        '--freeze', action='append', default=[], metavar='SELECTOR',
        help="A selector expression (same DSL as --require) naming a region "
             "of the schedule that must be identical to the old solution, "
             "e.g. 'Block 1 or Block 2'. May be given multiple times."
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


def build_score_functions(residents, blocks, rotations, rankings=None,
                          score_list=(), block_resident_ranking=None,
                          min_individual_rank=None):
    """Wire rankings/score CSVs into score functions and extra constraints.

    Args:
        residents, blocks, rotations: The main grid dimensions.
        rankings: Optional path to a rankings CSV (resident x rotation).
        score_list: Iterable of (grid_name, csv_path) pairs, as collected by
            the --score-list flag.
        block_resident_ranking: Optional (rotation, csv_path) pair, as
            collected by the --block-resident-ranking flag.
        min_individual_rank: Optional per-resident score bound; produces a
            MinIndividualScoreConstraint (requires rankings).

    Returns:
        (score_functions, scores, extra_csts): score_functions is a list of
        (grid_name, function) pairs for solve.solve; scores is the main-grid
        score dict (or None without rankings); extra_csts is a list of
        constraints to append to the model's constraint list.
    """

    if block_resident_ranking:
        block_resident_ranking = (
            block_resident_ranking[0],
            pd.read_csv(block_resident_ranking[1],
                        header=0, index_col=0, comment='#').T.to_dict())
    else:
        block_resident_ranking = None

    score_functions = []
    extra_csts = []

    if rankings:
        scores = score.score_dict_from_df(
            io.rankings_from_csv(rankings),
            residents, blocks, rotations, block_resident_ranking
        )
        score_functions.append(
            ('main', partial(score.objective_from_score_dict,
                             scores=scores)
            )
        )
    else:
        scores = None

    if min_individual_rank is not None:
        extra_csts.append(
            csts.MinIndividualScoreConstraint(scores, min_individual_rank)
        )

    for grid, score_file in score_list:
        df = pd.read_csv(score_file)
        sc_d = {
            i: row.iloc[0] for i, row in
            df.groupby([df.columns[0], df.columns[1], df.columns[2]]).sum().iterrows()
        }

        score_functions.append(
            (grid, partial(score.objective_from_score_dict,
                           scores=sc_d, default_score=0))
        )

    return score_functions, scores, extra_csts


def report_and_write(status, solver, solution_printer, results_path):
    """Print the solve statistics and, on success, write the best solution.

    Returns 1 when a solution was found and written, 0 otherwise.
    """

    # Statistics.
    print("status:", status)
    print('\nStatistics')
    print('  - conflicts      : %i' % solver.NumConflicts())
    print('  - branches       : %i' % solver.NumBranches())
    print('  - wall time      : %f s' % solver.WallTime())
    print('  - solutions found: %i' % solution_printer.solution_count())
    print('  - objective value: %i' % solver.ObjectiveValue())

    if status in ['OPTIMAL', 'FEASIBLE']:
        io.write_solution(results_path, solution_printer._solutions[-1])
        print("Best solution at ", results_path)

        return 1
    else:
        print("No best solution.")

        return 0


def load_problem_and_scores(args):

    problem = io.load_problem(
        args.config,
        coverage_min=args.coverage_min,
        coverage_max=args.coverage_max,
        hint_path=args.hint,
        require=args.require,
    )

    print("Residents:", len(problem.residents))
    print("Blocks:", len(problem.blocks))
    print("Rotations:", len(problem.rotations))

    score_functions, scores, extra_csts = build_score_functions(
        problem.residents, problem.blocks, problem.rotations,
        rankings=args.rankings,
        score_list=args.score_list,
        block_resident_ranking=args.block_resident_ranking,
        min_individual_rank=args.min_individual_rank,
    )

    return problem, score_functions, scores, extra_csts


def run_solve(args):

    problem, score_functions, scores, extra_csts = load_problem_and_scores(args)

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        problem.residents, problem.blocks, problem.rotations,
        problem.groups_array, problem.cst_list + extra_csts,
        soln_printer=partial(
            callback.JugScheduleSolutionPrinter,
            scores=scores,
            solution_limit=args.n_solutions,
        ),
        cogrids=problem.cogrids,
        score_functions=score_functions,
        n_processes=args.n_processes,
        hint=problem.hint,
        max_time_in_mins=None
    )

    return report_and_write(status, solver, solution_printer, args.results)


def run_swap(args):

    n_solutions = (1 if args.n_solutions in (Ellipsis, None)
                   else args.n_solutions)
    if n_solutions < 1:
        raise SystemExit(
            "schedulomicon swap: --n-solutions must be at least 1 "
            f"(got {n_solutions})")

    problem, score_functions, scores, extra_csts = load_problem_and_scores(args)

    old_solution = io.read_solution(args.minimize_changes_from)

    freeze_csts = [
        swap.build_freeze_constraint(
            spec, old_solution, problem.config, problem.groups_array,
            problem.residents, problem.blocks, problem.rotations,
            problem.cogrids)
        for spec in args.freeze
    ]

    cst_list = problem.cst_list + extra_csts + freeze_csts

    # In swap mode -n counts proposals, not per-pass callback solutions; a
    # per-pass cap could stop CP-SAT before proving minimality, so the
    # printer prototype never gets a solution_limit here.
    soln_printer = partial(callback.JugScheduleSolutionPrinter, scores=scores)

    if n_solutions == 1:
        status, solver, solution_printer, model, wall_runtime, d_star = \
            swap.swap_solve(
                problem.residents, problem.blocks, problem.rotations,
                problem.groups_array, cst_list,
                soln_printer=soln_printer,
                cogrids=problem.cogrids,
                score_functions=score_functions,
                old_solution=old_solution,
                n_processes=args.n_processes,
                hint=problem.hint,
                max_time_in_mins=None,
            )

        if d_star is not None:
            print(f"Minimal changes (variable flips) from old schedule: {d_star}")

        ret = report_and_write(status, solver, solution_printer, args.results)

        if status in ['OPTIMAL', 'FEASIBLE']:
            print()
            print(swap.format_diff_report(
                old_solution, solution_printer._solutions[-1]))

        return ret

    proposals, last_result = swap.swap_solve_multi(
        problem.residents, problem.blocks, problem.rotations,
        problem.groups_array, cst_list,
        soln_printer=soln_printer,
        cogrids=problem.cogrids,
        score_functions=score_functions,
        old_solution=old_solution,
        n_solutions=n_solutions,
        n_processes=args.n_processes,
        hint=problem.hint,
        max_time_in_mins=None,
    )

    if not proposals:
        status, solver, solution_printer, model, wall_runtime, d_star = \
            last_result
        return report_and_write(status, solver, solution_printer, args.results)

    for i, prop in enumerate(proposals, 1):
        path = io.numbered_path(args.results, i)
        io.write_solution(path, prop.solution)

        header = (f"=== Proposal {i}/{n_solutions}: {prop.d} variable "
                  "flip(s) from old schedule")
        if prop.score is not None:
            header += f" (score: {prop.score})"
        header += " ==="

        print()
        print(header)
        print("Solution written to", path)
        print(swap.format_diff_report(old_solution, prop.solution))

    if len(proposals) < n_solutions:
        print()
        print(f"Found {len(proposals)} of {n_solutions} requested proposals; "
              "no further distinct feasible solutions exist.")

    return 1


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # back-compat shim: 'schedulomicon --config ...' used to be the whole
    # CLI; treat a leading flag (except bare -h/--help) as 'solve'
    if argv and argv[0].startswith('-') and argv[0] not in ('-h', '--help'):
        print("DeprecationWarning: invoking schedulomicon without a "
              "subcommand is deprecated; assuming 'schedulomicon solve'.",
              file=sys.stderr)
        argv = ['solve'] + list(argv)

    args = parse_args(argv)

    if args.command == 'swap':
        return run_swap(args)
    else:
        return run_solve(args)


if __name__ == '__main__':
    main()
