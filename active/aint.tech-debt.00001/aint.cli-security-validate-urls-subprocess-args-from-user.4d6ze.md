---
title: "CLI security: validate URLs and subprocess args from user config"
status: open
priority: 2
parent: 00001
---

The asya CLI reads URLs and subprocess args from .asya/config.yaml. A compromised machine could inject malicious values (file:// URLs, crafted subprocess args). Currently suppressed with nosemgrep/nosec. Fix: (1) validate URL schemes are http/https, (2) validate subprocess commands, (3) validate importlib module names match [a-zA-Z0-9_.] pattern. Files: k_cli.py, build_cli.py, parser.py, compiler.py.
