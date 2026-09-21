"""Category vocabularies and near matches, used only to word zero-result hints."""

import pyarrow as pa

from botmap.category_taxonomy import category_pairs, closest_values


def _batch(primaries, basics=None):
    columns = {"taxonomy": pa.array(
        [None if p is None else {"primary": p} for p in primaries],
        type=pa.struct([("primary", pa.string())]))}
    if basics is not None:
        columns["basic_category"] = pa.array(basics, type=pa.string())
    return pa.RecordBatch.from_pydict(columns)


class TestClosestValues:
    def test_plural_input_finds_the_singular(self):
        assert closest_values("restaurants", {"restaurant", "hospital"})[0] == "restaurant"

    def test_shared_token_beats_character_overlap(self):
        hits = closest_values("ferry_terminal", {"ferry_service", "cafeteria"})
        assert hits == ["ferry_service"]

    def test_typo_is_corrected(self):
        assert closest_values("coffe_shop", {"coffee_shop", "hospital"}) == ["coffee_shop"]

    def test_unrelated_values_are_not_suggested(self):
        assert closest_values("ferry_terminal", {"hospital", "bookstore"}) == []

    def test_returns_at_most_n(self):
        values = {"ferry_terminal", "ferry_service", "ferry_boat_company", "ferry_dock"}
        assert len(closest_values("ferry", values, n=3)) == 3


class TestCategoryPairs:
    def test_pairs_both_vocabularies_in_one_pass(self):
        batches = [_batch(["veterinarian", "cafe"], ["animal_or_pet_service", "cafe"])]
        assert category_pairs(batches) == {
            ("veterinarian", "animal_or_pet_service"), ("cafe", "cafe")}

    def test_keeps_rows_where_one_side_is_null(self):
        batches = [_batch([None, "cafe"], ["park", None])]
        assert category_pairs(batches) == {(None, "park"), ("cafe", None)}

    def test_release_without_basic_category_pairs_with_none(self):
        assert category_pairs([_batch(["cafe"])]) == {("cafe", None)}

    def test_collects_across_batches(self):
        batches = [_batch(["cafe"], ["cafe"]), _batch(["bar"], ["bar"])]
        assert category_pairs(batches) == {("cafe", "cafe"), ("bar", "bar")}
