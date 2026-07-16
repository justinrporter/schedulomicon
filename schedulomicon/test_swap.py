import os
import warnings

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml

from ortools.sat.python import cp_model

from . import csts, exceptions, io, solver, swap


RESIDENTS = ['R1', 'R2']
BLOCKS = ['Bl1', 'Bl2']
ROTATIONS = ['Ro1', 'Ro2']


def grid_functions_by_name(grid_and_functions):
    d = dict(grid_and_functions)
    assert len(d) == len(grid_and_functions), "duplicate grid entries"
    return d


class TestBuildDiffScoreFunctions:

    def test_main_grid_scores_and_count(self):
        old_solution = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl2', 'Ro2'): 1,
            ('R2', 'Bl1', 'Ro2'): 1,
            ('R2', 'Bl2', 'Ro1'): 1,
        }}

        grid_and_functions, n_valid_old_on = swap.build_diff_score_functions(
            old_solution, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert n_valid_old_on == 4
        fns = grid_functions_by_name(grid_and_functions)
        assert set(fns) == {'main'}
        assert fns['main'].keywords['scores'] == {
            k: -1 for k in old_solution['main']
        }

    def test_partial_evaluates_added_minus_retained(self):
        old_solution = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R2', 'Bl1', 'Ro2'): 1,
        }}

        grid_and_functions, _ = swap.build_diff_score_functions(
            old_solution, RESIDENTS, ['Bl1'], ROTATIONS, cogrids={})
        fn = grid_functions_by_name(grid_and_functions)['main']

        # identical to old: both old-on retained, nothing added
        same = {
            ('R1', 'Bl1', 'Ro1'): 1, ('R1', 'Bl1', 'Ro2'): 0,
            ('R2', 'Bl1', 'Ro1'): 0, ('R2', 'Bl1', 'Ro2'): 1,
        }
        assert fn(same) == -2

        # R2 moves Ro2 -> Ro1: one added (+1, charged via default_score),
        # one old-on dropped (its -1 no longer earned)
        changed = {
            ('R1', 'Bl1', 'Ro1'): 1, ('R1', 'Bl1', 'Ro2'): 0,
            ('R2', 'Bl1', 'Ro1'): 1, ('R2', 'Bl1', 'Ro2'): 0,
        }
        assert fn(changed) == 0

    def test_dense_explicit_zeros_not_old_on(self):
        old_solution = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl1', 'Ro2'): 0,
        }}

        grid_and_functions, n_valid_old_on = swap.build_diff_score_functions(
            old_solution, RESIDENTS, ['Bl1'], ROTATIONS, cogrids={})

        assert n_valid_old_on == 1
        fn = grid_functions_by_name(grid_and_functions)['main']
        assert fn.keywords['scores'] == {('R1', 'Bl1', 'Ro1'): -1}

    def test_backup_and_vacation_grids_included(self):
        old_solution = {
            'main': {('R1', 'Bl1', 'Ro1'): 1},
            'backup': {('R1', 'Bl1'): 1},
            'vacation': {('R1', 'Week 1', 'Ro1'): 1},
        }
        cogrids = {
            'backup': {'coverage': 1},
            'vacation': {'blocks': {'Week 1': {'blocks': ['Bl1']},
                                    'Week 2': {'blocks': ['Bl2']}},
                         'pools': {}},
        }

        grid_and_functions, n_valid_old_on = swap.build_diff_score_functions(
            old_solution, RESIDENTS, BLOCKS, ROTATIONS, cogrids=cogrids)

        fns = grid_functions_by_name(grid_and_functions)
        assert set(fns) == {'main', 'backup', 'vacation'}
        assert n_valid_old_on == 3
        assert fns['backup'].keywords['scores'] == {('R1', 'Bl1'): -1}
        assert fns['vacation'].keywords['scores'] == {
            ('R1', 'Week 1', 'Ro1'): -1}

    def test_old_grid_absent_from_model_warns_and_skips(self):
        old_solution = {
            'main': {('R1', 'Bl1', 'Ro1'): 1},
            'backup': {('R1', 'Bl1'): 1},
        }

        with pytest.warns(UserWarning, match='backup'):
            grid_and_functions, n_valid_old_on = \
                swap.build_diff_score_functions(
                    old_solution, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert set(grid_functions_by_name(grid_and_functions)) == {'main'}
        assert n_valid_old_on == 1

    def test_model_grid_absent_from_old_silently_skipped(self):
        old_solution = {'main': {('R1', 'Bl1', 'Ro1'): 1}}
        cogrids = {
            'vacation': {'blocks': {'Week 1': {'blocks': ['Bl1']}},
                         'pools': {}},
        }

        with warnings.catch_warnings():
            warnings.simplefilter('error')
            grid_and_functions, n_valid_old_on = \
                swap.build_diff_score_functions(
                    old_solution, RESIDENTS, BLOCKS, ROTATIONS,
                    cogrids=cogrids)

        assert set(grid_functions_by_name(grid_and_functions)) == {'main'}
        assert n_valid_old_on == 1

    def test_stale_keys_warned_and_excluded(self):
        old_solution = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R9', 'Bl1', 'Ro1'): 1,        # resident no longer exists
            ('R2', 'Bl1', 'Old Rot'): 1,    # rotation renamed away
        }}

        with pytest.warns(UserWarning) as record:
            grid_and_functions, n_valid_old_on = \
                swap.build_diff_score_functions(
                    old_solution, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        messages = [str(w.message) for w in record]
        stale_msgs = [m for m in messages if '2' in m and 'main' in m]
        assert stale_msgs, f"no stale-key warning found in {messages}"
        assert any('R9' in m or 'Old Rot' in m for m in stale_msgs), \
            "stale-key warning should include sample keys"

        assert n_valid_old_on == 1
        fn = grid_functions_by_name(grid_and_functions)['main']
        assert fn.keywords['scores'] == {('R1', 'Bl1', 'Ro1'): -1}


class TestComputeFreezePins:

    OLD = {'main': {
        ('R1', 'Bl1', 'Ro1'): 1,
        ('R1', 'Bl2', 'Ro2'): 1,
        ('R2', 'Bl1', 'Ro2'): 1,
        ('R2', 'Bl2', 'Ro1'): 1,
    }}

    BACKUP_COGRIDS = {'backup': {'coverage': 1}}
    VACATION_COGRIDS = {'vacation': {
        'blocks': {'Week 1': {'blocks': ['Bl1']},
                   'Week 2': {'blocks': ['Bl1', 'Bl2']}},
        'pools': {},
    }}

    def _mask(self):
        return np.zeros((len(RESIDENTS), len(BLOCKS), len(ROTATIONS)),
                        dtype=bool)

    def test_full_block_mask_pins_on_and_off_cells(self):
        mask = self._mask()
        mask[:, 0, :] = True  # all of Bl1

        pins = swap.compute_freeze_pins(
            mask, self.OLD, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert pins == {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl1', 'Ro2'): 0,
            ('R2', 'Bl1', 'Ro1'): 0,
            ('R2', 'Bl1', 'Ro2'): 1,
        }}

    def test_partial_mask_pins_only_masked_cells(self):
        mask = self._mask()
        mask[:, :, 0] = True  # only Ro1, in every block

        pins = swap.compute_freeze_pins(
            mask, self.OLD, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert pins == {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl2', 'Ro1'): 0,
            ('R2', 'Bl1', 'Ro1'): 0,
            ('R2', 'Bl2', 'Ro1'): 1,
        }}

    def test_pair_missing_from_old_raises(self):
        mask = self._mask()
        mask[:, 0, :] = True
        old = {'main': {('R1', 'Bl1', 'Ro1'): 1}}  # nothing for R2

        with pytest.raises(exceptions.FreezeError, match=r"R2.*Bl1"):
            swap.compute_freeze_pins(
                mask, old, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

    def test_pair_with_removed_rotation_raises(self):
        mask = self._mask()
        mask[:, 0, :] = True
        old = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R2', 'Bl1', 'Old Rot'): 1,  # rotation no longer in the config
        }}

        with pytest.raises(exceptions.FreezeError, match=r"R2.*Bl1"):
            swap.compute_freeze_pins(
                mask, old, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

    def test_backup_pinned_when_all_rotations_masked(self):
        mask = self._mask()
        mask[:, 0, :] = True
        old = dict(self.OLD)
        old['backup'] = {('R1', 'Bl1'): 1}  # sparse: R2/Bl1 is 0

        pins = swap.compute_freeze_pins(
            mask, old, RESIDENTS, BLOCKS, ROTATIONS,
            cogrids=self.BACKUP_COGRIDS)

        assert pins['backup'] == {('R1', 'Bl1'): 1, ('R2', 'Bl1'): 0}

    def test_backup_not_projected_for_partial_masks(self):
        mask = self._mask()
        mask[:, :, 0] = True  # no (res, blk) has all rotations masked
        old = dict(self.OLD)
        old['backup'] = {('R1', 'Bl1'): 1}

        pins = swap.compute_freeze_pins(
            mask, old, RESIDENTS, BLOCKS, ROTATIONS,
            cogrids=self.BACKUP_COGRIDS)

        assert 'backup' not in pins

    def test_backup_grid_missing_from_old_raises(self):
        mask = self._mask()
        mask[:, 0, :] = True

        with pytest.raises(exceptions.FreezeError, match='backup'):
            swap.compute_freeze_pins(
                mask, self.OLD, RESIDENTS, BLOCKS, ROTATIONS,
                cogrids=self.BACKUP_COGRIDS)

    def test_vacation_week_pinned_when_all_its_blocks_masked(self):
        mask = self._mask()
        mask[:, 0, :] = True  # Bl1 only: Week 1 frozen, Week 2 not
        old = dict(self.OLD)
        old['vacation'] = {('R1', 'Week 1', 'Ro1'): 1}

        pins = swap.compute_freeze_pins(
            mask, old, RESIDENTS, BLOCKS, ROTATIONS,
            cogrids=self.VACATION_COGRIDS)

        assert pins['vacation'] == {
            ('R1', 'Week 1', 'Ro1'): 1,
            ('R1', 'Week 1', 'Ro2'): 0,
            ('R2', 'Week 1', 'Ro1'): 0,
            ('R2', 'Week 1', 'Ro2'): 0,
        }

    def test_multi_block_week_pinned_only_when_fully_masked(self):
        mask = self._mask()
        mask[:, :, :] = True  # everything: Week 2 (Bl1 + Bl2) frozen too
        old = dict(self.OLD)
        old['vacation'] = {('R1', 'Week 1', 'Ro1'): 1}

        pins = swap.compute_freeze_pins(
            mask, old, RESIDENTS, BLOCKS, ROTATIONS,
            cogrids=self.VACATION_COGRIDS)

        week2_keys = {k for k in pins['vacation'] if k[1] == 'Week 2'}
        assert week2_keys == {
            (res, 'Week 2', rot) for res in RESIDENTS for rot in ROTATIONS}

    def test_vacation_grid_missing_from_old_raises(self):
        mask = self._mask()
        mask[:, 0, :] = True

        with pytest.raises(exceptions.FreezeError, match='vacation'):
            swap.compute_freeze_pins(
                mask, self.OLD, RESIDENTS, BLOCKS, ROTATIONS,
                cogrids=self.VACATION_COGRIDS)

    def test_no_cogrids_main_pins_only(self):
        mask = self._mask()
        mask[:, 0, :] = True

        pins = swap.compute_freeze_pins(
            mask, self.OLD, RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert set(pins) == {'main'}

    def test_all_false_mask_yields_no_pins(self):
        cogrids = {**self.BACKUP_COGRIDS, **self.VACATION_COGRIDS}

        pins = swap.compute_freeze_pins(
            self._mask(), self.OLD, RESIDENTS, BLOCKS, ROTATIONS,
            cogrids=cogrids)

        assert pins == {}


class TestBuildFreezeConstraint:

    OLD = TestComputeFreezePins.OLD

    def _config(self):
        config = {
            'residents': {'R1': {}, 'R2': {}},
            'rotations': {'Ro1': {}, 'Ro2': {}},
            'blocks': {'Bl1': {}, 'Bl2': {}},
        }
        _, _, _, _, groups_array = io.process_config(config)
        return config, groups_array

    def test_selector_resolves_to_expected_pins(self):
        config, groups_array = self._config()

        cst = swap.build_freeze_constraint(
            'Bl1', self.OLD, config, groups_array,
            RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

        assert isinstance(cst, swap.FreezeConstraint)
        assert cst.pins == {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl1', 'Ro2'): 0,
            ('R2', 'Bl1', 'Ro1'): 0,
            ('R2', 'Bl1', 'Ro2'): 1,
        }}

    def test_unknown_identifier_raises(self):
        config, groups_array = self._config()

        with pytest.raises(exceptions.YAMLParseError):
            swap.build_freeze_constraint(
                'No Such Thing', self.OLD, config, groups_array,
                RESIDENTS, BLOCKS, ROTATIONS, cogrids={})

    def test_apply_forces_pinned_values(self):
        model = cp_model.CpModel()
        variables = {
            key: model.NewBoolVar(str(key))
            for key in [('R1', 'Bl1', 'Ro1'), ('R1', 'Bl1', 'Ro2')]
        }
        grids = {'main': {'variables': variables}}

        cst = swap.FreezeConstraint(
            {'main': {('R1', 'Bl1', 'Ro1'): 1, ('R1', 'Bl1', 'Ro2'): 0}})
        cst.apply(model, block_assigned=variables, residents=[], blocks=[],
                  rotations=[], grids=grids)

        cp_solver = cp_model.CpSolver()
        assert cp_solver.StatusName(cp_solver.Solve(model)) == 'OPTIMAL'
        assert cp_solver.Value(variables[('R1', 'Bl1', 'Ro1')]) == 1
        assert cp_solver.Value(variables[('R1', 'Bl1', 'Ro2')]) == 0

    def test_apply_conflict_is_infeasible(self):
        model = cp_model.CpModel()
        var = model.NewBoolVar('v')
        grids = {'main': {'variables': {('k',): var}}}
        model.Add(var == 1)

        cst = swap.FreezeConstraint({'main': {('k',): 0}})
        cst.apply(model, block_assigned=grids['main']['variables'],
                  residents=[], blocks=[], rotations=[], grids=grids)

        cp_solver = cp_model.CpSolver()
        assert cp_solver.StatusName(cp_solver.Solve(model)) == 'INFEASIBLE'


class TestFormatDiffReport:

    def test_full_report_across_grids(self):
        # sparse old (nonzero only, as read from .json)
        old = {
            'main': {
                ('Resident A', 'Block 7', 'Cardiology'): 1,
                ('Resident B', 'Block 7', 'ICU'): 1,
            },
            'backup': {('Resident A', 'Block 7'): 1},
            'vacation': {('Resident A', 'Week 1', 'Cardiology'): 1},
        }
        # dense new (as produced by solution_dict())
        new = {
            'main': {
                ('Resident A', 'Block 7', 'Cardiology'): 0,
                ('Resident A', 'Block 7', 'ICU'): 1,
                ('Resident B', 'Block 7', 'Cardiology'): 0,
                ('Resident B', 'Block 7', 'ICU'): 1,
            },
            'backup': {
                ('Resident A', 'Block 7'): 0,
                ('Resident B', 'Block 7'): 1,
            },
            'vacation': {
                ('Resident A', 'Week 1', 'Cardiology'): 0,
                ('Resident A', 'Week 2', 'Cardiology'): 1,
            },
        }

        report = swap.format_diff_report(old, new)

        # main: changed rows listed old -> new; unchanged rows not listed
        assert 'Resident A, Block 7: Cardiology -> ICU' in report
        assert 'Resident B, Block 7: ICU' not in report

        # backup / vacation: added (+) and dropped (-) entries
        assert '+ Resident B, Block 7' in report
        assert '- Resident A, Block 7' in report
        assert '+ Resident A, Week 2, Cardiology' in report
        assert '- Resident A, Week 1, Cardiology' in report

        # per-grid and total counts in the header
        header = report.splitlines()[0]
        assert '5' in header
        assert 'main: 1' in header
        assert 'backup: 2' in header
        assert 'vacation: 2' in header

    def test_noncomparable_old_pairs_counted_in_footer(self):
        old = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R9', 'Bl1', 'Ro1'): 1,  # R9 removed from the config
        }}
        new = {'main': {
            ('R1', 'Bl1', 'Ro1'): 0,
            ('R1', 'Bl1', 'Ro2'): 1,
        }}

        report = swap.format_diff_report(old, new)

        assert 'R1, Bl1: Ro1 -> Ro2' in report
        assert '1 old assignment(s) could not be compared' in report

    def test_no_changes(self):
        old = {'main': {('R1', 'Bl1', 'Ro1'): 1}}
        new = {'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl1', 'Ro2'): 0,
        }}

        assert 'No changes.' in swap.format_diff_report(old, new)


