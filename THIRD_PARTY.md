# Third-party software and data

Vexilla is MIT-licensed (see LICENSE). It uses techniques and data from
public sources — never GPL code. This file credits all third-party
lists, data, and notable techniques used.

## Data — domain / host lists

The knowledge base (`data/kb.db`) is built from curated domain data.
The MVP seed set is hand-authored. Future expansions may use:

| List | Source | License | Used for |
|---|---|---|---|
| StevenBlack hosts | https://github.com/StevenBlack/hosts | MIT | Tracker/ad domain identification |
| EasyList | https://easylist.to/ | GPL-3 (data only) | Ad blocking rules (data-derived categories only) |
| Tranco top sites | https://tranco-list.eu/ | CC-BY-4.0 | Common service coverage |

All lists are used for **data/information only**, not as code. Their
licenses apply to the list data itself, not to Vexilla.

## Techniques (not code)

The `/proc/net` → inode → PID attribution technique is well-documented
and used by many open-source tools including OpenSnitch (GPL-3) and
Portmaster (BSD). Vexilla reimplements the technique from publicly
available kernel documentation — not from anyone's code.

## Software dependencies

See `pyproject.toml` for Python packages. All are permissively licensed
(MIT, Apache-2.0, BSD) or compatible with MIT distribution.

## Licenses

- **Vexilla itself:** MIT
- **StevenBlack hosts:** MIT
- **Tranco:** Creative Commons Attribution 4.0
- **EasyList (data-derived):** GPL-3 (data only, not linked code)
- **All Python dependencies:** MIT / Apache-2.0 / BSD
