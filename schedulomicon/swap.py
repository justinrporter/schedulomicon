"""Swap mode: minimal-change rescheduling against a prior solution.

Given an existing schedule and new requirements, find the smallest set of
changes that satisfies the new constraints (pass 1), then re-optimize the
normal score objective without exceeding that change count (pass 2).
"""

import logging
import warnings

from functools import partial

from . import csts, exceptions, parser, score, solve

logger = logging.getLogger(__name__)


def compute_freeze_pins(mask, old_solution, residents, blocks, rotations,
                        cogrids):
    """Compute the variable pins that freeze a region to an old solution.

    The main grid is pinned cell by cell: for every (resident, block) pair
    with at least one masked rotation, each masked cell is pinned to its old
    value (1 for the pair's old on-assignment, 0 otherwise). Cogrids are
    pinned where the mask determines them completely: a backup (res, block)
    is pinned when the mask covers all rotations for that pair, and a
    vacation (res, week, rot) is pinned when the week's block list is
    nonempty and every listed block is masked for that (res, rot). Sparse
    old solutions are fine — a missing key in a present grid is a
    determined 0.

    Args:
        mask: Boolean ndarray of shape (residents, blocks, rotations), as
            produced by parser.resolve_eligible_field (``field[0]``).
        old_solution: {grid_name: {key_tuple: value}} as returned by
            io.read_solution; may be sparse.
        residents, blocks, rotations: The current model's main dimensions.
        cogrids: The cogrid configs for the current model, as in
            Problem.cogrids; only truthy 'backup'/'vacation' entries (the
            ones solve.solve builds grids for) are projected.

    Returns:
        {grid_name: {key_tuple: 0 or 1}}; grids with no pinned cells are
        omitted entirely.

    Raises:
        exceptions.FreezeError: If a masked (resident, block) pair has no
            valid old on-assignment (resident added mid-year, or its old
            rotation was removed/renamed), or if the region projects onto a
            backup/vacation grid the old solution lacks.
    """

    old_main_on = {
        (res, blk): rot
        for (res, blk, rot), v in old_solution.get('main', {}).items()
        if v != 0 and res in residents and blk in blocks and rot in rotations
    }

    pins = {}

    main_pins = {}
    undetermined = []
    for i, res in enumerate(residents):
        for j, blk in enumerate(blocks):
            masked_rots = [k for k, rot in enumerate(rotations)
                           if mask[i, j, k]]
            if not masked_rots:
                continue

            if (res, blk) not in old_main_on:
                undetermined.append((res, blk))
                continue

            old_rot = old_main_on[res, blk]
            for k in masked_rots:
                main_pins[res, blk, rotations[k]] = \
                    int(rotations[k] == old_rot)

    if undetermined:
        samples = '; '.join(map(str, undetermined[:5]))
        raise exceptions.FreezeError(
            f"Cannot freeze: {len(undetermined)} (resident, block) pair(s) "
            f"in the frozen region have no valid assignment in the old "
            f"solution (e.g. {samples}). This happens when a resident was "
            "added or their old rotation was removed/renamed since the old "
            "solution was produced. Narrow the --freeze selector to exclude "
            "them (e.g. '<selector> and not <resident>').")

    if main_pins:
        pins['main'] = main_pins

    if cogrids.get('backup'):
        backup_keys = [
            (res, blk)
            for i, res in enumerate(residents)
            for j, blk in enumerate(blocks)
            if mask[i, j, :].all()
        ]
        if backup_keys:
            if 'backup' not in old_solution:
                raise exceptions.FreezeError(
                    f"Cannot freeze: the frozen region pins "
                    f"{len(backup_keys)} backup assignment(s) (e.g. "
                    f"{'; '.join(map(str, backup_keys[:5]))}), but the old "
                    "solution has no 'backup' grid. Narrow the --freeze "
                    "selector or use an old solution that includes it.")
            pins['backup'] = {
                key: int(old_solution['backup'].get(key, 0) != 0)
                for key in backup_keys
            }

    if cogrids.get('vacation'):
        vacation_keys = []
        for week, spec in cogrids['vacation']['blocks'].items():
            week_blocks = (spec or {}).get('blocks') or []
            block_idxs = [blocks.index(blk) for blk in week_blocks
                          if blk in blocks]
            if not week_blocks or len(block_idxs) != len(week_blocks):
                continue  # empty/missing block list or unknown block

            for i, res in enumerate(residents):
                for k, rot in enumerate(rotations):
                    if all(mask[i, j, k] for j in block_idxs):
                        vacation_keys.append((res, week, rot))

        if vacation_keys:
            if 'vacation' not in old_solution:
                raise exceptions.FreezeError(
                    f"Cannot freeze: the frozen region pins "
                    f"{len(vacation_keys)} vacation assignment(s) (e.g. "
                    f"{'; '.join(map(str, vacation_keys[:5]))}), but the "
                    "old solution has no 'vacation' grid. Narrow the "
                    "--freeze selector or use an old solution that "
                    "includes it.")
            pins['vacation'] = {
                key: int(old_solution['vacation'].get(key, 0) != 0)
                for key in vacation_keys
            }

    return pins


