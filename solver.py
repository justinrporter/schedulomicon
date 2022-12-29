import math
import datetime
import argparse
import csv

import yaml
import numpy as np

from ortools.sat.python import cp_model


class Constraint:
    pass

class MinIndividualRankConstraint(Constraint):

    def __init__(self, rankings, min_rank):
        self.rankings = rankings
        self.min_rank = min_rank

    def apply(self, model, block_assigned, residents, blocks, rotations):

        for res in residents:
            res_obj = 0
            for blk in blocks:
                for rot in rotations:
                    if res in self.rankings and rot in self.rankings[res]:
                        res_obj += (
                            self.rankings[res][rot] *
                            block_assigned[res, blk, rot]
                        )
            model.Add(res_obj < self.min_rank)


class GroupCountPerResident(Constraint):

    def __init__(self, rotations_in_group, n_min, n_max):

        self.rotations_in_group = rotations_in_group
        self.n_min = n_min
        self.n_max = n_max

    def apply(self, model, block_assigned, all_residents, all_blocks, all_rotations):

        for res in all_residents:
            ct = 0

            for blk in all_blocks:
                for rot in self.rotations_in_group:
                    ct += block_assigned[(res, blk, rot)]

            model.Add(ct >= self.n_min)
            model.Add(ct <= self.n_max)


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


def add_prerequisite_constraint(model, block_assigned, residents, blocks,
                                rotation, prerequisites):

    for resident in residents:
        for i in range(len(blocks)):
            rot_is_assigned = block_assigned[(resident, blocks[i], rotation)]

            for prereq in prerequisites:
                n_prereq_instances = 0
                for j in range(0, i):
                    n_prereq_instances += block_assigned[(resident, blocks[j], prereq)]

                model.Add(n_prereq_instances >= 1).OnlyEnforceIf(rot_is_assigned)


def add_must_be_followed_by_constraint(model, block_assigned, residents, blocks,
                                       rotation, following_rotations):

    for a_block, b_block in zip(blocks[0:-1], blocks[1:]):
        for resident in residents:
            a = block_assigned[(resident, a_block, rotation)]

            n_electives = 0

            for elective in following_rotations:
                n_electives += block_assigned[(resident, b_block, elective)]

            model.Add(
                n_electives > 0
            ).OnlyEnforceIf(a)


def add_must_be_paired_constraint(model, block_assigned, residents, blocks,
                                  rot_name):

    for resident in residents:
        for b1, b2, b3 in zip(blocks[:-2], blocks[1:-1], blocks[2:]):
            n_flanking = (
                block_assigned[(resident, b1, rot_name)] +
                block_assigned[(resident, b3, rot_name)]
            )

            model.Add(
                n_flanking == 1
            ).OnlyEnforceIf(block_assigned[(resident, b2, rot_name)])

        #  the above constraint leaves off the edges.
        b1 = blocks[0]
        b2 = blocks[1]

        model.Add(
            block_assigned[(resident, b2, rot_name)] == 1
        ).OnlyEnforceIf(block_assigned[(resident, b1, rot_name)])

        b1 = blocks[-1]
        b2 = blocks[-2]

        model.Add(
            block_assigned[(resident, b2, rot_name)] == 1
        ).OnlyEnforceIf(block_assigned[(resident, b1, rot_name)])


class BlockSchedulePartialSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, block_assigned, residents, blocks, rotations, limit, outfile):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._block_assigned = block_assigned
        self._residents = residents
        self._blocks = blocks
        self._rotations = rotations
        self._solution_count = 0
        self._solution_limit = limit

        self._outfile = outfile

        self._column_width = max(
            max(len(b) for b in blocks),
            max(len(r) for r in rotations)
        )

    def on_solution_callback(self):
        self._solution_count += 1

        rows = [[''] + self._residents]
        for block in self._blocks:
            row = [block]
            for resident in self._residents:
                for rotation in self._rotations:
                    if self.Value(self._block_assigned[(resident, block, rotation)]):
                        row.append(self._rotations.index(rotation))
            rows.append(row)

        # with open(self._outfile % self._solution_count, 'w') as f:
        #     writer = csv.writer(f, delimiter=',')
        #     for row in rows:
        #         writer.writerow(row)

        a = np.array([r[1:] for r in rows[1:]], dtype='int16')
        fname = self._outfile.replace('csv', 'npz') % 0


        if self._solution_count == 1:
            a_full = a
        else:
            a_full = np.load(fname)['a']
            a_full = np.dstack([a_full, a])

        np.savez(fname, a=a_full)

        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        # if self._solution_count >= self._solution_limit:
        #     self.StopSearch()

    def solution_count(self):
        return self._solution_count