def _pass_result(status, objective=0.0, solutions=None):
    solver = MagicMock()
    solver.ObjectiveValue.return_value = objective
    printer = MagicMock()
    printer._solutions = solutions if solutions is not None else []
    return (status, solver, printer, MagicMock(), 1.0)


def _swap_solve(mock_solve, score_functions, old_solution, cst_list=None,
                hint=None):
    return swap.swap_solve(
        residents=['R1'], blocks=['Bl1'], rotations=['Ro1', 'Ro2'],
        groups_array={},
        cst_list=cst_list if cst_list is not None else [],
        soln_printer=MagicMock(),
        cogrids={},
        score_functions=score_functions,
        old_solution=old_solution,
        hint=hint,
    )


@patch('schedulomicon.solve.solve')
class TestSwapSolve:

    OLD = {'main': {('R1', 'Bl1', 'Ro1'): 1}}
    PASS1_SOLN = {'main': {('R1', 'Bl1', 'Ro1'): 0, ('R1', 'Bl1', 'Ro2'): 1}}

    def test_two_pass_plumbing(self, mock_solve):
        pass1 = _pass_result('OPTIMAL', objective=0.0,
                             solutions=[self.PASS1_SOLN])
        pass2 = _pass_result('OPTIMAL', solutions=[self.PASS1_SOLN])
        mock_solve.side_effect = [pass1, pass2]

        user_score_functions = [('main', lambda v: 0)]
        cst_list = []

        status, solver, printer, model, runtime, d_star = _swap_solve(
            mock_solve, user_score_functions, self.OLD, cst_list=cst_list)

        assert mock_solve.call_count == 2

        # pass 1: diff score functions, old solution as hint
        _, kwargs1 = mock_solve.call_args_list[0]
        assert kwargs1['hint'] == self.OLD
        p1_fns = kwargs1['score_functions']
        assert [g for g, _ in p1_fns] == ['main']
        assert p1_fns[0][1].keywords['scores'] == {('R1', 'Bl1', 'Ro1'): -1}

        # pass 2: change bound appended, user objective, pass-1 soln as hint
        args2, kwargs2 = mock_solve.call_args_list[1]
        assert kwargs2['score_functions'] is user_score_functions
        assert kwargs2['hint'] == self.PASS1_SOLN
        bound = args2[4][-1]  # cst_list is the 5th positional arg
        assert isinstance(bound, csts.MinTotalScoreConstraint)
        assert bound.min_score == 0
        assert bound.grid_and_functions == p1_fns
        assert cst_list == [], "caller's cst_list must not be mutated"

        # results are pass 2's; d_star = o_star + n_valid_old_on = 0 + 1
        assert status == 'OPTIMAL'
        assert printer is pass2[2]
        assert d_star == 1

    def test_pass2_skipped_without_score_functions(self, mock_solve):
        pass1 = _pass_result('OPTIMAL', objective=0.0,
                             solutions=[self.PASS1_SOLN])
        mock_solve.side_effect = [pass1]

        status, solver, printer, model, runtime, d_star = _swap_solve(
            mock_solve, [], self.OLD)

        assert mock_solve.call_count == 1
        assert printer is pass1[2]
        assert d_star == 1

    def test_infeasible_pass1_short_circuits(self, mock_solve):
        pass1 = _pass_result('INFEASIBLE')
        mock_solve.side_effect = [pass1]

        status, solver, printer, model, runtime, d_star = _swap_solve(
            mock_solve, [('main', lambda v: 0)], self.OLD)

        assert mock_solve.call_count == 1
        assert status == 'INFEASIBLE'
        assert d_star is None

    def test_feasible_pass1_warns_upper_bound(self, mock_solve):
        pass1 = _pass_result('FEASIBLE', objective=0.0,
                             solutions=[self.PASS1_SOLN])
        mock_solve.side_effect = [pass1]

        with pytest.warns(UserWarning, match='upper bound'):
            _swap_solve(mock_solve, [], self.OLD)

    def test_explicit_hint_overrides_old_solution(self, mock_solve):
        pass1 = _pass_result('OPTIMAL', objective=0.0,
                             solutions=[self.PASS1_SOLN])
        mock_solve.side_effect = [pass1]
        my_hint = {'main': {('R1', 'Bl1', 'Ro2'): 1}}

        _swap_solve(mock_solve, [], self.OLD, hint=my_hint)

        _, kwargs1 = mock_solve.call_args_list[0]
        assert kwargs1['hint'] == my_hint


