"""Minimal stage-separated quality report, not an accepted-revision system."""
from .spec import SpecError, fields

STAGES = ("specification", "execution", "structure", "visual", "domain", "export", "target_compatibility")
STATES = ("passed", "failed", "not_run", "not_applicable")


def report(passed=(), failed=None):
    result = {"schema_version": 1, "acceptance": "not_evaluated", "stages": {}}
    for stage in STAGES:
        state = "passed" if stage in passed else "not_run"
        reason = "Phase 2A does not evaluate this stage"
        evidence = []
        if stage in passed:
            reason = {"specification": "Strict schema and compile contracts passed",
                      "execution": "Blender process and result protocol passed",
                      "structure": "Actual artifacts validated after .blend reopening"}[stage]
            evidence = {"specification": ["plan.json", "skills.lock.json"], "execution": ["execution.json", "result.json"],
                        "structure": ["validation.json", "artifact-manifest.json"]}[stage]
        if failed and stage == failed[0]:
            state, reason = "failed", failed[1]
        result["stages"][stage] = {"state": state, "reason": reason, "evidence": evidence}
    return validate_report(result)


def validate_report(value):
    if isinstance(value,dict) and value.get('schema_version')==2:
        from .quality_profiles import validate_quality_report
        return validate_quality_report(value)
    fields(value, "QualityReport", ("schema_version", "acceptance", "stages"))
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
        or value["acceptance"] != "not_evaluated" or not isinstance(value["stages"],dict) or set(value["stages"]) != set(STAGES)):
        raise SpecError("QualityReport: invalid version, stages or unsupported acceptance promotion")
    for stage, entry in value["stages"].items():
        fields(entry, f"quality.{stage}", ("state", "reason", "evidence"))
        if (entry["state"] not in STATES or not isinstance(entry["reason"], str) or not entry["reason"]
            or not isinstance(entry["evidence"], list) or not all(isinstance(x, str) for x in entry["evidence"])):
            raise SpecError(f"quality.{stage}: invalid state/reason/evidence")
    return value
