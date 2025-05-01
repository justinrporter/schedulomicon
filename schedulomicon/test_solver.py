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
            'R1': {'group': ['CA1']},
            'R2': {'group': ['CA1']},
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
        args = solver.parse_args(['--config', 'config.yml', '--results', 'results.csv'])
        assert args.config == 'config.yml'
        assert args.results == 'results.csv'
        assert args.n_processes == 1  # default
    
    def test_all_args(self):
        """Test parsing of all possible arguments."""
        args = solver.parse_args([
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
            '--hint', 'hint.csv'
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
        assert args.hint == 'hint.csv'


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
    
    @patch('schedulomicon.io.process_config')
    def test_process_config(self, mock_process_config, basic_config_file):
        """Test processing of configuration."""
        residents = ['R1', 'R2']
        blocks = ['Block1', 'Block2']
        rotations = ['Rotation1', 'Rotation2']
        cogrids_avail = []
        groups_array = {}
        
        mock_process_config.return_value = (residents, blocks, rotations, cogrids_avail, groups_array)
        
        with open(basic_config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        result = io.process_config(config)
        
        mock_process_config.assert_called_once()
        assert result == (residents, blocks, rotations, cogrids_avail, groups_array)


class TestInputFileHandling:
    """Test handling of input files."""
    
    @patch('schedulomicon.io.coverage_constraints_from_csv')
    def test_coverage_min_loading(self, mock_coverage_constraints, coverage_min_file):
        """Test loading coverage minimum constraints from CSV."""
        mock_coverage_constraints.return_value = [MagicMock()]
        
        constraints = io.coverage_constraints_from_csv(coverage_min_file, 'rmin')
        
        mock_coverage_constraints.assert_called_once_with(coverage_min_file, 'rmin')
        assert len(constraints) == 1
    
    @patch('schedulomicon.io.coverage_constraints_from_csv')
    def test_coverage_max_loading(self, mock_coverage_constraints, coverage_max_file):
        """Test loading coverage maximum constraints from CSV."""
        mock_coverage_constraints.return_value = [MagicMock()]
        
        constraints = io.coverage_constraints_from_csv(coverage_max_file, 'rmax')
        
        mock_coverage_constraints.assert_called_once_with(coverage_max_file, 'rmax')
        assert len(constraints) == 1
    
    @patch('schedulomicon.io.rankings_from_csv')
    def test_rankings_loading(self, mock_rankings_from_csv, rankings_file):
        """Test loading rankings from CSV."""
        mock_rankings = {'R1': {'Rotation1': 10, 'Rotation2': 3}, 
                        'R2': {'Rotation1': 5, 'Rotation2': 8}}
        mock_rankings_from_csv.return_value = mock_rankings
        
        rankings = io.rankings_from_csv(rankings_file)
        
        mock_rankings_from_csv.assert_called_once_with(rankings_file)
        assert rankings == mock_rankings


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
    
    def test_block_resident_ranking_integration(self, block_resident_ranking_file):
        """Test integration of block-resident rankings."""
        residents = ['R1', 'R2']
        blocks = ['Block1', 'Block2']
        rotations = ['Rotation1', 'Rotation2']
        
        mock_rankings = {
            'R1': {'Rotation1': 10, 'Rotation2': 3}, 
            'R2': {'Rotation1': 5, 'Rotation2': 8}
        }
        
        block_resident_df = pd.read_csv(block_resident_ranking_file, header=0, index_col=0)
        block_resident_ranking = ('main', block_resident_df.T.to_dict())
        
        scores = score.score_dict_from_df(mock_rankings, residents, blocks, rotations, block_resident_ranking)
        
        # Check that block-resident rankings are applied
        assert scores[('R1', 'Block1', 'Rotation1')] != scores[('R1', 'Block2', 'Rotation1')]
        assert scores[('R2', 'Block1', 'Rotation2')] != scores[('R2', 'Block2', 'Rotation2')]


@patch('schedulomicon.solve.solve')
class TestSolverIntegration:
    """Test the integration of solve functionality."""
    
    def test_solve_with_basic_config(self, mock_solve, basic_config_file, temp_directory):
        """Test solving with a basic configuration."""
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Mock solve function
        solution_printer = MagicMock()
        solution_printer.solution_count.return_value = 1
        solution_printer._solutions = [pd.DataFrame({
            'R1': ['Rotation1', 'Rotation2'],
            'R2': ['Rotation2', 'Rotation1']
        }, index=['Block1', 'Block2'])]
        
        mock_solve.return_value = ('OPTIMAL', MagicMock(), solution_printer, MagicMock(), 1.0)
        
        # Redirect stdout to capture printed output
        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main(['--config', basic_config_file, '--results', results_file])
        
        assert exit_code == 1
        assert os.path.exists(results_file)
        assert "Best solution at " in fake_stdout.getvalue()
        
    def test_solve_with_all_options(self, mock_solve, basic_config_file, coverage_min_file, 
                                  coverage_max_file, rotation_pins_file, rankings_file, 
                                  score_list_file, block_resident_ranking_file, hint_file,
                                  temp_directory):
        """Test solving with all options specified."""
        results_file = os.path.join(temp_directory, 'results.csv')
        vacation_file = os.path.join(temp_directory, 'vacation.csv')
        
        # Mock solve function
        solution_printer = MagicMock()
        solution_printer.solution_count.return_value = 1
        solution_printer._solutions = [pd.DataFrame({
            'R1': ['Rotation1', 'Rotation2'],
            'R2': ['Rotation2', 'Rotation1']
        }, index=['Block1', 'Block2'])]
        
        mock_solve.return_value = ('OPTIMAL', MagicMock(), solution_printer, MagicMock(), 1.0)
        
        # Redirect stdout to capture printed output
        with patch('sys.stdout', new=StringIO()):
            exit_code = solver.main([
                '--config', basic_config_file,
                '--coverage-min', coverage_min_file,
                '--coverage-max', coverage_max_file,
                '--rotation-pins', rotation_pins_file,
                '--rankings', rankings_file,
                '--score-list', 'main', score_list_file,
                '--block-resident-ranking', 'main', block_resident_ranking_file,
                '--results', results_file,
                '--vacation', vacation_file,
                '-p', '2',
                '-n', '5',
                '--min-individual-rank', '3.0',
                '--hint', hint_file
            ])
        
        assert exit_code == 1
        assert os.path.exists(results_file)
        
    def test_no_solution_found(self, mock_solve, basic_config_file, temp_directory):
        """Test behavior when no solution is found."""
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Mock solve function to return INFEASIBLE status
        mock_solve.return_value = ('INFEASIBLE', MagicMock(), MagicMock(), MagicMock(), 1.0)
        
        # Redirect stdout to capture printed output
        with patch('sys.stdout', new=StringIO()) as fake_stdout:
            exit_code = solver.main(['--config', basic_config_file, '--results', results_file])
        
        assert exit_code == 0
        assert "No best solution." in fake_stdout.getvalue()
        assert not os.path.exists(results_file)


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
            solver.main(['--config', invalid_config_path, '--results', results_file])
    
    def test_nonexistent_file(self, temp_directory):
        """Test behavior with a nonexistent file."""
        nonexistent_file = os.path.join(temp_directory, 'nonexistent.yml')
        results_file = os.path.join(temp_directory, 'results.csv')
        
        # Expect a FileNotFoundError
        with pytest.raises(FileNotFoundError):
            solver.main(['--config', nonexistent_file, '--results', results_file])
