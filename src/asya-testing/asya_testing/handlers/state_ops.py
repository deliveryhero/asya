"""Test handler that exercises state proxy operations via patched builtins."""

import base64
import os
import stat as stat_module


def state_ops_handler(payload: dict) -> dict:
    """Dispatch state proxy operations for component/integration testing.

    Payload fields:
        op: str      - operation: read, write, exists, stat, listdir, remove, makedirs
        path: str    - absolute path under a state mount (e.g. /state/meta/key.txt)
        content: str - data to write (text mode) or base64-encoded (binary mode)
        mode: str    - file mode for open() (default: "r" for read, "w" for write)
        exist_ok: bool - for makedirs (default: False)
    """
    op = payload["op"]
    path = payload["path"]

    if op == "read":
        mode = payload.get("mode", "r")
        with open(path, mode) as f:
            content = f.read()
        if isinstance(content, bytes):
            return {"content_b64": base64.b64encode(content).decode()}
        return {"content": content}

    if op == "write":
        content = payload["content"]
        mode = payload.get("mode", "w")
        data_to_write = base64.b64decode(content) if "b" in mode else content
        with open(path, mode) as f:
            written = f.write(data_to_write)
        return {"written": written}

    if op == "exists":
        return {"exists": os.path.exists(path)}

    if op == "stat":
        st = os.stat(path)
        return {"size": st.st_size, "is_file": stat_module.S_ISREG(st.st_mode)}

    if op == "listdir":
        return {"entries": sorted(os.listdir(path))}

    if op == "remove":
        os.remove(path)
        return {"removed": True}

    if op == "makedirs":
        os.makedirs(path, exist_ok=payload.get("exist_ok", False))
        return {"created": True}

    raise ValueError(f"Unknown operation: {op}")
