"""Helper functions for flow tests."""


def contains_with_either_quotes(haystack: str, needle: str) -> bool:
    """
    Check if haystack contains needle, accepting either single or double quotes.

    This handles the fact that ast.unparse() uses single quotes while
    test assertions might use double quotes.
    """
    double_quote_version = needle
    single_quote_version = needle.replace('"', "'")

    return double_quote_version in haystack or single_quote_version in haystack
