"""Tests Entropy tasks."""

from src.tasks import calculate_entropy, HIGH_ENTROPY_THRESHOLD

class TestEntropyTask:
    """Tests for the Entropy task."""

    def test_random_entropy(self):
        with open('test_data/random.1k', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > 7.8)

    def test_zero_entropy(self):
        with open('test_data/zero.1k', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy == 0.0)

    def test_log_entropy(self):
        with open('test_data/syslog', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy == 5.129738750791151)

    def test_binary_low_entropy(self):
        with open('test_data/hello.bin', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > 0 )
            assert (entropy < HIGH_ENTROPY_THRESHOLD)

    def test_binary_high_entropy(self):
        with open('test_data/hello-upx.bin', 'rb') as random_file:
            entropy = calculate_entropy(random_file.read())
            assert (entropy > HIGH_ENTROPY_THRESHOLD)
