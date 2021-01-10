import logging
import os
import subprocess

import pytest

import runez
from runez.conftest import verify_abort
from runez.program import RunResult


CHATTER = runez.log.tests_path("chatter")


@pytest.mark.skipif(runez.WINDOWS, reason="Not supported on windows")
def test_capture(monkeypatch):
    with runez.CurrentFolder(os.path.dirname(CHATTER)):
        # Check which finds programs in current folder
        assert runez.which("chatter") == CHATTER

    with runez.CaptureOutput(dryrun=True) as logged:
        # Dryrun mode doesn't fail (since it doesn't actually run the program)
        r = runez.run(CHATTER, "silent-fail", fatal=True)
        assert r.succeeded
        assert "[dryrun] " in r.output
        assert r.error == ""
        assert "Would run:" in logged.pop()

        r = runez.run(CHATTER, "silent-fail", stdout=None, stderr=None, fatal=True)
        assert r.succeeded
        assert r.output is None
        assert r.error is None
        assert "Would run:" in logged.pop()

    with runez.CaptureOutput(seed_logging=True) as logged:
        # Test success
        assert runez.run(CHATTER, "hello", fatal=False) == RunResult("hello", "", 0)
        assert runez.run(CHATTER, "hello", fatal=True) == RunResult("hello", "", 0)
        assert "chatter hello" in logged.pop()
        assert runez.run(CHATTER, stdout=None) == RunResult(None, "", 0)

        # Test no-wait
        r = runez.run(CHATTER, "hello", fatal=None, stdout=None, stderr=None)
        assert r.exit_code is None  # We don't know exit code because we didn't wait
        assert r.pid

        r = runez.run(CHATTER, stdout=None, stderr=None)
        if not runez.PY2:  # __bool__ not respected in PY2... no point trying to fix it
            assert r

        assert str(r) == "RunResult(exit_code=0)"
        assert r.succeeded
        assert r.output is None
        assert r.error is None
        assert r.full_output is None

        r = runez.run(CHATTER, "hello", path_env={"PATH": ":."})
        assert str(r) == "RunResult(exit_code=0)"
        assert r.succeeded
        assert r.output == "hello"
        assert r.error == ""
        assert r.full_output == "hello"

        # Test stderr
        r = runez.run(CHATTER, "complain")
        assert r.succeeded
        assert r.output == ""
        assert r.error == "complaining"
        assert r.full_output == "complaining"

        # Test failure
        assert "ERROR" in verify_abort(runez.run, CHATTER, "fail")

        r = runez.run(CHATTER, "silent-fail", fatal=False)
        assert str(r) == "RunResult(exit_code=1)"
        assert r.failed
        assert r.error == ""
        assert r.output == ""
        assert r.full_output == r.error

        r = runez.run(CHATTER, "fail", fatal=False)
        assert r.failed
        assert r.error == "failed"
        assert r.output == "hello there"
        assert r.full_output == "failed\nhello there"

        assert runez.run("/dev/null", fatal=False) == RunResult(None, "/dev/null is not installed", 1)
        assert "/dev/null is not installed" in verify_abort(runez.run, "/dev/null")

        with monkeypatch.context() as m:
            runez.conftest.patch_raise(m, subprocess, "Popen", OSError("testing"))
            r = runez.run("python", "--version", fatal=False)
            if not runez.PY2:  # __bool__ not respected in PY2... no point trying to fix it
                assert not r

            assert r.failed
            assert r.error == "python failed: testing"
            assert r.output is None
            assert r.full_output == "python failed: testing"

            with pytest.raises(OSError):
                runez.run("python", "--version")

        # Test convenience arg None filtering
        logged.clear()
        assert runez.run(CHATTER, "hello", "-a", 0, "-b", None, 1, 2, None, "foo bar") == RunResult("hello -a 0 1 2 foo bar", "", 0)
        assert 'chatter hello -a 0 1 2 "foo bar"' in logged.pop()