class FreezeConstraint(csts.Constraint):
    """Pin a set of grid variables to fixed 0/1 values.

    ``pins`` is {grid_name: {key_tuple: 0 or 1}}, as produced by
    compute_freeze_pins. All decisions and error handling happen when the
    pins are computed; apply only adds the equalities to the model.
    """

    def __init__(self, pins):
        self.pins = pins

    def apply(self, model, block_assigned, residents, blocks, rotations,
              grids):
        for grid_name, grid_pins in self.pins.items():
            variables = grids[grid_name]['variables']
            for key, value in grid_pins.items():
                model.Add(variables[key] == value)


def build_freeze_constraint(selector, old_solution, config, groups_array,
                            residents, blocks, rotations, cogrids):
    """Build a FreezeConstraint pinning a selected region to an old solution.

    Args:
        selector: A selector DSL expression (as accepted by --require), e.g.
            ``'Block 1 or Block 2'``; resolved against groups_array.
        old_solution: The prior solution ({grid: {key: value}}, may be
            sparse) whose values the region is pinned to.
        config, groups_array: The loaded YAML config and its group masks.
        residents, blocks, rotations: The current model's main dimensions.
        cogrids: The cogrid configs, as in Problem.cogrids.

    Returns:
        FreezeConstraint: With pins from compute_freeze_pins.

    Raises:
        exceptions.YAMLParseError: If the selector names an unknown
            resident/block/rotation/group.
        exceptions.FreezeError: If the region touches cells the old solution
            does not determine (see compute_freeze_pins).
    """

    field = parser.resolve_eligible_field(
        selector,
        groups_array,
        config['residents'].keys(),
        config['blocks'].keys(),
        config['rotations'].keys()
    )

    pins = compute_freeze_pins(
        field[0], old_solution, residents, blocks, rotations, cogrids)

    return FreezeConstraint(pins)


