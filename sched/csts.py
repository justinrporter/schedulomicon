import itertools
import numbers
import logging
import numpy as np

from .exceptions import YAMLParseError


logger = logging.getLogger(__name__)


class Constraint:

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):
        pass

    @classmethod
    def _check_yaml_params(cls, root_entity, cst_params):
        for key in cst_params:
            if key not in cls.ALLOWED_YAML_OPTIONS:
                raise YAMLParseError(
                    f'On {root_entity}, option {key} not allowed (allowed '
                    f'options are {cls.ALLOWED_YAML_OPTIONS}).'
                )

class BackupRequiredOnBlockBackupConstraint(Constraint):

    def __init__(self, block, n_residents_needed):
        self.block = block
        self.n_residents_needed = n_residents_needed

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        ct = 0
        for resident in residents:
            ct += block_backup[(resident, self.block)]
        model.Add(ct == self.n_residents_needed)


class RotationBackupCountConstraint(Constraint):

    def __init__(self, rotation, count):
        self.rotation = rotation
        self.count = count

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        backup_vars = {}
        for resident in residents:
            for block in blocks:
                backup_vars[(resident, block)] = model.NewBoolVar(
                    'backup_r%s_b%s_%s' % (resident, block, self.rotation))

        for resident in residents:
            for block in blocks:
                model.AddImplication(
                    block_backup[(resident, block)],
                    backup_vars[(resident, block)]
                ).OnlyEnforceIf(block_assigned[(resident, block, self.rotation)])

                model.AddImplication(
                    block_assigned[(resident, block, self.rotation)],
                    backup_vars[(resident, block)]
                ).OnlyEnforceIf(block_backup[(resident, block)])

                model.AddImplication(
                    block_assigned[(resident, block, self.rotation)].Not(),
                    backup_vars[(resident, block)].Not()
                )

                model.AddImplication(
                    block_backup[(resident, block)].Not(),
                    backup_vars[(resident, block)].Not()
                )

        ct = 0
        for block in blocks:
            for resident in residents:
                ct += backup_vars[(resident, block)]
        model.Add(ct <= self.count)

class BanBackupBlockContraint(Constraint):
    def __init__(self, resident, block):
        self.block = block
        self.resident = resident

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        model.Add(block_backup[(self.resident, self.block)] == 0)
class BackupEligibleBlocksBackupConstraint(Constraint):

    def __init__(self, backup_eligible):
        self.backup_eligible = {k: 1 if v else 0 for k, v in backup_eligible.items()}

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        for resident in residents:
            for block in blocks:
                for rotation in rotations:
                    # if a resident is assigned to a rotation on a block
                    # backup_eligible must be 1 for block_backup to be 1

                    block_is_assigned = block_assigned[(resident, block, rotation)]

                    model.Add(
                        self.backup_eligible[rotation] >= block_backup[(resident, block)]) \
                            .OnlyEnforceIf(block_is_assigned)


class BanRotationBlockConstraint(Constraint):

    def __init__(self, block, rotation):
        self.block = block
        self.rotation = rotation

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        for resident in residents:
            model.Add(block_assigned[(resident, self.block, self.rotation)] == 0)


