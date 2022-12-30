class Constraint:
    pass

class PinnedRotationConstraint(Constraint):

    def __repr__(self):
        return "PinnedRotationConstraint(%s,%s,%s)" % (self.resident, self.pinned_blocks, self.pinned_rotation)

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
