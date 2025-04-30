
from ortools.sat.python import cp_model


def generate_model(residents, blocks, rotations, groups_array):
    model = cp_model.CpModel()

    # Creates shift variables.
    block_assigned = {}
    for res in residents:
        for blk in blocks:
            for rot in rotations:
                block_assigned[res, blk, rot] = model.NewBoolVar(
                    f'block_assigned-r{res}-b{blk}-{rot}')

    # Each resident must work some rotation each block
    for res in residents:
        for block in blocks:
            model.AddExactlyOne(
                block_assigned[(res, block, rot)] for rot in rotations)

    return block_assigned, model


def generate_vacation(model, residents, rotations, weeks):

    vacation_assigned = {}

    for res in residents:
        for week in weeks:
            for rot in rotations:
                vacation_assigned[res, week, rot] = model.NewBoolVar(
                    f'vacation_assigned-r{res}-w{week}-{rot}'
                )

    # for each week/resident pair, there can be at most one vacation
    for week in weeks:
        for res in residents:
            model.Add(
                sum(vacation_assigned[res, week, rot] for rot in rotations)
                <= 1
            )

    return vacation_assigned


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