class RotationCoverageConstraint(Constraint):

    def __repr__(self):
        return "RotationCoverageConstraint(%s,%s,%s,%s)" % (
             self.rotation, self.blocks, self.rmin, self.rmax)

    def __init__(self, rotation, blocks=Ellipsis, rmin=None, rmax=None, allowed_vals=None):
        self.rotation = rotation
        self.blocks = blocks
        self.rmin = rmin
        self.rmax = rmax
        self.allowed_vals = allowed_vals

        assert self.rmax is not None or self.rmin is not None

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        # ellipsis just means all blocks
        if self.blocks is Ellipsis:
            apply_to_blocks = blocks
        else:
            apply_to_blocks = self.blocks

        if not hasattr(self.rmin, '__len__'):
            rmin_list = [self.rmin]*len(apply_to_blocks)
        else:
            rmin_list = self.rmin

        if not hasattr(self.rmax, '__len__'):
            rmax_list = [self.rmax]*len(apply_to_blocks)
        else:
            rmax_list = self.rmax

        for block, rmin, rmax in zip(apply_to_blocks, rmin_list, rmax_list):
            # r_tot is the total number of residents on this rotation for this block
            r_tot = 0
            for res in residents:
                r_tot += block_assigned[(res, block, self.rotation)]
            #r_tot = sum(block_assigned[(res, block, self.rotation)] for res in residents)
            if rmin is not None:
                model.Add(r_tot >= rmin)
            if rmax is not None:
                model.Add(r_tot <= rmax)
            if self.allowed_vals is not None:
                r_tot_var = model.NewIntVar(-1000, 1000, "r_tot_var")
                model.Add(r_tot_var == r_tot)
                allowed_vals = [[value] for value in self.allowed_vals]
                model.AddAllowedAssignments([r_tot_var], allowed_vals)


class PrerequisiteRotationConstraint(Constraint):

    def __init__(self, rotation, prerequisites=None, prereq_counts=None):
        self.rotation = rotation

        assert prerequisites is not None or prereq_counts is not None
        assert prerequisites is None or prereq_counts is None

        if prerequisites is not None:
            assert prereq_counts is None

            self.prerequisites = {}
            for p in prerequisites:
                self.prerequisites[(p,)] = 1
        else:
            # has the form {(rot1, rot2): 2, (rot3,): 1}
            # indicates rot1 and/or rot2 twice, rot3 once
            self.prerequisites = prereq_counts

        logger.debug('Rotation %s prerequisites %s', rotation, self.prerequisites)

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        for resident in residents:
            for i in range(len(blocks)):
                rot_is_assigned = block_assigned[(resident, blocks[i], self.rotation)]

                for prereq_grp, req_ct in self.prerequisites.items():
                    for prereq in prereq_grp:
                        n_prereq_instances = 0
                        for j in range(0, i):
                            n_prereq_instances += block_assigned[(resident, blocks[j], prereq)]

                    model.Add(n_prereq_instances >= req_ct).OnlyEnforceIf(rot_is_assigned)


class AlwaysPairedRotationConstraint(Constraint):

    def __repr__(self):
        return "AlwaysPairedRotationConstraint(%s)" % (
             self.rotation)

    def __init__(self, rotation):
        self.rotation = rotation

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        add_must_be_paired_constraint(
            model, block_assigned, residents, blocks,
            rot_name=self.rotation
        )


class MustBeFollowedByRotationConstraint(Constraint):

    def __repr__(self):
        return "RotationMustBeFollowedByConstraint(%s,%s)" % (
             self.rotation, self.following_rotations)

    def __init__(self, rotation, following_rotations):
        self.rotation = rotation
        self.following_rotations = following_rotations

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        add_must_be_followed_by_constraint(
            model, block_assigned, residents, blocks,
            rotation=self.rotation,
            following_rotations=self.following_rotations
        )


class CoolDownConstraint(Constraint):

    ALLOWED_YAML_OPTIONS = ['window', 'count', 'suppress_for']

    @classmethod
    def from_yml_dict(cls, rotation, params):

        assert 'cool_down' in params
        cls._check_yaml_params(rotation, params['cool_down'])

        # Expected format:
        # cool_down:
        #   window: 2
        #   count: 1
        #   exclude_for: ["Yi, Yangtian"]

        window_size = params['cool_down'].get('window')
        count = params['cool_down'].get('count', 1)
        suppress_for = params['cool_down'].get('suppress_for', [])

        if params.get('always_paired', False) and window_size < 2:
            assert False, (
                f'Expected window_size > 1 (got {window_size}) for '
                f'paired rotation {rotation}'
            )

        return cls(
            rotation,
            window_size=window_size,
            count=[0, count],
            suppress_for=suppress_for
        )

    def __repr__(self):
        return "CoolDownConstraint(%s,%s,%s)" % (
             self.rotation, self.window_size, self.count)

    def __init__(self, rotation, window_size, count, suppress_for=[]):
        self.rotation = rotation
        self.window_size = window_size
        self.count = count
        self.n_min = count[0]
        self.n_max = count[1]
        self.suppress_for = suppress_for

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        residents = [res for res in residents if res not in self.suppress_for]
        
        add_window_count_constraint(
            model, block_assigned, residents, blocks,
            rotations=[self.rotation],
            window_size=self.window_size,
            n_min = self.n_min,
            n_max = self.n_max
        )


