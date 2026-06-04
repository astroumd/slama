"""Tests for the filter_leaves() function in dump_redis.py."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from dump_redis import filter_leaves


class TestFilterLeaves:
    def test_empty_input(self):
        assert filter_leaves([]) == []

    def test_single_path_is_leaf(self):
        assert filter_leaves(["a:b"]) == ["a:b"]

    def test_branch_removed_when_child_present(self):
        assert filter_leaves(["a:b", "a:b:c"]) == ["a:b:c"]

    def test_sibling_leaf_kept(self):
        # a:b is a branch (has child a:b:c), but a:d is a true leaf
        result = filter_leaves(["a:b", "a:b:c", "a:d"])
        assert "a:b:c" in result
        assert "a:d" in result
        assert "a:b" not in result

    def test_all_leaves_unchanged(self):
        paths = ["a:b:c", "a:d:e", "x:y:z"]
        assert sorted(filter_leaves(paths)) == sorted(paths)

    def test_deep_nesting_keeps_only_deepest(self):
        paths = ["a", "a:b", "a:b:c", "a:b:c:d"]
        assert filter_leaves(paths) == ["a:b:c:d"]

    def test_scanspec_example(self):
        # The motivating case from the goal doc
        paths = [
            "antenna:1:if:1:scanspec",
            "antenna:1:if:1:scanspec:channel_adc:1:name",
            "antenna:1:if:1:scanspec:channel_adc:1:step",
        ]
        result = filter_leaves(paths)
        assert "antenna:1:if:1:scanspec" not in result
        assert "antenna:1:if:1:scanspec:channel_adc:1:name" in result
        assert "antenna:1:if:1:scanspec:channel_adc:1:step" in result

    def test_shared_prefix_siblings_both_kept(self):
        # a:b:c and a:b:d share prefix a:b — both are leaves
        paths = ["a:b:c", "a:b:d"]
        result = filter_leaves(paths)
        assert "a:b:c" in result
        assert "a:b:d" in result

    def test_preserves_input_order(self):
        paths = ["z:leaf", "a:branch", "a:branch:leaf"]
        result = filter_leaves(paths)
        assert result.index("z:leaf") < result.index("a:branch:leaf")

    def test_no_colon_paths_treated_as_leaves(self):
        # Paths with no ":" separator are always leaves
        assert filter_leaves(["alpha", "beta"]) == ["alpha", "beta"]

    def test_intermediate_nodes_all_removed(self):
        # Multiple levels of branches should all be stripped
        paths = ["x:a", "x:a:b", "x:a:b:c", "x:a:b:c:leaf"]
        assert filter_leaves(paths) == ["x:a:b:c:leaf"]
