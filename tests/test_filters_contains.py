"""`contains` keeps rows whose list column holds a value."""

import pyarrow as pa

from botmap.filters import list_contains_mask


def _mask(lists, value):
    col = pa.array(lists, type=pa.list_(pa.string()))
    return list_contains_mask(col, value).to_pylist()


class TestListContainsMask:
    def test_matches_a_value_anywhere_in_the_list(self):
        hierarchies = [
            ["food_and_drink", "restaurant", "steakhouse"],
            ["food_and_drink", "restaurant"],
        ]
        assert _mask(hierarchies, "restaurant") == [True, True]

    def test_non_matching_row_is_false(self):
        assert _mask([["shopping", "bookstore"]], "restaurant") == [False]

    def test_matches_whole_elements_not_substrings(self):
        assert _mask([["restaurant_equipment_and_supply"]], "restaurant") == [False]

    def test_empty_list_is_false(self):
        assert _mask([[]], "restaurant") == [False]

    def test_null_list_is_false(self):
        assert _mask([None], "restaurant") == [False]

    def test_null_element_is_skipped(self):
        assert _mask([[None, "restaurant"], [None]], "restaurant") == [True, False]

    def test_sliced_column_aligns_with_its_own_rows(self):
        col = pa.array([["restaurant"], ["cafe"], ["restaurant"]],
                       type=pa.list_(pa.string())).slice(1)
        assert list_contains_mask(col, "restaurant").to_pylist() == [False, True]


class TestValueMatchesElementType:
    def test_text_value_matches_a_numeric_list(self):
        col = pa.array([[1, 5], [2]], type=pa.list_(pa.int64()))
        assert list_contains_mask(col, "5").to_pylist() == [True, False]

    def test_numeric_looking_text_matches_a_text_list(self):
        assert _mask([["5"], ["6"]], "5") == [True, False]