class RotationCountConstraint(Constraint):

    def __init__(self, rotation, n_min, n_max):
        self.rotation = rotation
        self.n_min = n_min
        self.n_max = n_max

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        n_min = self.n_min
        n_max = self.n_max

        if not hasattr(n_min, '__len__'):
            n_min = itertools.repeat(n_min)
        if not hasattr(n_max, '__len__'):
            n_max = itertools.repeat(n_max)

        for resident, nmin, nmax in zip(residents, n_min, n_max):
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot >= nmin)
            model.Add(r_tot <= nmax)

class RotationCountNotConstraint(Constraint):

    def __init__(self, rotation, ct):
        self.rotation = rotation
        self.ct = ct

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        for resident in residents:
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot != self.ct)

class PinnedRotationConstraint(Constraint):

    def __init__(self, eligible_field):
        self.eligible_field = eligible_field
    
    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        sum = 0
        for loc,value in np.ndenumerate(self.eligible_field[0]):
            x,y,z = loc
            if value == True:
                res = residents[x]
                block = blocks[y]
                rot = rotations[z]
                sum += block_assigned[res, block, rot]
        model.Add(sum >= 1)

class ProhibitedCombinationConstraint(Constraint):

    def __init__(self, prohibited_fields):
        self.prohibited_fields = prohibited_fields
    
    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)
        
        list_length = len(self.prohibited_fields)
        sum = 0
        for field in self.prohibited_fields:
            for loc,value in np.ndenumerate(field):
                x,y,z = loc
                if value == True:
                    res = residents[x]
                    block = blocks[y]
                    rot = rotations[z]
                    sum += block_assigned[res, block, rot]
        model.Add(sum < list_length)
class MarkIneligibleConstraint(Constraint):

    def __init__(self, eligible_field):
        self.eligible_field = eligible_field
    
    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        sum = 0
        for (x,y,z), value in np.ndenumerate(~self.eligible_field[0]):
            if value == True:
                res = residents[x]
                block = blocks[y]
                rot = rotations[z]
                sum += block_assigned[res, block, rot]
        model.Add(sum == 0)

class RotationWindowConstraint(Constraint):

    def __repr__(self):
        return "%s(%s,%s,%s)" % (
            self.__class__, self.resident, self.rotation, self.possible_blocks)

    def __init__(self, resident, rotation, possible_blocks):

        self.resident = resident
        self.rotation = rotation
        self.possible_blocks = possible_blocks

    def apply(self, model, block_assigned, residents, blocks, rotations):

        super().apply(model, block_assigned, residents, blocks, rotations)

        # Rotation is assigned to the resident somewhere in the "possible_blocks"
        sum = 0
        for block in self.possible_blocks:
            sum += block_assigned[self.resident, block, self.rotation]

        model.Add(sum >= 1)

class MinIndividualScoreConstraint(Constraint):

    def __init__(self, scores, min_score):
        assert isinstance(min_score, numbers.Number)
        assert min_score == int(min_score)

        self.scores = scores

        self.min_score = int(min_score)
        print(self.min_score)

        logger.info(f"Created MinIndividualScoreConstraint with "
                     f"min_score {self.min_score}")


    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        assert set(residents) == set([res for res, _, _ in block_assigned.keys()])

        for res in residents:
            res_obj = 0
            ct = 0
            for rot in rotations:
                for blk in blocks:
                    k = (res, blk, rot)
                    x = self.scores[k]

                    assert int(x) == x, f"Score for {x} {k} is not an integer"

                    res_obj += int(x) * block_assigned[k]
                    ct += 1

            logger.debug(f"Added {ct} scores for {res} in MinIndividualScoreConstraint")
            model.Add(res_obj < self.min_score)

        logger.info(f"Applied individual resident utility < {self.min_score} to "
                     f"{len(residents)} residents")