def build_diff_score_functions(old_solution, residents, blocks, rotations,
                               cogrids):
    """Build per-grid score functions whose sum measures distance from an
    old solution.

    For each grid present in both the old solution and the current model,
    every variable that was on in the old solution scores -1 and every other
    variable scores +1 (via ``default_score``), so the aggregate objective is
    (added variables) - (retained variables). Minimizing it minimizes the
    symmetric difference from the old schedule.

    Grids in the old solution with no counterpart in the current model are
    skipped with a warning; model grids absent from the old solution are
    silently skipped (they contribute nothing to the change count). Old
    assignments whose keys no longer exist in the current config (removed
    residents, renamed rotations, ...) are warned about and ignored.

    Args:
        old_solution: {grid_name: {key_tuple: value}} as returned by
            io.read_solution; may be sparse or dense.
        residents, blocks, rotations: The current model's main dimensions.
        cogrids: The cogrid configs ({'backup': ..., 'vacation': ...}) for
            the current model, as in Problem.cogrids.

    Returns:
        (grid_and_functions, n_valid_old_on): a list of
        ``(grid_name, score_function)`` pairs suitable for solve.solve's
        score_functions / MinTotalScoreConstraint, and the number of old-on
        assignments that are still valid. The minimized objective value o*
        relates to the total flip count d* by ``d* = o* + n_valid_old_on``.
    """

    valid_keys = {
        'main': {
            (res, blk, rot)
            for res in residents for blk in blocks for rot in rotations
        }
    }

    if cogrids.get('backup'):
        valid_keys['backup'] = {
            (res, blk) for res in residents for blk in blocks
        }

    if cogrids.get('vacation'):
        weeks = list(cogrids['vacation']['blocks'])
        valid_keys['vacation'] = {
            (res, week, rot)
            for res in residents for week in weeks for rot in rotations
        }

    grid_and_functions = []
    n_valid_old_on = 0

    for grid_name, old_vars in old_solution.items():
        if grid_name not in valid_keys:
            warnings.warn(
                f"Grid '{grid_name}' from the old solution is not part of "
                "the current model; it is ignored for the change count.")
            continue

        old_on = {k for k, v in old_vars.items() if v != 0}

        stale = sorted(k for k in old_on if k not in valid_keys[grid_name])
        if stale:
            samples = '; '.join(map(str, stale[:5]))
            warnings.warn(
                f"{len(stale)} old assignment(s) in grid '{grid_name}' no "
                f"longer exist in the current config (e.g. {samples}); they "
                "are ignored for the change count.")
            old_on -= set(stale)

        n_valid_old_on += len(old_on)

        grid_and_functions.append((
            grid_name,
            partial(score.objective_from_score_dict,
                    scores={k: -1 for k in old_on},
                    default_score=1)
        ))

    return grid_and_functions, n_valid_old_on


def swap_solve(residents, blocks, rotations, groups_array, cst_list,
               soln_printer, cogrids, score_functions, old_solution,
               max_time_in_mins=None, n_processes=None, hint=None):
    """Solve for the minimal-change schedule relative to an old solution.

    Lexicographic two-pass solve. Pass 1 minimizes the change objective from
    build_diff_score_functions, giving the minimal objective value o*. Pass 2
    (run only when ``score_functions`` is nonempty) re-solves with the change
    objective bounded at o* as a hard constraint and optimizes the caller's
    ``score_functions`` as usual.

    The arguments shared with solve.solve (residents, blocks, rotations,
    groups_array, cst_list, soln_printer, cogrids, max_time_in_mins,
    n_processes) are applied identically in both passes, so a solution limit
    in the printer prototype applies per pass.

    Args:
        score_functions: The user's score objective for pass 2; empty means
            pass 2 is skipped.
        old_solution: The prior solution to stay close to.
        hint: Optional solver hint for pass 1; defaults to old_solution.

    Returns:
        (status, solver, solution_printer, model, wall_runtime, d_star):
        the solve.solve results of the last pass run, plus d_star, the
        number of variable flips away from the (valid part of the) old
        solution — o* + n_valid_old_on — or None if pass 1 found no
        solution.
    """

    grid_and_functions, n_valid_old_on = build_diff_score_functions(
        old_solution, residents, blocks, rotations, cogrids)

    print("Pass 1: minimizing changes from the old schedule")
    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents, blocks, rotations, groups_array, cst_list,
        soln_printer=soln_printer,
        cogrids=cogrids,
        score_functions=grid_and_functions,
        max_time_in_mins=max_time_in_mins,
        n_processes=n_processes,
        hint=hint if hint is not None else old_solution,
    )

    if status not in ('OPTIMAL', 'FEASIBLE'):
        return status, solver, solution_printer, model, wall_runtime, None

    if status == 'FEASIBLE':
        warnings.warn(
            "Pass 1 stopped before proving optimality (status FEASIBLE); "
            "the change count is an upper bound, not the minimum.")

    o_star = int(round(solver.ObjectiveValue()))
    d_star = o_star + n_valid_old_on

    if not score_functions:
        return status, solver, solution_printer, model, wall_runtime, d_star

    print("Pass 2: optimizing score subject to the pass-1 change bound")
    pass2_cst_list = list(cst_list) + [
        csts.MinTotalScoreConstraint(
            grid_and_functions=grid_and_functions, min_score=o_star)
    ]

    status, solver, pass2_printer, model, pass2_runtime = solve.solve(
        residents, blocks, rotations, groups_array, pass2_cst_list,
        soln_printer=soln_printer,
        cogrids=cogrids,
        score_functions=score_functions,
        max_time_in_mins=max_time_in_mins,
        n_processes=n_processes,
        hint=solution_printer._solutions[-1],
    )

    return (status, solver, pass2_printer, model,
            wall_runtime + pass2_runtime, d_star)


