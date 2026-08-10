"""Every named job, fed to pytest — the whole of the runner.

The job table lives in pyproject.toml under [tool.cool8.jobs]; the
group name is the pytest marker (`pytest -m rtl`), xdist fans jobs out
(`-n auto`), `--durations` says where the time went. This file only
reads the table and shells each job exactly as a person would run it —
it deliberately holds no policy of its own, so there is nothing here
to drift from the documentation. docs/12-tasks.md is normative for
what each job proves.

Each job gets its own build directory (COOL8_BUILD), as the old runner
gave it, so parallel jobs never race over an artifact.
"""

import os
import subprocess
import sys
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
    _CFG = tomllib.load(fh)["tool"]["cool8"]


def _params():
    for group, jobs in _CFG["jobs"].items():
        for job in jobs:
            marks = [getattr(pytest.mark, group)]
            if job.get("slow"):
                marks.append(pytest.mark.slow)
            yield pytest.param(group, job, marks=marks,
                               id=f"{group}-{job['id']}")


@pytest.mark.parametrize("group,job", list(_params()))
def test_job(group, job):
    env = dict(os.environ)
    env.setdefault("COOL8_BUILD", os.path.join(
        ROOT, *_CFG["buildRoot"].split("/"), "jobs", f"{group}-{job['id']}"))
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, *job["run"].split("/"))]
        + job.get("args", []),
        cwd=ROOT, env=env, capture_output=True, text=True)
    # Passed means exit 0 AND no "FAIL" in the output — two suites
    # report a count rather than a status, and an exit code alone would
    # take their word for it. The old runner's rule, kept.
    if r.returncode != 0 or "FAIL" in r.stdout:
        pytest.fail(f"{job['run']} exited {r.returncode}\n"
                    f"{r.stdout[-4000:]}\n{r.stderr[-2000:]}",
                    pytrace=False)