def generate_solver(config, residents, blocks, rotations, groups, rankings):

    model = cp_model.CpModel()

    # Creates shift variables.
    block_assigned = {}
    for resident in residents:
        for block in blocks:
            for rot in rotations:
                block_assigned[(resident, block, rot)] = model.NewBoolVar(
                    f'block_assigned-r{resident}-b{block}-{rot}')

    for block, params in config['blocks'].items():
        if not params:
            continue

        for key in params:
            if key in rotations:
                bval = params[key]
                if not bval:
                    for resident in residents:
                        model.Add(block_assigned[(resident, block, key)] == 0)
                else:
                    print(f"In {block}, {key}: Yes has no effect")
            if key in groups:
                grp = resolve_group(key, config['rotations'])
                bval = params[key]

                if not bval:
                    for grp_memb in grp:
                        for resident in residents:
                            model.Add(block_assigned[(resident, block, grp_memb)] == 0)
                else:
                    print(f"In {block}, {key}: Yes has no effect")

    for rotation, params in config['rotations'].items():

        if not params:
            continue
        if 'coverage' in params:
            rmin, rmax = handle_count_specification(
                params['coverage'], len(blocks))

            for block, rmin, rmax in zip(blocks, rmin, rmax):
                # r_tot is the total number of residents on this rotation for this block
                r_tot = sum(block_assigned[(res, block, rotation)] for res in residents)
                model.Add(r_tot >= rmin)
                model.Add(r_tot <= rmax)
        if 'must_be_followed_by' in params:
            following_rotations = []
            for key in params['must_be_followed_by']:
                if key in config['rotations']:
                    following_rotations.append(key)
                else:
                    following_rotations.extend(
                        resolve_group(key, config['rotations']))

            add_must_be_followed_by_constraint(
                model, block_assigned, residents, blocks,
                rotation=rotation,
                following_rotations=following_rotations
            )

        if 'prerequisite' in params:
            add_prerequisite_constraint(
                model, block_assigned, residents, blocks,
                rotation=rotation, prerequisites=params['prerequisite']
            )

        if params.get('always_paired', False):
            add_must_be_paired_constraint(
                model, block_assigned, residents, blocks,
                rot_name=rotation
            )

        if 'rot_count' in params:
            rmin, rmax = handle_count_specification(
                params['rot_count'], len(residents))

            for resident, rmin, rmax in zip(residents, rmin, rmax):
                r_tot = sum(block_assigned[(resident, block, rotation)] for block in blocks)
                model.Add(r_tot >= rmin)
                model.Add(r_tot <= rmax)

        if 'not_rot_count' in params:
            ct = params['not_rot_count']

            for resident in residents:
                r_tot = sum(block_assigned[(resident, block, rotation)] for block in blocks)
                model.Add(r_tot != ct)

    for res, params in config['residents'].items():
        if not params:
            continue
        if 'pin_rotation' in params:
            for pinned_rotation, pinned_blocks in params['pin_rotation'].items():
                for pinned_block in pinned_blocks:
                    model.Add(
                        block_assigned[res, pinned_block, pinned_rotation] == 1
                    )
                if len(pinned_blocks) == 0:
                    model.Add(
                        sum(block_assigned[res, block, pinned_rotation] for block in blocks) >= 1
                    )

    # Each resident must work some rotation each block
    for res in residents:
        for block in blocks:
            model.AddExactlyOne(
                block_assigned[(res, block, rot)] for rot in rotations)

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


def generate_constraints_from_configs(
        config, block_assigned, model, residents, blocks, rotations,
        rankings, groups):

    constraints = []

    for cst in config['group_constraints']:
        if cst['kind'] == 'group_count_per_resident':
            constraints.append(
                GroupCountPerResident(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1])
            )

    return constraints

def main():

    args = parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    residents, blocks, rotations, rankings, groups = process_config(config)

    block_assigned, model = generate_solver(
        config, residents, blocks, rotations, rankings, groups
    )

    constraints = generate_constraints_from_configs(
        config, block_assigned, model, residents, blocks, rotations,
        rankings, groups)

    if args.min_individual_rank is not None:
        constraints.append(
            MinIndividualRankConstraint(rankings, args.min_individual_rank)
        )

    for cst in constraints:
        cst.apply(model, block_assigned, residents, blocks, rotations)

    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    solver.parameters.linearization_level = 2

    print(args.objective)
    print(args.objective == 'rank_sum_objective')
    if args.objective == 'rank_sum_objective':
        obj = rank_sum_objective(block_assigned, rankings, residents, blocks, rotations)
        model.Minimize(obj)
        solver.parameters.enumerate_all_solutions = False
        solver.parameters.num_search_workers = args.n_processes
    else:
        assert False
        solver.parameters.enumerate_all_solutions = True

    # Display the first five solutions.
    solution_limit = args.n_solutions
    solution_printer = BlockSchedulePartialSolutionPrinter(
        block_assigned,
        residents,
        blocks,
        rotations,
        solution_limit,
        outfile=args.results
    )

    solver.Solve(model, solution_printer)
    # solver.Solve(model, cp_model.ObjectiveSolutionPrinter())
    # solver.SearchForAllSolutions(model, solution_printer)

    # Statistics.
    # print('\nStatistics')
    # print('  - conflicts      : %i' % solver.NumConflicts())
    # print('  - branches       : %i' % solver.NumBranches())
    print('  - wall time      : %f s' % solver.WallTime())
    print('  - solutions found: %i' % solution_printer.solution_count())
    # print('  - objective value: %i' % solver.ObjectiveValue())


if __name__ == '__main__':
    main()
