"""
Nested try-except blocks.

The inner try/except catches parse errors and continues with the outer
pipeline. The outer try/except catches connection errors from any actor
in the entire block. Each nesting level gets its own resiliency rules;
inner rules take precedence for actors in both scopes.

Error routing:
  fetch_data         → ConnectionError → handle_connection_error
  parse_data         → ValueError      → handle_parse_error (continue to transform)
                     → ConnectionError → handle_connection_error
  validate_data      → ValueError      → handle_parse_error (continue to transform)
                     → ConnectionError → handle_connection_error
  transform_data     → ConnectionError → handle_connection_error
  cleanup runs always (finally)
"""

from _asya_utils import flow


@flow
def nested_error_handling(p: dict) -> dict:
    try:
        p = fetch_data(p)
        try:
            p = parse_data(p)
            p = validate_data(p)
        except ValueError:
            p["parse_status"] = "invalid"
            p = handle_parse_error(p)
        p = transform_data(p)
    except ConnectionError:
        p["status"] = "connection_failed"
        p = handle_connection_error(p)
    finally:
        p = cleanup(p)
    p = store_results(p)
    return p