def format_diff_report(old_solution, new_solution):
    """Render a human-readable summary of the differences between two
    solutions.

    The main grid is reported one line per (resident, block) whose assigned
    rotation changed ('R1, Block 7: Cardiology -> ICU'); other grids
    (backup, vacation) list added (+) and dropped (-) assignments. Only
    grids present in both solutions are compared. Old assignments whose
    (resident, block) pair or key no longer exists in the new solution are
    tallied in a footer rather than reported as changes.

    Args:
        old_solution: {grid: {key_tuple: value}}; may be sparse (missing
            key = 0), as read from a .json solution.
        new_solution: same shape; expected dense (a full key space), as
            produced by a solution printer's solution_dict().

    Returns:
        str: The report, starting with per-grid and total change counts, or
        'No changes.' when the solutions agree.
    """

    grid_counts = {}
    sections = []
    n_noncomparable = 0

    for grid_name, old_vars in old_solution.items():
        if grid_name not in new_solution:
            continue
        new_vars = new_solution[grid_name]
        section = []

        if grid_name == 'main':
            old_assign = {(res, blk): rot
                          for (res, blk, rot), v in old_vars.items() if v != 0}
            new_assign = {(res, blk): rot
                          for (res, blk, rot), v in new_vars.items() if v != 0}

            n_changes = 0
            for (res, blk), old_rot in sorted(old_assign.items()):
                if (res, blk) not in new_assign:
                    n_noncomparable += 1
                    continue
                new_rot = new_assign[(res, blk)]
                if new_rot != old_rot:
                    section.append(f"  {res}, {blk}: {old_rot} -> {new_rot}")
                    n_changes += 1
            grid_counts[grid_name] = n_changes

        else:
            old_on = {k for k, v in old_vars.items() if v != 0}
            new_on = {k for k, v in new_vars.items() if v != 0}

            noncomparable = {k for k in old_on if k not in new_vars}
            n_noncomparable += len(noncomparable)
            old_on -= noncomparable

            added = sorted(new_on - old_on)
            dropped = sorted(old_on - new_on)
            for k in added:
                section.append("  + " + ", ".join(map(str, k)))
            for k in dropped:
                section.append("  - " + ", ".join(map(str, k)))
            grid_counts[grid_name] = len(added) + len(dropped)

        if section:
            sections.append((grid_name, section))

    total = sum(grid_counts.values())

    lines = []
    if total == 0:
        lines.append("No changes.")
    else:
        per_grid = ", ".join(
            f"{g}: {ct}" for g, ct in grid_counts.items() if ct)
        lines.append(f"Changes from old schedule: {total} ({per_grid})")
        for grid_name, section in sections:
            lines.append("")
            lines.append(f"{grid_name}:")
            lines.extend(section)

    if n_noncomparable:
        lines.append("")
        lines.append(
            f"{n_noncomparable} old assignment(s) could not be compared "
            "(resident/block/rotation no longer in the schedule).")

    return "\n".join(lines)
