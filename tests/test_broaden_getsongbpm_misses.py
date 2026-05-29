import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from broaden_getsongbpm_misses import (
    candidate_row,
    collect_candidates,
    no_candidate_row,
    select_top,
    song_id,
    variants_for,
)
from fetch_getsongbpm_keys import QueryVariant


def source_row(**overrides):
    row = {
        "normalized_artists": "$NOT",
        "normalized_title": "GOSHA (feat. Wifisfuneral)",
        "source_position": "5",
        "video_id": "vid",
        "video_url": "https://music.youtube.com/watch?v=vid",
    }
    row.update(overrides)
    return row


def song(**overrides):
    payload = {
        "id": "abc",
        "title": "Gosha",
        "uri": "https://getsongbpm.com/song/gosha/abc",
        "tempo": "140",
        "time_sig": "4/4",
        "key_of": "Am",
        "open_key": "1m",
        "danceability": 60,
        "acousticness": 5,
        "artist": {"id": "x", "name": "$NOT"},
    }
    payload.update(overrides)
    return payload


class BroadenGetSongBpmMissesTest(unittest.TestCase):
    def test_variants_drop_artist(self):
        variants = variants_for(source_row())
        names = [v.name for v in variants]
        self.assertIn("title_only", names)
        self.assertIn("simplified_title_only", names)
        for variant in variants:
            self.assertEqual(variant.artist, "")

    def test_variants_skip_simplified_when_equal(self):
        variants = variants_for(source_row(normalized_title="Stem"))
        self.assertEqual([v.name for v in variants], ["title_only"])

    def test_variants_empty_title_returns_no_variants(self):
        self.assertEqual(variants_for(source_row(normalized_title="")), [])

    def test_variants_include_truncated_for_long_titles(self):
        variants = variants_for(
            source_row(normalized_title="My Love Mine All Mine"),
            include_truncated=True,
        )
        names = [v.name for v in variants]
        self.assertIn("title_first3", names)
        self.assertIn("title_first2", names)
        first3 = next(v for v in variants if v.name == "title_first3").title
        first2 = next(v for v in variants if v.name == "title_first2").title
        self.assertEqual(first3, "My Love Mine")
        self.assertEqual(first2, "My Love")

    def test_variants_skip_truncated_for_short_titles(self):
        variants = variants_for(
            source_row(normalized_title="Stem"),
            include_truncated=True,
        )
        names = [v.name for v in variants]
        self.assertNotIn("title_first3", names)
        self.assertNotIn("title_first2", names)

    def test_variants_truncated_dedupes_against_existing(self):
        variants = variants_for(
            source_row(normalized_title="My Love Mine"),
            include_truncated=True,
            truncated_min_words=3,
        )
        # first3 == full simplified title -> skip duplicate
        titles = [v.title for v in variants]
        self.assertEqual(titles.count("My Love Mine"), 1)
        # first2 still emitted
        self.assertIn("My Love", titles)

    def test_select_top_filters_by_min_score(self):
        row = source_row()
        good = song(id="g", title="Gosha", artist={"name": "$NOT"})
        bad = song(id="b", title="Totally Different", artist={"name": "Random"})
        kept = select_top(row, [good, bad], top_n=3, min_score=0.55)
        ids = [s.get("id") for _, s in kept]
        self.assertEqual(ids, ["g"])

    def test_select_top_caps_at_top_n(self):
        row = source_row(normalized_title="Song")
        songs = [
            song(id=f"id{n}", title="Song", artist={"name": "$NOT"})
            for n in range(6)
        ]
        kept = select_top(row, songs, top_n=3, min_score=0.55)
        self.assertEqual(len(kept), 3)

    def test_collect_candidates_dedupes_and_tracks_variants(self):
        row = source_row()
        variants = variants_for(row)
        responses = {
            variants[0].name: {"search": [song(id="a"), song(id="b")]},
            variants[1].name: {"search": [song(id="b"), song(id="c")]},
        }
        cached_flag = {variants[0].name: True, variants[1].name: False}

        def fetch(variant: QueryVariant):
            return responses[variant.name], cached_flag[variant.name]

        unique, variant_by_id, raw_count, fresh = collect_candidates(row, variants, fetch)
        self.assertEqual({song_id(s) for s in unique}, {"a", "b", "c"})
        self.assertEqual(variant_by_id["a"], "title_only")
        self.assertEqual(variant_by_id["b"], "title_only")
        self.assertEqual(variant_by_id["c"], "simplified_title_only")
        self.assertEqual(raw_count, 4)
        self.assertEqual(fresh, 1)

    def test_candidate_row_normalizes_mode_and_score(self):
        row = candidate_row(source_row(), song(), 0.9123, 1, "title_only")
        self.assertEqual(row["candidate_rank"], 1)
        self.assertEqual(row["candidate_score"], "0.9123")
        self.assertEqual(row["candidate_variant"], "title_only")
        self.assertEqual(row["key_of"], "A")
        self.assertEqual(row["mode"], "minor")
        self.assertEqual(row["getsongbpm_artist"], "$NOT")

    def test_no_candidate_row_records_counts(self):
        row = no_candidate_row(source_row(), raw_count=4, best_score=0.42)
        self.assertEqual(row["raw_candidate_count"], 4)
        self.assertEqual(row["best_score"], "0.4200")
        self.assertEqual(row["normalized_title"], "GOSHA (feat. Wifisfuneral)")


if __name__ == "__main__":
    unittest.main()
