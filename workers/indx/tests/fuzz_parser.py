"""Coverage-guided Atheris / OSS-Fuzz harness for NTFS INDX and INDEX_ROOT parsers."""

import sys

import atheris

with atheris.instrument_imports():
    from src.parser.indx import parse_indx_block
    from src.parser.mft import parse_mft_record
    from src.parser.root import parse_index_root


def TestOneInput(data: bytes) -> None:
    """Fuzz harness entrypoint for Atheris and OSS-Fuzz."""
    if len(data) < 24:
        return

    try:
        parse_indx_block(data)
    except Exception:  # noqa: TRY203
        # Parser should handle malformed bytes gracefully without crashing
        raise

    try:
        parse_index_root(data)
    except Exception:  # noqa: TRY203
        raise

    try:
        parse_mft_record(data)
    except Exception:  # noqa: TRY203
        raise


def main() -> None:
    """Atheris fuzzing runner."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