@pytest.mark.skipif(runez.WINDOWS, reason="Not supported on windows")
def test_executable(temp_folder):
    with runez.CaptureOutput(dryrun=True) as logged:
        assert runez.make_executable("some-file") == 1
        assert "Would make some-file executable" in logged.pop()
        assert runez.make_executable("some-file", logger=False) == 1
        assert not logged

    with runez.CaptureOutput() as logged:
        assert runez.touch("some-file") == 1
        assert "Touched some-file" in logged.pop()
        assert runez.delete("some-file") == 1
        assert "Deleted some-file" in logged.pop()
        assert runez.touch("some-file", logger=logging.debug) == 1
        assert "Touched some-file" in logged.pop()
        assert runez.make_executable("some-file", logger=logging.debug) == 1
        assert "Made 'some-file' executable" in logged.pop()
        assert runez.is_executable("some-file")
        assert runez.make_executable("some-file") == 0
        assert not logged

        assert runez.touch("some-file", logger=False) == 1
        assert runez.delete("some-file", logger=False) == 1
        assert not runez.is_executable("some-file")
        assert not logged

        assert runez.make_executable("/dev/null/some-file", fatal=False) == -1
        assert "does not exist, can't make it executable" in logged.pop()

        assert runez.make_executable("/dev/null/some-file", fatal=False, logger=None) == -1  # Don't log anything
        assert not logged

        assert runez.make_executable("/dev/null/some-file", fatal=False, logger=False) == -1  # Log errors only
        assert "does not exist, can't make it executable" in logged.pop()


def check_process_tree(pinfo, max_depth=10):
    """Verify that process info .parent does not recurse infinitely"""
    if pinfo:
        assert max_depth > 0
        check_process_tree(pinfo.parent, max_depth=max_depth - 1)


def test_ps(monkeypatch):
    p = runez.ps_info(os.getpid())
    check_process_tree(p)
    info = p.info

    assert info["PID"] in str(p)
    assert p.cmd
    assert p.cmd_basename
    assert p.ppid == os.getppid()
    assert p.userid != p.uid

    parent = p.parent
    assert parent.pid == p.ppid

    # Test edge cases on `cmd_basename` extraction
    p.cmd = "/dev/null/foo bar baz"
    del p.cmd_basename
    assert p.cmd_basename == "/dev/null/foo"  # Fall back to using 1st sequence with space as basename

    with monkeypatch.context() as m:
        m.setattr(runez.program, "is_executable", lambda x: x == "/dev/null/foo bar")
        del p.cmd_basename
        assert p.cmd_basename == "foo bar"

    uid = p.uid
    userid = p.userid
    if runez.to_int(info["UID"]) is None:
        info["UID"] = uid

    else:
        info["UID"] = userid

    # Trigger re-computation simulating opposite uid report by `ps`, verify it came back to the same values
    del p.uid
    del p.userid
    assert p.uid == uid
    assert p.userid == userid

    # Edge case for __repr__
    p.info = None
    assert str(p)


def test_which():
    assert runez.which(None) is None
    assert runez.which("/dev/null") is None
    assert runez.which("dev/null") is None
    assert runez.which("python")


def check_ri(platform, instructions=None):
    return verify_abort(runez.program.require_installed, "foo", instructions=instructions, platform=platform)


def test_require_installed(monkeypatch):
    monkeypatch.setattr(runez.program, "which", lambda x: "/bin/foo")
    assert runez.program.require_installed("foo") is None  # Does not raise

    monkeypatch.setattr(runez.program, "which", lambda x: None)
    r = check_ri("darwin")
    assert "foo is not installed, run: `brew install foo`" in r

    r = check_ri("linux")
    assert "foo is not installed, run: `apt install foo`" in r

    r = check_ri("darwin", instructions="custom instructions")
    assert "foo is not installed, custom instructions" in r

    r = check_ri(None)
    assert "foo is not installed:\n" in r
    assert "- on darwin: run: `brew install foo`" in r
    assert "- on linux: run: `apt install foo`" in r


def test_pids():
    assert not runez.check_pid(None)
    assert not runez.check_pid(0)
    assert not runez.check_pid("foo")  # garbage given, don't crash

    assert runez.check_pid(os.getpid())
    assert not runez.check_pid(1)  # No privilege to do this (tests shouldn't run as root)


@pytest.mark.skipif(runez.WINDOWS, reason="Not supported on windows")
def test_wrapped_run(monkeypatch):
    original = ["python", "-mvenv", "foo"]
    monkeypatch.delenv("PYCHARM_HOSTED", raising=False)
    with runez.program._WrappedArgs(original) as args:
        assert args == original

    monkeypatch.setenv("PYCHARM_HOSTED", "1")
    with runez.program._WrappedArgs(original) as args:
        assert args
        assert len(args) == 5
        assert args[0] == "/bin/sh"
        assert os.path.basename(args[1]) == "pydev-wrapper.sh"
