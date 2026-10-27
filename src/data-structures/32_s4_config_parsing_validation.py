# Topic: S4. Config Parsing / Validation (dicts, nested merge, schema)
# Section: 11. SRE/Platform Day-to-Day Scripting & Automation
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

import json
 
def deep_merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and \
                isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v              # scalars/lists replace
    return out
 
SCHEMA = {"service": str, "replicas": int,
          "resources": {"cpu": str, "memory": str}}
 
def validate(cfg, schema, path=""):
    errors = []
    for key, typ in schema.items():
        where = f"{path}.{key}" if path else key
        val = cfg.get(key)
        if key not in cfg:
            errors.append(f"missing {where}")
        elif isinstance(typ, dict):
            if isinstance(val, dict):
                errors += validate(val, typ, where)
            else:
                errors.append(f"{where}: expected mapping")
        elif not isinstance(val, typ) or (
                typ is int and isinstance(val, bool)):
            name = typ.__name__
            errors.append(f"{where}: expected {name}")
    return errors
 
base = json.loads('{"service": "api", "replicas": 2,'
                  ' "resources": {"cpu": "500m",'
                  ' "memory": "1Gi"}}')
prod = {"replicas": 6, "resources": {"memory": "4Gi"}}
cfg = deep_merge(base, prod)
assert cfg["resources"] == {"cpu": "500m", "memory": "4Gi"}
assert base["resources"]["memory"] == "1Gi"   # untouched
assert validate(cfg, SCHEMA) == []
bad = {"service": "api", "replicas": True,
       "resources": {"cpu": 2}}
assert validate(bad, SCHEMA) == [
    "replicas: expected int", "resources.cpu: expected str",
    "missing resources.memory"]
