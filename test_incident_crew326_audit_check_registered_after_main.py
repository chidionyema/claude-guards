"""crew#326: c_hook_router was appended to CHECKS after `raise SystemExit(main())`, so the
scheduled audit ran it never and the overwritten router went ungraded for three days.
Rule: every CHECKS.append in estate_audit.py precedes the __main__ guard."""
import pathlib

SRC = pathlib.Path(__file__).resolve().parent / "estate" / "estate_audit.py"


def test_incident_crew326_every_check_registered_before_main():
    lines = SRC.read_text().splitlines()
    main_at = next(i for i, l in enumerate(lines) if l.startswith('if __name__ == "__main__":'))
    late = [i + 1 for i, l in enumerate(lines) if l.startswith("CHECKS.append(") and i > main_at]
    assert late == [], f"checks registered after __main__ (never run by launchd): lines {late}"
    assert any(l.startswith("CHECKS.append(c_hook_router)") for l in lines[:main_at])


def test_incident_crew326_guard_refuses_the_bad_shape(tmp_path):
    bad = tmp_path / "x.py"
    bad.write_text('CHECKS = []\nif __name__ == "__main__":\n    pass\nCHECKS.append(c_late)\n')
    lines = bad.read_text().splitlines()
    main_at = next(i for i, l in enumerate(lines) if l.startswith('if __name__ == "__main__":'))
    assert [i for i, l in enumerate(lines) if l.startswith("CHECKS.append(") and i > main_at]