class TimeToFirstConstraint(Constraint):

    def __init__(self, rotations_in_group, window_size):
        self.rotations_in_group = rotations_in_group
        self.window_size = window_size
    
    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        for res in residents:
            count = 0
            for blk in blocks[:self.window_size]:
                for rot in self.rotations_in_group:
                    count += block_assigned[(res, blk, rot)]

            model.Add(count > 1)


class GroupCountPerResidentPerWindow(Constraint):

    def __repr__(self):
        return "GroupCountPerResident(%s,%s,%s)" % (
             self.rotations_in_group, self.n_min, self.n_max)

    def __init__(self, rotations_in_group, n_min, n_max, window_size, res_list=None):

        self.rotations_in_group = rotations_in_group
        self.n_min = n_min
        self.n_max = n_max
        self.window = window_size
        self.res_list = res_list

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        super().apply(model, block_assigned, residents, blocks, rotations, block_backup)

        if self.res_list is not None: 
            residents = self.res_list

        add_window_count_constraint(
            model, block_assigned, residents, blocks,
            self.rotations_in_group, self.window, self.n_min, self.n_max
        )

class ResidentGroupConstraint(Constraint):

    def __init__(self, rotation, eligible_residents):

        self.rotation = rotation
        self.eligible_residents = eligible_residents

    def apply(self, model, block_assigned, residents, blocks):

        super().apply(model, block_assigned, residents, blocks)

        add_resident_group_constraint(
            model, block_assigned, residents, blocks,
            self.rotation, self.eligible_residents
        )

class EligibleAfterBlockConstraint(Constraint):

    def __init__(self, rotation, resident_group, eligible_after_block):

        self.rotation = rotation
        self.resident_group = resident_group
        self.eligible_after_block = eligible_after_block

    def apply(self, model, block_assigned, residents, blocks, rotations):

        super().apply(model, block_assigned, residents, blocks, rotations)

        eligible_index = blocks.index(self.eligible_after_block)+1
        ineligible_blocks = blocks[:eligible_index]

        add_resident_group_constraint(
            model, block_assigned, residents, blocks, rotations,
            self.rotation, self.resident_group, ineligible_blocks
        )



def add_must_be_paired_constraint(model, block_assigned, residents, blocks,
                                  rot_name):

    # slide a window of size 3 across the blocks
    # only one of the flanking rotations can be rot_name
    # and that cst is only applied if the middle block is also rot_name
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


def add_window_count_constraint(model, block_assigned, residents, blocks,
                                rotations, window_size, n_min, n_max):

    n_blocks = len(blocks)
    n_full_windows = n_blocks - window_size + 1

    for res in residents:
        for i in range(n_full_windows):
            ct = 0
            for blk in blocks[ i : window_size + i ]:
                for rot in rotations:
                    ct += block_assigned[(res, blk, rot)]
            model.Add(ct >= n_min)
            model.Add(ct <= n_max)

def add_resident_group_constraint(model, block_assigned, residents, blocks,
                                rotation, eligible_residents, ineligible_blocks = None):
# If all blocks are indicated, adds a constrains that the sum of blocks = 0 if the resident is not in "eligible residents" group
    for res in residents:
        if ineligible_blocks is None:
            n = sum(block_assigned[(res, block, rotation)] for block in blocks)
            model.Add(n == 0).OnlyEnforceIf(res not in eligible_residents)
# If only certain 'eligible blocks' have been indicated, makes sure that the eligible_residents are NOT assigned the rotation during an ineligible block)
        else:
            n = sum(block_assigned[(res, block, rotation)] for block in ineligible_blocks)
            model.Add(n == 0).OnlyEnforceIf(res in eligible_residents)