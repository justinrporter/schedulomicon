import os
import tempfile
import pytest
import yaml
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from io import StringIO

from schedulomicon import solver, io, csts, solve, callback, score


@pytest.fixture
def temp_directory():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def basic_config_file(temp_directory):
    """Create a basic configuration file for testing."""
    config = {
        'residents': {
            'R1': {'groups': ['CA1']},
            'R2': {'groups': ['CA1']},
        },
        'rotations': {
            'Rotation1': {'groups': ['group1']},
            'Rotation2': {'groups': ['group1']},
        },
        'blocks': {
            'Block1': {},
            'Block2': {},
        }
    }
    
    config_path = os.path.join(temp_directory, 'test_config.yml')
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    
    return config_path


@pytest.fixture
def coverage_min_file(temp_directory):
    """Create a coverage minimum CSV file for testing."""
    data = {
        'Block1': {'Rotation1': 1, 'Rotation2': 0},
        'Block2': {'Rotation1': 0, 'Rotation2': 1}
    }
    df = pd.DataFrame(data)
    
    file_path = os.path.join(temp_directory, 'coverage_min.csv')
    df.to_csv(file_path)
    
    return file_path


@pytest.fixture
def coverage_max_file(temp_directory):
    """Create a coverage maximum CSV file for testing."""
    data = {
        'Block1': {'Rotation1': 1, 'Rotation2': 1},
        'Block2': {'Rotation1': 1, 'Rotation2': 1}
    }
    df = pd.DataFrame(data)
    
    file_path = os.path.join(temp_directory, 'coverage_max.csv')
    df.to_csv(file_path)
    
    return file_path


@pytest.fixture
def rotation_pins_file(temp_directory):
    """Create a rotation pins CSV file for testing."""
    data = {
        'Block1': {'R1': 'Rotation1', 'R2': None},
        'Block2': {'R1': None, 'R2': 'Rotation2'}
    }
    df = pd.DataFrame(data)
    
    file_path = os.path.join(temp_directory, 'rotation_pins.csv')
    df.to_csv(file_path)
    
    return file_path


@pytest.fixture
def rankings_file(temp_directory):
    """Create a rankings CSV file for testing."""
    data = {
        'Rotation1': {'R1': 10, 'R2': 5},
        'Rotation2': {'R1': 3, 'R2': 8}
    }
    df = pd.DataFrame(data)
    
    file_path = os.path.join(temp_directory, 'rankings.csv')
    df.to_csv(file_path)
    
    return file_path


@pytest.fixture
def score_list_file(temp_directory):
    """Create a score list CSV file for testing."""
    data = [
        ['R1', 'Block1', 'Rotation1', 5],
        ['R1', 'Block2', 'Rotation2', 3],
        ['R2', 'Block1', 'Rotation2', 4],
        ['R2', 'Block2', 'Rotation1', 2]
    ]
    df = pd.DataFrame(data, columns=['Resident', 'Block', 'Rotation', 'Score'])
    
    file_path = os.path.join(temp_directory, 'score_list.csv')
    df.to_csv(file_path, index=False)
    
    return file_path


@pytest.fixture
def block_resident_ranking_file(temp_directory):
    """Create a block-resident ranking CSV file for testing."""
    data = {
        'R1': {'Block1': 10, 'Block2': 5},
        'R2': {'Block1': 7, 'Block2': 9}
    }
    df = pd.DataFrame(data)
    
    file_path = os.path.join(temp_directory, 'block_resident_ranking.csv')
    df.to_csv(file_path)
    
    return file_path


@pytest.fixture
def hint_file(temp_directory):
    """Create a hint file (previous solution) for testing."""
    # Create solution dictionary in the format expected by hint processing
    solution = {
        'main': {
            ('R1', 'Block1', 'Rotation1'): 1,
            ('R1', 'Block2', 'Rotation2'): 1,
            ('R2', 'Block1', 'Rotation2'): 1,
            ('R2', 'Block2', 'Rotation1'): 1,
        }
    }
    
    file_path = os.path.join(temp_directory, 'hint.pkl')
    with open(file_path, 'wb') as f:
        import pickle
        pickle.dump(solution, f)
    
    return file_path


