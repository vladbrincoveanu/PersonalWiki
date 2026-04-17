"""Tests for core/prose.py - measure_prose function."""
import pytest


class TestMeasureProse:
    """TDD tests for measure_prose function."""

    def test_empty_text_returns_zero(self):
        """Empty text should return (0, 0.0)."""
        from core.prose import measure_prose
        chars, ratio = measure_prose("")
        assert chars == 0
        assert ratio == 0.0

    def test_whitespace_only_returns_zero(self):
        """Whitespace-only text should return (0, 0.0)."""
        from core.prose import measure_prose
        chars, ratio = measure_prose("   \n\n\t  ")
        assert chars == 0
        assert ratio == 0.0

    def test_high_prose_ratio(self):
        """Text with mostly prose should have high ratio."""
        from core.prose import measure_prose
        text = """This is a substantial paragraph with multiple sentences.

This is another paragraph that continues the narrative flow."""
        chars, ratio = measure_prose(text)
        # Both blocks have >3 words, mixed case, and >30% alpha
        assert chars > 0
        assert ratio > 0.5

    def test_low_prose_ratio_all_caps(self):
        """ALL CAPS blocks should be filtered out."""
        from core.prose import measure_prose
        text = """THIS IS ALL CAPS HEADING

This is a normal prose paragraph with multiple sentences."""
        chars, ratio = measure_prose(text)
        # Only the second block should count
        assert chars < len(text.strip())

    def test_low_prose_ratio_too_few_words(self):
        """Blocks with fewer than 3 words should be filtered out."""
        from core.prose import measure_prose
        text = """This is a normal paragraph.

Hi

Another normal paragraph."""
        chars, ratio = measure_prose(text)
        # "Hi" is a single word, should be filtered
        assert chars < len(text.strip())

    def test_low_prose_ratio_symbol_heavy(self):
        """Blocks with <30% alphabetic chars should be filtered out."""
        from core.prose import measure_prose
        text = """This is normal prose.

___---***%%%___---***

Another normal paragraph."""
        chars, ratio = measure_prose(text)
        # The symbol-heavy block should be filtered

    def test_prose_ratio_calculation(self):
        """Verify prose_ratio = prose_chars / total_chars."""
        from core.prose import measure_prose
        text = """One sentence here.

Another sentence in this paragraph."""
        chars, ratio = measure_prose(text)
        expected_ratio = chars / len(text.strip())
        assert abs(ratio - expected_ratio) < 0.001

    def test_real_article_snippet(self):
        """Test with realistic article content."""
        from core.prose import measure_prose
        text = """Researchers from MIT have developed a new approach to machine learning
that achieves better results with less training data.

The method, called sparse attention transformers, allows models to focus
only on the most relevant parts of the input during processing.

Key findings:
- 40% less training data required
- Improved performance on long documents
- Compatible with existing architectures

The research team published their findings in the latest issue of Nature ML."""
        chars, ratio = measure_prose(text)
        # Should count the prose blocks, skip the Key findings section (mostly symbols)
        assert chars > 0
        assert 0 < ratio < 1.0