import unittest

from fortune_fetch import format_animal_blocks


class FortuneFormatTests(unittest.TestCase):
    def test_fixed_spacing_between_heading_body_score_and_next_animal(self):
        lines = [
            "〈쥐띠〉",
            "쥐띠 본문입니다.",
            "운세지수 94%. 금전 95 건강 90 애정 95",
            "〈소띠〉",
            "소띠 본문입니다.",
            "운세지수 41%. 금전 45 건강 45 애정 40",
        ]

        self.assertEqual(
            format_animal_blocks(lines),
            "〈쥐띠〉\n\n"
            "쥐띠 본문입니다.\n\n\n"
            "운세지수 94%. 금전 95 건강 90 애정 95\n\n"
            "〈소띠〉\n\n"
            "소띠 본문입니다.\n\n\n"
            "운세지수 41%. 금전 45 건강 45 애정 40",
        )

    def test_multiple_body_fragments_are_joined_into_one_paragraph(self):
        lines = [
            "〈범띠〉",
            "첫 문장입니다.",
            "둘째 문장입니다.",
            "운세지수 87%. 금전 90 건강 85 애정 85",
        ]

        self.assertIn("첫 문장입니다. 둘째 문장입니다.", format_animal_blocks(lines))


if __name__ == "__main__":
    unittest.main()