class TestParseArgs:
    """Test command-line argument parsing."""
    
    def test_required_args(self):
        """Test that required arguments are enforced."""
        with pytest.raises(SystemExit):
            solver.parse_args([])
    
    def test_basic_args(self):
        """Test parsing of basic arguments."""
        args = solver.parse_args(['solve', '--config', 'config.yml', '--results', 'results.csv'])
        assert args.config == 'config.yml'
        assert args.results == 'results.csv'
        assert args.n_processes == 1  # default
    
    def test_all_args(self):
        """Test parsing of all possible arguments."""
        args = solver.parse_args([
            'solve',
            '--config', 'config.yml',
            '--coverage-min', 'min.csv',
            '--coverage-max', 'max.csv',
            '--rotation-pins', 'pins.csv',
            '--rankings', 'rankings.csv',
            '--score-list', 'main', 'scores.csv',
            '--block-resident-ranking', 'main', 'block_rankings.csv',
            '--results', 'results.csv',
            '--vacation', 'vacation.csv',
            '--dump-model', 'model.json',
            '-p', '4',
            '-n', '10',
            '--objective', 'custom_objective',
            '--min-individual-rank', '5.5',
            '--hint', 'hint.pkl'
        ])
        
        assert args.config == 'config.yml'
        assert args.coverage_min == 'min.csv'
        assert args.coverage_max == 'max.csv'
        assert args.rotation_pins == 'pins.csv'
        assert args.rankings == 'rankings.csv'
        assert args.score_list == [['main', 'scores.csv']]
        assert args.block_resident_ranking == ['main', 'block_rankings.csv']
        assert args.results == 'results.csv'
        assert args.vacation == 'vacation.csv'
        assert args.dump_model == 'model.json'
        assert args.n_processes == 4
        assert args.n_solutions == 10
        assert args.objective == 'custom_objective'
        assert args.min_individual_rank == 5.5
        assert args.hint == 'hint.pkl'


