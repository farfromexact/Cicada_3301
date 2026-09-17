from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt6_multiplicative as multiplicative


class MultiplicativeTests(unittest.TestCase):
    def test_prime_implementations_agree(self):
        self.assertEqual(multiplicative.simple_primes(100), multiplicative.sieve_primes(100))

    def test_zero_free_and_zero_consume_are_distinct(self):
        primes = multiplicative.sieve_primes(20)
        cipher = [0, 4, 0, 7]
        free, free_clock = multiplicative.decode_page_candidate(cipher, 0, primes, False)
        consume, consume_clock = multiplicative.decode_page_candidate(cipher, 0, primes, True)
        self.assertEqual(free[0], consume[0], 0)
        self.assertNotEqual(free[1], consume[1])
        self.assertEqual(free_clock, 2)
        self.assertEqual(consume_clock, 4)

    def test_candidate_and_independent_decoders_agree(self):
        primes = multiplicative.sieve_primes(50)
        cipher = [0, 1, 2, 0, 28, 3]
        for consume in (False, True):
            candidate = multiplicative.decode_page_candidate(cipher, 2, primes, consume)
            independent = multiplicative.decode_page_independent(cipher, 2, primes, consume)
            self.assertEqual(candidate, independent)

    def test_corpus_applicability_is_pinned(self):
        pages = multiplicative.load_pages()
        self.assertEqual(len(pages), 56)
        self.assertEqual([p["page"] for p in pages if not p["indices"]], ["LP2/50"])
        self.assertEqual(sum(p["rune_count"] for p in pages), 12956)


if __name__ == "__main__":
    unittest.main()
