"""Fork: the entrypoint must hand a root-owned uploads directory to the app user.

Runs the real docker-entrypoint.sh with the system commands it calls replaced
by stubs, so the test needs neither root nor Docker. The stubbed ``stat``
reports ownership from a table; ``chown`` records what it was asked to fix.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / 'docker-entrypoint.sh'


def _stub(bindir, name, body):
    path = bindir / name
    path.write_text('#!/bin/bash\n' + body + '\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, owners, upload_folder=None):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    log = tmp_path / 'chown.log'
    log.touch()
    table = '\n'.join(f'"{d}") echo "{o}";;' for d, o in owners.items())
    _stub(bindir, 'id', 'echo 1000')
    _stub(bindir, 'groupmod', 'exit 0')
    _stub(bindir, 'usermod', 'exit 0')
    _stub(bindir, 'mkdir', 'exit 0')
    _stub(bindir, 'gosu', 'exit 0')
    _stub(bindir, 'chown', f'echo "$@" >> "{log}"')
    _stub(bindir, 'stat', f'case "${{@: -1}}" in\n{table}\n*) echo "1000:1000";;\nesac')
    env = {'PATH': f'{bindir}:/usr/bin:/bin', 'PUID': '1000', 'PGID': '1000'}
    if upload_folder:
        env['UPLOAD_FOLDER'] = upload_folder
    subprocess.run(['bash', str(ENTRYPOINT), 'true'], env=env, check=True,
                   capture_output=True, text=True)
    return log.read_text().splitlines()


@pytest.mark.skipif(os.name == 'nt', reason='bash entrypoint')
def test_root_owned_uploads_is_fixed_when_data_is_already_correct(tmp_path):
    calls = _run(tmp_path, {'/app/data': '1000:1000', '/app/data/uploads': '0:0'})
    assert calls == ['-R may:may /app/data/uploads']


@pytest.mark.skipif(os.name == 'nt', reason='bash entrypoint')
def test_nothing_is_chowned_when_everything_is_owned_correctly(tmp_path):
    assert _run(tmp_path, {}) == []


@pytest.mark.skipif(os.name == 'nt', reason='bash entrypoint')
def test_wrong_data_dir_is_still_fixed(tmp_path):
    calls = _run(tmp_path, {'/app/data': '0:0'})
    assert calls == ['-R may:may /app/data']


@pytest.mark.skipif(os.name == 'nt', reason='bash entrypoint')
def test_custom_upload_folder_is_checked(tmp_path):
    calls = _run(tmp_path, {'/srv/uploads': '0:0'}, upload_folder='/srv/uploads')
    assert calls == ['-R may:may /srv/uploads']