class TestSubcommands:
    """Test the solve/swap subcommand interface."""

    def test_swap_requires_minimize_changes_from(self):
        with pytest.raises(SystemExit):
            solver.parse_args(
                ['swap', '--config', 'c.yml', '--results', 'r.csv'])

    def test_require_repeatable_on_solve(self):
        args = solver.parse_args([
            'solve', '--config', 'c.yml', '--results', 'r.csv',
            '--require', 'sum == 1: R1 and Bl1',
            '--require', 'sum == 0: R2 and Bl2',
        ])
        assert args.require == [
            'sum == 1: R1 and Bl1', 'sum == 0: R2 and Bl2']

    def test_require_and_minimize_changes_from_on_swap(self):
        args = solver.parse_args([
            'swap', '--config', 'c.yml', '--results', 'r.csv',
            '--minimize-changes-from', 'old.json',
            '--require', 'sum == 1: R1 and Bl1',
        ])
        assert args.require == ['sum == 1: R1 and Bl1']
        assert args.minimize_changes_from == 'old.json'

    def test_freeze_repeatable_on_swap(self):
        args = solver.parse_args([
            'swap', '--config', 'c.yml', '--results', 'r.csv',
            '--minimize-changes-from', 'old.json',
            '--freeze', 'Block 1', '--freeze', 'R1',
        ])
        assert args.freeze == ['Block 1', 'R1']

    def test_freeze_rejected_on_solve(self):
        with pytest.raises(SystemExit):
            solver.parse_args([
                'solve', '--config', 'c.yml', '--results', 'r.csv',
                '--freeze', 'Block 1',
            ])

    def test_bare_help_lists_subcommands(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            solver.main(['--help'])

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert 'solve' in out
        assert 'swap' in out

    @patch('schedulomicon.solve.solve')
    def test_flagless_invocation_warns_and_solves(
            self, mock_solve, basic_config_file, temp_directory, capsys):
        results_file = os.path.join(temp_directory, 'results.csv')
        mock_solve.return_value = (
            'INFEASIBLE', MagicMock(), MagicMock(), MagicMock(), 1.0)

        exit_code = solver.main(
            ['--config', basic_config_file, '--results', results_file])

        assert exit_code == 0
        assert 'deprecat' in capsys.readouterr().err.lower()
        mock_solve.assert_called_once()

    @patch('schedulomicon.solve.solve')
    def test_swap_plumbs_old_solution_and_require(
            self, mock_solve, basic_config_file, temp_directory):
        from schedulomicon import csts as csts_module

        old_solution = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
            }
        }
        old_file = os.path.join(temp_directory, 'old.json')
        io.write_solution(old_file, old_solution)

        results_file = os.path.join(temp_directory, 'results.json')

        # pass-1 result; no rankings given, so pass 2 is skipped
        new_solution = {
            'main': {
                ('R1', 'Block1', 'Rotation2'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation1'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
            }
        }
        cp_solver = MagicMock()
        cp_solver.ObjectiveValue.return_value = -2.0
        printer = MagicMock()
        printer._solutions = [new_solution]
        printer.solution_count.return_value = 1
        mock_solve.return_value = (
            'OPTIMAL', cp_solver, printer, MagicMock(), 1.0)

        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main([
                'swap',
                '--config', basic_config_file,
                '--minimize-changes-from', old_file,
                '--require', 'sum == 0: R1 and Block1 and Rotation1',
                '--results', results_file,
            ])

        assert exit_code == 1
        mock_solve.assert_called_once()

        args, kwargs = mock_solve.call_args
        # the old solution is passed as the pass-1 hint
        assert kwargs['hint'] == old_solution
        # the --require constraint made it into the constraint list
        cst_list = args[4]
        assert any(isinstance(c, csts_module.FieldSumConstraint)
                   for c in cst_list)
        # pass 1 minimizes the diff objective
        assert [g for g, _ in kwargs['score_functions']] == ['main']

        assert os.path.exists(results_file)
        # d_star = o_star + n_valid_old_on = -2 + 4
        assert 'Minimal changes' in fake_stdout.getvalue()
        assert 'R1, Block1: Rotation1 -> Rotation2' in fake_stdout.getvalue()

    @patch('schedulomicon.solve.solve')
    def test_swap_plumbs_freeze_constraint(
            self, mock_solve, basic_config_file, temp_directory):
        from schedulomicon import swap as swap_module

        old_solution = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
            }
        }
        old_file = os.path.join(temp_directory, 'old.json')
        io.write_solution(old_file, old_solution)

        results_file = os.path.join(temp_directory, 'results.json')

        cp_solver = MagicMock()
        cp_solver.ObjectiveValue.return_value = -4.0
        printer = MagicMock()
        printer._solutions = [old_solution]
        printer.solution_count.return_value = 1
        mock_solve.return_value = (
            'OPTIMAL', cp_solver, printer, MagicMock(), 1.0)

        exit_code = solver.main([
            'swap',
            '--config', basic_config_file,
            '--minimize-changes-from', old_file,
            '--freeze', 'Block1',
            '--results', results_file,
        ])

        assert exit_code == 1
        mock_solve.assert_called_once()

        args, kwargs = mock_solve.call_args
        cst_list = args[4]
        freeze_csts = [c for c in cst_list
                       if isinstance(c, swap_module.FreezeConstraint)]
        assert len(freeze_csts) == 1
        assert freeze_csts[0].pins == {'main': {
            ('R1', 'Block1', 'Rotation1'): 1,
            ('R1', 'Block1', 'Rotation2'): 0,
            ('R2', 'Block1', 'Rotation1'): 0,
            ('R2', 'Block1', 'Rotation2'): 1,
        }}


