import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_getsongbpm_keys import choose_match, comparable, mode_from_key, output_row, query_variants, score_song
from key_normalization import normalize_key_fields, normalize_key_mode


def source_row(**overrides):
    row = {
        "normalized_artists": "Metallica",
        "normalized_title": "Master of Puppets",
        "source_position": "1",
        "video_id": "vid",
        "video_url": "https://music.youtube.com/watch?v=vid",
        "original_artists": "Metallica",
        "original_title": "Master of Puppets",
        "album": "Master of Puppets",
        "duration_seconds": "515",
    }
    row.update(overrides)
    return row


def song(**overrides):
    payload = {
        "id": "o2r0L",
        "title": "Master of Puppets",
        "uri": "https://getsongbpm.com/song/master-of-puppets/o2r0L",
        "tempo": "220",
        "time_sig": "4/4",
        "key_of": "Em",
        "open_key": "2m",
        "danceability": 55,
        "acousticness": 0,
        "artist": {"id": "nZR", "name": "Metallica"},
        "album": {"title": "Master of Puppets", "year": 1986},
    }
    payload.update(overrides)
    return payload


class FetchGetSongBpmKeysTest(unittest.TestCase):
    def test_comparable_strips_punctuation_and_feat_metadata(self):
        self.assertEqual(comparable("Song (feat. Guest)!!!"), "song")

    def test_score_exact_match_is_high(self):
        self.assertGreaterEqual(score_song(source_row(), song()), 0.99)

    def test_choose_match_accepts_high_confidence(self):
        match = choose_match(source_row(), [song()], 0.86)
        self.assertEqual(match.status, "matched")
        self.assertEqual(match.song["id"], "o2r0L")

    def test_choose_match_rejects_low_confidence(self):
        match = choose_match(source_row(), [song(title="Enter Sandman")], 0.86)
        self.assertEqual(match.status, "low_confidence")

    def test_choose_match_marks_near_tie_ambiguous(self):
        row = source_row(normalized_title="Song")
        match = choose_match(
            row,
            [
                song(id="1", title="Song", artist={"name": "Metallica"}),
                song(id="2", title="Song", artist={"name": "Metallica"}),
            ],
            0.86,
        )
        self.assertEqual(match.status, "ambiguous")

    def test_mode_from_key(self):
        self.assertEqual(mode_from_key("Em"), "minor")
        self.assertEqual(mode_from_key("E minor"), "minor")
        self.assertEqual(mode_from_key("C"), "major")
        self.assertEqual(mode_from_key("C major"), "major")

    def test_normalize_key_mode_uses_canonical_pitch_classes(self):
        self.assertEqual(normalize_key_mode("Bb major"), ("A#", "major"))
        self.assertEqual(normalize_key_mode("A♯ minor"), ("A#", "minor"))
        self.assertEqual(normalize_key_mode("F# minor"), ("F#", "minor"))
        self.assertEqual(normalize_key_mode("F♯m"), ("F#", "minor"))
        self.assertEqual(normalize_key_mode("C"), ("C", "major"))

    def test_normalize_key_fields_moves_embedded_tempo(self):
        normalized = normalize_key_fields("Cm 84", tempo="")
        self.assertEqual(normalized.key_of, "C")
        self.assertEqual(normalized.mode, "minor")
        self.assertEqual(normalized.tempo, "84")

    def test_output_row_contains_key_and_mode(self):
        match = choose_match(source_row(), [song()], 0.86)
        row = output_row(source_row(), match)
        self.assertEqual(row["key_of"], "E")
        self.assertEqual(row["mode"], "minor")
        self.assertEqual(row["tempo"], "220")

    def test_query_variants_include_simplified_feature_title(self):
        variants = query_variants(
            source_row(
                normalized_artists="Lady Gaga",
                normalized_title="Just Dance (feat. Colby O'Donis)",
            )
        )
        self.assertEqual([variant.name for variant in variants], ["primary", "simplified_title"])
        self.assertEqual(variants[1].title, "Just Dance")


if __name__ == "__main__":
    unittest.main()
