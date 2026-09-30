"""opskit - small, dependency-light building blocks for operational Python.

Design rules every module follows:
  * dry-run by default, explicit apply
  * idempotent and safe to re-run
  * paginate + time out every remote call
  * structured (JSON) logs and meaningful exit codes
"""
__version__ = "1.0.0"