class TestNSolutionsFlag:
    """Parsing of -n / --n_solutions / --n-solutions."""

    def test_dashed_spelling_on_solve(self):
        args = solver.parse_args([
            'solve', '--config', 'c.yml', '--results', 'r.csv',
            '--n-solutions', '3'])
        assert args.n_solutions == 3

    def test_dashed_spelling_on_swap(self):
        args = solver.parse_args([
            'swap', '--config', 'c.yml', '--results', 'r.csv',
            '--minimize-changes-from', 'old.json',
            '--n-solutions', '3'])
        assert args.n_solutions == 3

    def test_short_and_underscore_spellings_still_work(self):
        args = solver.parse_args([
            'solve', '--config', 'c.yml', '--results', 'r.csv', '-n', '3'])
        assert args.n_solutions == 3

        args = solver.parse_args([
            'solve', '--config', 'c.yml', '--results', 'r.csv',
            '--n_solutions', '4'])
        assert args.n_solutions == 4


class TestSwapMultiProposals:
    """swap --n-solutions N > 1: numbered files and validation."""

    @patch('schedulomicon.solve.solve')
    def test_swap_multi_writes_numbered_files(
            self, mock_solve, basic_config_file, temp_directory):
        old_solution = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
            }
        }
        old_file = os.path.join(temp_directory, 'old.json')
        io.write_solution(old_file, old_solution)

        results_file = os.path.join(temp_directory, 'new.json')

        s1 = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 0,
                ('R1', 'Block1', 'Rotation2'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
            }
        }
        s2 = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 0,
                ('R2', 'Block2', 'Rotation2'): 1,
            }
        }

        def pass_result(solution):
            cp_solver = MagicMock()
            cp_solver.ObjectiveValue.return_value = -2.0
            printer = MagicMock()
            printer._solutions = [solution]
            printer.solution_count.return_value = 1
            return ('OPTIMAL', cp_solver, printer, MagicMock(), 1.0)

        # no rankings: pass 2 is skipped, one solve call per proposal
        mock_solve.side_effect = [pass_result(s1), pass_result(s2)]

        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main([
                'swap',
                '--config', basic_config_file,
                '--minimize-changes-from', old_file,
                '--n-solutions', '2',
                '--results', results_file,
            ])

        assert exit_code == 1
        assert mock_solve.call_count == 2

        # numbered files are written, not the bare --results path
        assert not os.path.exists(results_file)
        assert io.read_solution(os.path.join(temp_directory, 'new-1.json')) \
            == {'main': {k: v for k, v in s1['main'].items() if v}}
        assert io.read_solution(os.path.join(temp_directory, 'new-2.json')) \
            == {'main': {k: v for k, v in s2['main'].items() if v}}

        out = fake_stdout.getvalue()
        # d = o_star + n_valid_old_on = -2 + 4
        assert 'Proposal 1/2: 2 variable flip(s) from old schedule' in out
        assert 'Proposal 2/2: 2 variable flip(s) from old schedule' in out
        assert 'R1, Block1: Rotation1 -> Rotation2' in out
        assert 'R2, Block2: Rotation1 -> Rotation2' in out

    @patch('schedulomicon.solve.solve')
    def test_swap_n_solutions_zero_errors(
            self, mock_solve, basic_config_file, temp_directory):
        old_file = os.path.join(temp_directory, 'old.json')
        io.write_solution(
            old_file, {'main': {('R1', 'Block1', 'Rotation1'): 1}})

        with pytest.raises(SystemExit) as exc_info:
            solver.main([
                'swap',
                '--config', basic_config_file,
                '--minimize-changes-from', old_file,
                '--n-solutions', '0',
                '--results', os.path.join(temp_directory, 'new.json'),
            ])

        assert 'at least 1' in str(exc_info.value)
        mock_solve.assert_not_called()