def _write_yaml_config(tmp_path, config):
    path = tmp_path / 'config.yml'
    with open(path, 'w') as f:
        yaml.dump(config, f)
    return str(path)


class TestSwapEndToEnd:
    """Full CP-SAT integration tests for the swap subcommand."""

    TINY_CONFIG = {
        'residents': {'R1': {}, 'R2': {}},
        'rotations': {'Rotation1': {}, 'Rotation2': {}},
        'blocks': {'Block1': {}, 'Block2': {}},
    }

    def _solve_tiny(self, tmp_path):
        config_path = _write_yaml_config(tmp_path, self.TINY_CONFIG)
        old_file = str(tmp_path / 'old.json')

        assert solver.main(
            ['solve', '--config', config_path, '--results', old_file]) == 1

        old = io.read_solution(old_file)
        old_rot = next(rot for (res, blk, rot), v in old['main'].items()
                       if res == 'R1' and blk == 'Block1' and v)
        return config_path, old_file, old, old_rot

    def test_freeze_error_raised_before_solving(self, tmp_path):
        config_path = _write_yaml_config(tmp_path, self.TINY_CONFIG)
        old_file = str(tmp_path / 'old.json')
        io.write_solution(old_file, {'main': {
            ('R1', 'Block1', 'Rotation1'): 1,
            ('R1', 'Block2', 'Rotation2'): 1,
        }})  # nothing for R2: freezing Block1 is undetermined

        with patch('schedulomicon.solve.solve') as mock_solve:
            with pytest.raises(exceptions.FreezeError, match=r"R2.*Block1"):
                solver.main([
                    'swap', '--config', config_path,
                    '--minimize-changes-from', old_file,
                    '--freeze', 'Block1',
                    '--results', str(tmp_path / 'new.json'),
                ])
            mock_solve.assert_not_called()

    def test_require_moves_only_target_cell(self, tmp_path):
        config_path, old_file, old, old_rot = self._solve_tiny(tmp_path)
        new_file = str(tmp_path / 'new.json')

        assert solver.main([
            'swap', '--config', config_path,
            '--minimize-changes-from', old_file,
            '--require', f'sum == 0: R1 and Block1 and {old_rot}',
            '--results', new_file,
        ]) == 1

        new = io.read_solution(new_file)
        assert new['main'].get(('R1', 'Block1', old_rot), 0) == 0

        # the minimal change set touches only R1/Block1
        changed = {
            k for k in set(old['main']) | set(new['main'])
            if old['main'].get(k, 0) != new['main'].get(k, 0)
        }
        assert changed, "the required cell must have changed"
        assert {(res, blk) for res, blk, _ in changed} == {('R1', 'Block1')}

    def test_satisfied_require_reproduces_old_schedule(self, tmp_path, capsys):
        config_path, old_file, old, old_rot = self._solve_tiny(tmp_path)
        new_file = str(tmp_path / 'new.json')

        assert solver.main([
            'swap', '--config', config_path,
            '--minimize-changes-from', old_file,
            '--require', f'sum == 1: R1 and Block1 and {old_rot}',
            '--results', new_file,
        ]) == 1

        out = capsys.readouterr().out
        assert 'Minimal changes (variable flips) from old schedule: 0' in out
        assert 'No changes.' in out
        assert io.read_solution(new_file) == old

    def test_pass2_optimizes_within_change_bound(self, tmp_path, capsys):
        config_path = _write_yaml_config(tmp_path, {
            'residents': {'R1': {}},
            'rotations': {'A': {}, 'B': {}, 'C': {}},
            'blocks': {'Bl1': {}},
        })

        old_file = str(tmp_path / 'old.json')
        io.write_solution(old_file, {'main': {('R1', 'Bl1', 'A'): 1}})

        # scores are minimized: C (1) beats B (5)
        rankings_file = tmp_path / 'rankings.csv'
        rankings_file.write_text(',A,B,C\nR1,0,5,1\n')

        new_file = str(tmp_path / 'new.json')
        assert solver.main([
            'swap', '--config', config_path,
            '--minimize-changes-from', old_file,
            '--require', 'sum == 0: A',
            '--rankings', str(rankings_file),
            '--results', new_file,
        ]) == 1

        new = io.read_solution(new_file)
        assert new['main'] == {('R1', 'Bl1', 'C'): 1}

        out = capsys.readouterr().out
        assert 'Minimal changes (variable flips) from old schedule: 2' in out

    def test_freeze_pins_frozen_region(self, tmp_path):
        config_path, old_file, old, old_rot = self._solve_tiny(tmp_path)
        new_file = str(tmp_path / 'new.json')

        old_b2_rot = next(rot for (res, blk, rot), v in old['main'].items()
                          if res == 'R1' and blk == 'Block2' and v)

        assert solver.main([
            'swap', '--config', config_path,
            '--minimize-changes-from', old_file,
            '--freeze', 'Block1',
            '--require', f'sum == 0: R1 and Block2 and {old_b2_rot}',
            '--results', new_file,
        ]) == 1

        new = io.read_solution(new_file)

        # the frozen block is identical to the old solution
        for res in RESIDENTS:
            for rot in ('Rotation1', 'Rotation2'):
                key = (res, 'Block1', rot)
                assert new['main'].get(key, 0) == old['main'].get(key, 0)

        # the required cell moved, and only R1/Block2 changed
        assert new['main'].get(('R1', 'Block2', old_b2_rot), 0) == 0
        changed = {
            k for k in set(old['main']) | set(new['main'])
            if old['main'].get(k, 0) != new['main'].get(k, 0)
        }
        assert {(res, blk) for res, blk, _ in changed} == {('R1', 'Block2')}

    def test_freeze_conflicting_require_is_infeasible(self, tmp_path):
        config_path, old_file, old, old_rot = self._solve_tiny(tmp_path)
        new_file = str(tmp_path / 'new.json')

        assert solver.main([
            'swap', '--config', config_path,
            '--minimize-changes-from', old_file,
            '--freeze', 'Block1',
            '--require', f'sum == 0: R1 and Block1 and {old_rot}',
            '--results', new_file,
        ]) == 0
        assert not os.path.exists(new_file)

    def test_example_config_freeze(self, tmp_path, capsys):
        example_config = os.path.join(
            os.path.dirname(__file__), '..', 'examples', 'example_config.yml'
        )
        old_file = str(tmp_path / 'old.json')
        new_file = str(tmp_path / 'new.json')

        assert solver.main(
            ['solve', '--config', example_config, '--results', old_file]) == 1

        old = io.read_solution(old_file)
        res, blk, rot = next((res, blk, rot)
                             for (res, blk, rot), v in old['main'].items()
                             if v and blk == 'Fall')

        assert solver.main([
            'swap', '--config', example_config,
            '--minimize-changes-from', old_file,
            '--freeze', 'Spring or Summer',
            '--require', f'sum == 0: {res} and Fall and {rot}',
            '--results', new_file,
        ]) == 1

        new = io.read_solution(new_file)

        # frozen main cells (Spring/Summer) identical to old
        frozen_keys = {
            k for k in set(old['main']) | set(new['main'])
            if k[1] in ('Spring', 'Summer')
        }
        for k in frozen_keys:
            assert new['main'].get(k, 0) == old['main'].get(k, 0), k

        # Weeks 1-2 map 1:1 to Spring/Summer, so vacation is frozen too
        frozen_vac_keys = {
            k for k in set(old['vacation']) | set(new['vacation'])
            if k[1] in ('Week 1', 'Week 2')
        }
        for k in frozen_vac_keys:
            assert new['vacation'].get(k, 0) == old['vacation'].get(k, 0), k

        # the diff report mentions nothing in the frozen region
        out = capsys.readouterr().out
        report = out[out.rindex('Changes from old schedule'):]
        for token in ('Spring', 'Summer', 'Week 1', 'Week 2'):
            assert token not in report

    def test_example_config_swap(self, tmp_path):
        example_config = os.path.join(
            os.path.dirname(__file__), '..', 'examples', 'example_config.yml'
        )
        old_file = str(tmp_path / 'old.json')
        new_file = str(tmp_path / 'new.json')

        assert solver.main(
            ['solve', '--config', example_config, '--results', old_file]) == 1

        old = io.read_solution(old_file)
        assert 'vacation' in old, "example config should produce a vacation grid"
        res, blk, rot = next(k for k, v in old['main'].items() if v)

        assert solver.main([
            'swap', '--config', example_config,
            '--minimize-changes-from', old_file,
            '--require', f'sum == 0: {res} and {blk} and {rot}',
            '--results', new_file,
        ]) == 1

        new = io.read_solution(new_file)
        assert new['main'].get((res, blk, rot), 0) == 0
        assert 'vacation' in new
