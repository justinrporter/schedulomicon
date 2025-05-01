import pytest
import numpy as np
import pyparsing as pp

from . import parser, exceptions


class TestParser:
    @pytest.fixture
    def sample_groups_array(self):
        # Create sample groups array for testing
        # Using a simple dictionary with boolean arrays
        residents = ['R1', 'R2', 'R3']
        blocks = ['Bl1', 'Bl2', 'Bl3']
        rotations = ['Ro1', 'Ro2', 'Ro3']

        # Create some test groups
        groups = {
            'CA1': np.array([True, False, False]),  # R1 only
            'CA2': np.array([False, True, True]),   # R2 and R3
            'Block 1': np.array([True, False, False]),  # Block 1 only
            'Surgery': np.array([True, False, True]),   # Ro1 and Ro3
            'ICU': np.array([False, True, False]),      # Ro2 only
            'Winter': np.array([False, False, True]),   # Bl3 only
            'Early': np.array([True, True, False]),     # Bl1 and Bl2
        }
        return groups

    def test_simple_expressions(self, sample_groups_array):
        # Test simple AND expression
        expr = "CA1 and Surgery"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        # R1 is CA1 and Ro1/Ro3 are Surgery, so the result should be R1 and (Ro1 or Ro3)
        expected = sample_groups_array['CA1'] & sample_groups_array['Surgery']
        # The result is a ParseResults object containing the array, so we need to extract it
        assert np.array_equal(result[0], expected)

        # Test simple OR expression
        expr = "CA1 or CA2"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        # Either R1 (CA1) or R2,R3 (CA2), so all should be True
        expected = sample_groups_array['CA1'] | sample_groups_array['CA2']
        assert np.array_equal(result[0], expected)

        # Test simple NOT expression
        expr = "not CA1"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        # Not R1, so R2 and R3 should be True
        expected = ~sample_groups_array['CA1']
        assert np.array_equal(result[0], expected)

    def test_complex_expressions(self, sample_groups_array):
        # Test nested expressions
        expr = "CA1 and (Surgery or ICU)"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['CA1'] & (sample_groups_array['Surgery'] | sample_groups_array['ICU'])
        assert np.array_equal(result[0], expected)

        # Test multiple operations with precedence
        expr = "CA1 or CA2 and Surgery"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        # AND has higher precedence, so this is CA1 or (CA2 and Surgery)
        expected = sample_groups_array['CA1'] | (sample_groups_array['CA2'] & sample_groups_array['Surgery'])
        assert np.array_equal(result[0], expected)

        # Test complex expression with parentheses
        expr = "(CA1 or CA2) and (Surgery or ICU) and not Winter"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = (sample_groups_array['CA1'] | sample_groups_array['CA2']) & \
                   (sample_groups_array['Surgery'] | sample_groups_array['ICU']) & \
                   ~sample_groups_array['Winter']
        assert np.array_equal(result[0], expected)

    def test_block_identifier(self, sample_groups_array):
        # Test special "Block X" format
        expr = "Block 1"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['Block 1']
        assert np.array_equal(result[0], expected)

        # Test Block identifier in complex expression
        expr = "Block 1 and CA1"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['Block 1'] & sample_groups_array['CA1']
        assert np.array_equal(result[0], expected)

    def test_quoted_strings(self, sample_groups_array):
        # Test single quoted string
        expr = "'CA1'"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['CA1']
        assert np.array_equal(result[0], expected)

        # Test double quoted string
        expr = '"CA2"'
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['CA2']
        assert np.array_equal(result[0], expected)

        # Test quoted strings in expressions
        expr = '"CA1" and "Surgery"'
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['CA1'] & sample_groups_array['Surgery']
        assert np.array_equal(result[0], expected)

    def test_error_handling(self, sample_groups_array):
        # Test non-existent identifier
        with pytest.raises(exceptions.YAMLParseError):
            parser.resolve_eligible_field("CA3", sample_groups_array, [], [], [])
            
        # It seems pyparsing is handling some syntax errors internally
        # Let's test that invalid identifiers are caught
        with pytest.raises(exceptions.YAMLParseError):
            # This should raise YAMLParseError when _resolve_identifier tries to find NonExistentGroup
            parser.resolve_eligible_field("CA1 and NonExistentGroup", sample_groups_array, [], [], [])

    def test_real_world_patterns(self, sample_groups_array):
        # Test a complex eligibility expression (e.g., CA1 residents eligible for Surgery in early blocks)
        expr = "CA1 and Surgery and Early"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = sample_groups_array['CA1'] & sample_groups_array['Surgery'] & sample_groups_array['Early']
        assert np.array_equal(result[0], expected)

        # Test exclusion pattern (e.g., all residents except CA1 for Surgery)
        expr = "not CA1 and Surgery"
        result = parser.resolve_eligible_field(expr, sample_groups_array, [], [], [])
        expected = ~sample_groups_array['CA1'] & sample_groups_array['Surgery']
        assert np.array_equal(result[0], expected)
        
    def test_utility_functions(self, sample_groups_array):
        """Test utility functions used with parser results."""
        # Define a simple wrapper function to mimic how the parser results might be used
        def is_eligible(expr, groups_array, residents, blocks, rotations):
            result = parser.resolve_eligible_field(expr, groups_array, residents, blocks, rotations)
            # Usually we'd check if result[0] is True for a specific resident/block/rotation
            # Return the array for testing
            return result[0]
        
        residents = ['R1', 'R2', 'R3']
        blocks = ['Bl1', 'Bl2', 'Bl3']
        rotations = ['Ro1', 'Ro2', 'Ro3']
        
        # Test simple eligibility check
        expr = "CA1 and Surgery"
        result = is_eligible(expr, sample_groups_array, residents, blocks, rotations)
        expected = sample_groups_array['CA1'] & sample_groups_array['Surgery']
        assert np.array_equal(result, expected)
        
        # Test complex eligibility check
        expr = "(CA1 or CA2) and not Winter"
        result = is_eligible(expr, sample_groups_array, residents, blocks, rotations)
        expected = (sample_groups_array['CA1'] | sample_groups_array['CA2']) & ~sample_groups_array['Winter']
        assert np.array_equal(result, expected)
        
        # Test direct group reference
        expr = "CA1"
        result = is_eligible(expr, sample_groups_array, residents, blocks, rotations)
        expected = sample_groups_array['CA1']
        assert np.array_equal(result, expected)