class TestConfigLoading:
    """Test configuration file loading and processing."""
    
    def test_load_basic_config(self, basic_config_file):
        """Test loading a basic configuration file."""
        with open(basic_config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'residents' in config
        assert 'rotations' in config
        assert 'blocks' in config
        assert len(config['residents']) == 2
        assert len(config['rotations']) == 2
        assert len(config['blocks']) == 2
    
class TestScoreFunctionGeneration:
    """Test generation and integration of score functions."""
    
    def test_score_dict_generation(self, rankings_file):
        """Test generation of score dictionaries from rankings."""
        residents = ['R1', 'R2']
        blocks = ['Block1', 'Block2']
        rotations = ['Rotation1', 'Rotation2']
        
        mock_rankings = {
            'R1': {'Rotation1': 10, 'Rotation2': 3}, 
            'R2': {'Rotation1': 5, 'Rotation2': 8}
        }
        
        scores = score.score_dict_from_df(mock_rankings, residents, blocks, rotations, None)
        
        # Check a few entries in the generated scores dictionary
        assert scores[('R1', 'Block1', 'Rotation1')] == 10
        assert scores[('R1', 'Block2', 'Rotation1')] == 10
        assert scores[('R2', 'Block1', 'Rotation2')] == 8
        assert scores[('R2', 'Block2', 'Rotation2')] == 8


@patch('schedulomicon.solve.solve')
class TestSolverIntegration:
    """Test the integration of solve functionality."""
    
    def test_solve_with_basic_config(self, mock_solve, basic_config_file, temp_directory):
        """Test solving with a basic configuration."""
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Mock solve function
        solution_printer = MagicMock()
        solution_printer.solution_count.return_value = 1

        solution_printer._solutions = [{
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block1', 'Rotation2'): 0,
                ('R1', 'Block2', 'Rotation1'): 0,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation1'): 0,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
                ('R2', 'Block2', 'Rotation2'): 0,
            }
        }]
        
        solution_printer.df_from_solution.return_value = pd.DataFrame(
            {
                'R1': ['Rotation1', 'Rotation2'],
                'R2': ['Rotation2', 'Rotation1']
            }, index=['Block1', 'Block2']
        )

        mock_solve.return_value = ('OPTIMAL', MagicMock(), solution_printer, MagicMock(), 1.0)

        # Redirect stdout to capture printed output
        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main(['solve', '--config', basic_config_file, '--results', results_file])

        assert exit_code == 1
        assert os.path.exists(results_file)
        assert "Best solution at " in fake_stdout.getvalue()
        
        
    def test_solve_with_json_results(self, mock_solve, basic_config_file, temp_directory):
        """--results with a .json extension writes the sparse JSON format."""
        import json

        results_file = os.path.join(temp_directory, 'results.json')

        solution_printer = MagicMock()
        solution_printer.solution_count.return_value = 1
        solution_printer._solutions = [{
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block1', 'Rotation2'): 0,
                ('R1', 'Block2', 'Rotation1'): 0,
                ('R1', 'Block2', 'Rotation2'): 1,
                ('R2', 'Block1', 'Rotation1'): 0,
                ('R2', 'Block1', 'Rotation2'): 1,
                ('R2', 'Block2', 'Rotation1'): 1,
                ('R2', 'Block2', 'Rotation2'): 0,
            }
        }]

        mock_solve.return_value = ('OPTIMAL', MagicMock(), solution_printer, MagicMock(), 1.0)

        with patch('sys.stdout', new=StringIO()):
            exit_code = solver.main(['solve', '--config', basic_config_file, '--results', results_file])

        assert exit_code == 1
        with open(results_file) as f:
            raw = json.load(f)

        assert raw['format_version'] == 1
        assert set(raw['grids']) == {'main'}
        assert raw['grids']['main']['key_fields'] == ['resident', 'block', 'rotation']
        assert sorted(map(tuple, raw['grids']['main']['variables'])) == [
            ('R1', 'Block1', 'Rotation1', 1),
            ('R1', 'Block2', 'Rotation2', 1),
            ('R2', 'Block1', 'Rotation2', 1),
            ('R2', 'Block2', 'Rotation1', 1),
        ]

    def test_json_hint_plumb_through(self, mock_solve, basic_config_file, temp_directory):
        """--hint with a .json file passes the sparse tuple-keyed dict to solve."""
        results_file = os.path.join(temp_directory, 'results.csv')
        hint_file = os.path.join(temp_directory, 'hint.json')

        solution = {
            'main': {
                ('R1', 'Block1', 'Rotation1'): 1,
                ('R1', 'Block2', 'Rotation2'): 0,
            }
        }
        io.write_solution(hint_file, solution)

        mock_solve.return_value = ('INFEASIBLE', MagicMock(), MagicMock(), MagicMock(), 1.0)

        with patch('sys.stdout', new=StringIO()):
            solver.main(['solve', '--config', basic_config_file,
                         '--results', results_file,
                         '--hint', hint_file])

        _, kwargs = mock_solve.call_args
        assert kwargs['hint'] == {'main': {('R1', 'Block1', 'Rotation1'): 1}}

    def test_no_solution_found(self, mock_solve, basic_config_file, temp_directory):
        """Test behavior when no solution is found."""
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Mock solve function to return INFEASIBLE status
        mock_solve.return_value = ('INFEASIBLE', MagicMock(), MagicMock(), MagicMock(), 1.0)
        
        # Redirect stdout to capture printed output
        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main(['solve', '--config', basic_config_file, '--results', results_file])
        
        assert exit_code == 0
        assert "No best solution." in fake_stdout.getvalue()
        assert not os.path.exists(results_file)


