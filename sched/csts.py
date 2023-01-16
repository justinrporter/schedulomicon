class Constraint:
    pass


class BackupRequiredOnBlockBackupConstraint(Constraint):

    def __init__(self, block, n_residents_needed):
        self.block = block
        self.n_residents_needed = n_residents_needed

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):
        ct = 0
        for resident in residents:
            ct += block_backup[(resident, self.block)]
        model.Add(ct == self.n_residents_needed)


class RotationBackupCountConstraint(Constraint):

    def __init__(self, rotation, count):
        self.rotation = rotation
        self.count = count

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

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


class BackupEligibleBlocksBackupConstraint(Constraint):

    def __init__(self, backup_eligible):
        self.backup_eligible = {k: 1 if v else 0 for k, v in backup_eligible.items()}

    def apply(self, model, block_assigned, residents, blocks, rotations, block_backup):

        # slacks = [model.NewBoolVar('slack_%i' % b) for b in all_bins]

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

    def apply(self, model, block_assigned, residents, blocks, rotations):

        for resident in residents:
            model.Add(block_assigned[(resident, self.block, self.rotation)] == 0)


class RotationCoverageConstraint(Constraint):

    def __repr__(self):
        return "RotationCoverageConstraint(%s,%s,%s,%s)" % (
             self.rotation, self.blocks, self.rmin, self.rmax)

    def __init__(self, rotation, blocks=Ellipsis, rmin=None, rmax=None):
        self.rotation = rotation
        self.blocks = blocks
        self.rmin = rmin
        self.rmax = rmax

        assert self.rmax is not None or self.rmin is not None

    def apply(self, model, block_assigned, residents, blocks, rotations):

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
            r_tot = sum(block_assigned[(res, block, self.rotation)] for res in residents)
            if rmin is not None and rmin > 0:
                model.Add(r_tot >= rmin)
            if rmax is not None:
                model.Add(r_tot <= rmax)


class PrerequisiteRotationConstraint(Constraint):

    def __init__(self, rotation, prerequisites):
        self.rotation = rotation
        self.prerequisites = prerequisites

    def apply(self, model, block_assigned, residents, blocks, rotations):

        add_prerequisite_constraint(
            model, block_assigned, residents, blocks,
            rotation=self.rotation, prerequisites=self.prerequisites
        )


class AlwaysPairedRotationConstraint(Constraint):

    def __repr__(self):
        return "AlwaysPairedRotationConstraint(%s)" % (
             self.rotation)

    def __init__(self, rotation):
        self.rotation = rotation

    def apply(self, model, block_assigned, residents, blocks, rotations):

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

    def apply(self, model, block_assigned, residents, blocks, rotations):

        add_must_be_followed_by_constraint(
            model, block_assigned, residents, blocks,
            rotation=self.rotation,
            following_rotations=self.following_rotations
        )


class RotationCountConstraint(Constraint):

    def __init__(self, rotation, n_min, n_max):
        self.rotation = rotation
        self.n_min = n_min
        self.n_max = n_max

    def apply(self, model, block_assigned, residents, blocks, rotations):

        for resident, nmin, nmax in zip(residents, self.n_min, self.n_max):
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot >= nmin)
            model.Add(r_tot <= nmax)

class RotationCountNotConstraint(Constraint):

    def __init__(self, rotation, ct):
        self.rotation = rotation
        self.ct = ct

    def apply(self, model, block_assigned, residents, blocks, rotations):

        for resident in residents:
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot != self.ct)


class PinnedRotationConstraint(Constraint):

    def __repr__(self):
        return "%s(%s,%s,%s)" % (
            self.__class__, self.resident, self.pinned_blocks, self.pinned_rotation)

    def __init__(self, resident, pinned_blocks, pinned_rotation):

        self.resident = resident
        self.pinned_blocks = pinned_blocks
        self.pinned_rotation = pinned_rotation

    def apply(self, model, block_assigned, residents, blocks, rotations):
        # if the block to pin is unspecified, the rotation is assigned to the
        # resident somewhere in the schedule
        if len(self.pinned_blocks) == 0:
            model.Add(
                sum(block_assigned[self.resident, block, self.pinned_rotation]
                    for block in blocks) >= 1
            )
        # otherwise we pin the specific block
        else:
            for pinned_block in self.pinned_blocks:
                model.Add(
                    block_assigned[
                        self.resident, pinned_block, self.pinned_rotation] == 1
                )


class MinIndividualRankConstraint(Constraint):

    def __init__(self, rankings, min_rank):
        self.rankings = rankings
        self.min_rank = min_rank

    def apply(self, model, block_assigned, residents, blocks, rotations):

        for res in residents:
            res_obj = 0
            for rot in rotations:
                if res in self.rankings and rot in self.rankings[res]:
                    for blk in blocks:
                        res_obj += (
                            self.rankings[res][rot] *
                            block_assigned[res, blk, rot]
                        )

            model.Add(res_obj <= self.min_rank)

class TimeToFirstConstraint(Constraint):

    def __init__(self, rotations_in_group, window_size):
        self.rotations_in_group = rotations_in_group
        self.window_size = window_size
    
    def apply(self, model, block_assigned, all_residents, all_blocks, all_rotations):
        for res in all_residents:
            count = 0
            for blk in all_blocks[:self.window_size]:
                for rot in self.rotations_in_group:
                    count += block_assigned[(res, blk, rot)]
            model.Add(count >= 1)
class GroupCountPerResidentPerWindow(Constraint):

    def __repr__(self):
        return "GroupCountPerResident(%s,%s,%s)" % (
             self.rotations_in_group, self.n_min, self.n_max)

    def __init__(self, rotations_in_group, n_min, n_max, window_size):

        self.rotations_in_group = rotations_in_group
        self.n_min = n_min
        self.n_max = n_max
        self.window = window_size

    def apply(self, model, block_assigned, all_residents, all_blocks, all_rotations):

        n_blocks = len(all_blocks)
        n_full_windows = n_blocks - self.window + 1

        for res in all_residents:

            for i in range(n_full_windows):
                ct = 0

                for blk in all_blocks[ i : self.window + i ]:

                    for rot in self.rotations_in_group:
                        ct += block_assigned[(res, blk, rot)]

                model.Add(ct >= self.n_min)
                model.Add(ct <= self.n_max)

        # Must also apply edge cases (the last window, which is not a full window)

            ct = 0

            for blk in all_blocks[ - (self.window - 1) :  ]:

                for rot in self.rotations_in_group:
                    ct += block_assigned[(res, blk, rot)]

            model.Add(ct >= self.n_min)
            model.Add(ct <= self.n_max)

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
