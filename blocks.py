from ortools.sat.python import cp_model

# Creates the model.
model = cp_model.CpModel()

n_residents = 4
n_blocks = 4

residents = ['Justin', 'Isaac', 'Brian', 'Leah']
blocks = ['summer', 'fall', 'winter', 'spring']
rotations = ['med', 'surg', 'elec', 'em']

# Creates shift variables.
# shift[(n, d, s)] == True if
block_assigned = {}
for resident in residents:
    for block in blocks:
        for rot in rotations:
            block_assigned[(resident, block, rot)] = model.NewBoolVar(
                f'block_assigned-r{resident}-b{block}-{rot}')

# Each shift must be assigned to only and only one one resident
# TODO accomodate >1 resident per block or 0 residents
for block in blocks:
    for rot in rotations:
        model.AddExactlyOne(block_assigned[(res, block, rot)] for res in residents)

# Each resident must work some rotation each block
for res in residents:
    for block in blocks:
        model.AddExactlyOne(block_assigned[(res, block, rot)] for rot in rotations)


# Creates the solver and solve.
solver = cp_model.CpSolver()
solver.parameters.linearization_level = 0
# Enumerate all solutions.
solver.parameters.enumerate_all_solutions = True

class BlockSchedulePartialSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, block_assigned, residents, blocks, rotations, limit):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._block_assigned = block_assigned
        self._residents = residents
        self._blocks = blocks
        self._rotations = rotations
        self._solution_count = 0
        self._solution_limit = limit

    def on_solution_callback(self):
        self._solution_count += 1
        # print('Solution %i' % self._solution_count)

        # for block in self._blocks:
        #     print(' ', block)
        #     for resident in self._residents:
        #         for rotation in self._rotations:
        #             if self.Value(self._block_assigned[(resident, block, rotation)]):
        #                 print('   ', resident, 'is on', rotation)

        # if self._solution_count >= self._solution_limit:
        #     print('Stop search after %i solutions' % self._solution_limit)
        #     self.StopSearch()

    def solution_count(self):
        return self._solution_count

# Display the first five solutions.
solution_limit = 400_000
solution_printer = BlockSchedulePartialSolutionPrinter(
    block_assigned, residents, blocks, rotations, solution_limit)

solver.Solve(model, solution_printer)


# Statistics.
print('\nStatistics')
print('  - conflicts      : %i' % solver.NumConflicts())
print('  - branches       : %i' % solver.NumBranches())
print('  - wall time      : %f s' % solver.WallTime())
print('  - solutions found: %i' % solution_printer.solution_count())