class TestExampleConfig:
    """Integration test running the full solver against the example config."""

    def test_example_config_produces_solution(self, tmp_path):
        """Run solver with examples/example_config.yml and verify results are written."""
        import os
        example_config = os.path.join(
            os.path.dirname(__file__), '..', 'examples', 'example_config.yml'
        )
        results_file = str(tmp_path / 'results.csv')

        exit_code = solver.main(['solve', '--config', example_config, '--results', results_file])

        assert exit_code == 1, "Solver should find a feasible solution"
        assert os.path.exists(results_file), "Results CSV should be written"
        df = pd.read_csv(results_file, index_col=0)
        assert not df.empty, "Results CSV should contain assignments"

    def test_example_config_json_write_then_hint(self, tmp_path):
        """Write a .json solution, then re-solve with it as --hint."""
        example_config = os.path.join(
            os.path.dirname(__file__), '..', 'examples', 'example_config.yml'
        )
        json_results = str(tmp_path / 'results.json')

        exit_code = solver.main(
            ['solve', '--config', example_config, '--results', json_results])
        assert exit_code == 1, "First solve should find a feasible solution"

        solution = io.read_solution(json_results)
        assert 'main' in solution
        assert all(v != 0 for v in solution['main'].values()), \
            "JSON solutions should be sparse (nonzero entries only)"

        second_results = str(tmp_path / 'results2.csv')
        exit_code = solver.main(
            ['solve', '--config', example_config, '--results', second_results,
             '--hint', json_results])
        assert exit_code == 1, "Hinted solve should find a feasible solution"
        assert os.path.exists(second_results)


class TestErrorHandling:
    """Test error handling in the solver application."""
    
    def test_invalid_config_file(self, temp_directory):
        """Test behavior with an invalid configuration file."""
        # Create an invalid YAML file
        invalid_config_path = os.path.join(temp_directory, 'invalid_config.yml')
        with open(invalid_config_path, 'w') as f:
            f.write('this: is: not: valid: yaml:')
        
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Expect the YAML parser to raise an exception
        with pytest.raises(yaml.YAMLError):
            solver.main(['solve', '--config', invalid_config_path, '--results', results_file])
    
    def test_nonexistent_file(self, temp_directory):
        """Test behavior with a nonexistent file."""
        nonexistent_file = os.path.join(temp_directory, 'nonexistent.yml')
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Expect a FileNotFoundError
        with pytest.raises(FileNotFoundError):
            solver.main(['solve', '--config', nonexistent_file, '--results', results_file])
