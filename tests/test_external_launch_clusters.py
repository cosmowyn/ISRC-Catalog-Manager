from __future__ import annotations

import subprocess

from isrc_manager import external_launch


def setup_function():
    external_launch.clear_external_launch_history()


def test_looks_like_test_process_respects_env_and_argv(monkeypatch):
    monkeypatch.delenv(external_launch.TEST_BLOCK_ENV_VAR, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)

    assert external_launch._looks_like_test_process(["app.py"]) is False
    assert external_launch._looks_like_test_process(["tests/test_something.py"]) is True
    assert external_launch._looks_like_test_process(["python", "-m", "pytest"]) is True
    monkeypatch.setenv(external_launch.TEST_BLOCK_ENV_VAR, "1")
    assert external_launch._looks_like_test_process(["app.py"]) is True


def test_command_token_launch_target_and_external_command_detection():
    assert external_launch._command_tokens(["open", "/tmp/file"], shell=False) == [
        "open",
        "/tmp/file",
    ]
    assert external_launch._command_tokens("open '/tmp/file name'", shell=True) == [
        "open",
        "/tmp/file name",
    ]
    assert (
        external_launch._launch_target_from_command(["xdg-open", "/tmp/file"], shell=False)
        == "/tmp/file"
    )

    assert (
        external_launch._looks_like_external_launch_command(
            ["cmd", "/c", "start", "https://example.test"],
            shell=False,
        )
        is True
    )
    assert (
        external_launch._looks_like_external_launch_command(
            ["powershell", "-Command", "Start-Process https://example.test"],
            shell=False,
        )
        is True
    )
    assert (
        external_launch._looks_like_external_launch_command(
            ["osascript"],
            shell=False,
            input_payload='tell application "Finder" to reveal POSIX file "/tmp/file"',
        )
        is True
    )
    assert (
        external_launch._looks_like_external_launch_command(["python", "-V"], shell=False) is False
    )


def test_blocked_completed_process_and_popen_shim_support_text_and_bytes():
    text_result = external_launch._blocked_completed_process(
        ["open", "/tmp/file"],
        {"text": True},
    )
    assert text_result.returncode == 0
    assert text_result.stdout == ""
    assert text_result.stderr == ""

    byte_result = external_launch._blocked_completed_process(["open", "/tmp/file"], {})
    assert byte_result.stdout == b""
    assert byte_result.stderr == b""

    blocked = external_launch._BlockedPopen(["open", "/tmp/file"], text_mode=True)
    assert blocked.communicate() == ("", "")
    assert blocked.wait() == 0
    assert blocked.poll() == 0
    blocked.terminate()
    assert blocked.returncode == -15
    blocked.kill()
    assert blocked.returncode == -9


def test_patched_subprocess_helpers_record_and_block_launcher_commands(monkeypatch):
    external_launch.set_external_launch_blocking(True, blocked_return_value=True)

    assert external_launch._patched_subprocess_call(["open", "/tmp/file"]) == 0
    assert external_launch._patched_subprocess_check_call(["xdg-open", "/tmp/file"]) == 0
    assert external_launch._patched_subprocess_check_output(["open", "/tmp/file"], text=True) == ""
    popen = external_launch._patched_subprocess_popen(["open", "/tmp/file"], text=True)
    assert isinstance(popen, external_launch._BlockedPopen)
    assert external_launch._patched_os_system("open /tmp/file") == 0

    launches = external_launch.external_launch_history()
    assert [launch.via for launch in launches] == [
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "os.system",
    ]

    called = []
    monkeypatch.setattr(
        external_launch,
        "_ORIGINAL_SUBPROCESS_RUN",
        lambda *args, **kwargs: called.append((args, kwargs))
        or subprocess.CompletedProcess(args, 0),
    )
    result = external_launch._patched_subprocess_run(["python", "-V"])
    assert result.returncode == 0
    assert called


def test_file_dialog_metadata_and_patched_dialogs_record_blocked_desktop_dialogs():
    details = external_launch._file_dialog_kwargs(
        ("parent", "Choose File", "/tmp", "*.wav", "selected"),
        {"options": "DontUseNativeDialog"},
    )
    assert details == {
        "caption": "Choose File",
        "directory": "/tmp",
        "filter": "*.wav",
        "selected_filter": "selected",
        "options": "DontUseNativeDialog",
    }

    assert external_launch._patched_qfiledialog_get_open_file_name(
        "parent",
        "Open",
        "/tmp",
        "*.wav",
    ) == ("", "")
    assert external_launch._patched_qfiledialog_get_open_file_names("parent", "Open Many") == (
        [],
        "",
    )
    assert external_launch._patched_qfiledialog_get_save_file_name("parent", "Save") == ("", "")
    assert external_launch._patched_qfiledialog_get_existing_directory("parent", "Folder") == ""

    launches = external_launch.external_launch_history()
    assert [launch.via for launch in launches] == [
        "QFileDialog.getOpenFileName",
        "QFileDialog.getOpenFileNames",
        "QFileDialog.getSaveFileName",
        "QFileDialog.getExistingDirectory",
    ]
    assert all(launch.blocked for launch in launches)


def test_temporary_blocking_restores_state_and_open_path_records_metadata(tmp_path):
    external_launch.set_external_launch_blocking(False, blocked_return_value=False)
    before = external_launch.external_launch_blocking_enabled()
    with external_launch.temporary_external_launch_blocking(True, blocked_return_value=False):
        assert external_launch.external_launch_blocking_enabled() is True
        target = tmp_path / "file.txt"
        assert (
            external_launch.open_external_path(
                target,
                source="test",
                metadata={"kind": "fixture"},
            )
            is False
        )
    assert external_launch.external_launch_blocking_enabled() is before

    launch = external_launch.external_launch_history()[-1]
    assert launch.via == "external_launch.open_external_url"
    assert launch.source == "test"
    assert launch.metadata["kind"] == "fixture"
    assert launch.metadata["local_path"] == str(target)


def test_patched_webbrowser_open_variants_record_and_respect_blocking(monkeypatch):
    external_launch.set_external_launch_blocking(True, blocked_return_value=False)

    assert external_launch._patched_webbrowser_open("https://example.test") is False
    assert external_launch._patched_webbrowser_open_new("https://example.test/new") is False
    assert external_launch._patched_webbrowser_open_new_tab("https://example.test/tab") is False

    assert [launch.via for launch in external_launch.external_launch_history()] == [
        "webbrowser.open",
        "webbrowser.open_new",
        "webbrowser.open_new_tab",
    ]

    external_launch.clear_external_launch_history()
    external_launch.set_external_launch_blocking(False)
    monkeypatch.setattr(external_launch, "_ORIGINAL_WEBBROWSER_OPEN", lambda *args, **kwargs: True)
    assert external_launch._patched_webbrowser_open("https://example.test") is True


def test_external_launch_fallbacks_and_url_dialog_shims(monkeypatch, tmp_path):
    external_launch.set_external_launch_blocking(True, blocked_return_value=True)
    monkeypatch.delenv(external_launch.TEST_BLOCK_ENV_VAR, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setattr(external_launch.sys, "argv", [])

    assert external_launch._looks_like_test_process([]) is False
    assert external_launch._command_tokens("open 'unterminated", shell=True) == [
        "open",
        "'unterminated",
    ]
    assert external_launch._launch_target_from_command([], shell=False) == ""
    assert (
        external_launch._looks_like_external_launch_command(
            ["osascript"],
            shell=False,
            input_payload=b'display dialog "Choose wisely"',
        )
        is True
    )

    assert external_launch._patched_qfiledialog_get_existing_directory_url("parent", "Folder")
    open_url_result = external_launch._patched_qfiledialog_get_open_file_url(
        "parent",
        "Open URL",
    )
    assert isinstance(open_url_result, tuple)
    assert external_launch._patched_qfiledialog_get_open_file_urls("parent", "Open URLs") == (
        [],
        "",
    )
    save_url_result = external_launch._patched_qfiledialog_get_save_file_url(
        "parent",
        "Save URL",
    )
    assert isinstance(save_url_result, tuple)
    assert [launch.via for launch in external_launch.external_launch_history()[-4:]] == [
        "QFileDialog.getExistingDirectoryUrl",
        "QFileDialog.getOpenFileUrl",
        "QFileDialog.getOpenFileUrls",
        "QFileDialog.getSaveFileUrl",
    ]

    with external_launch.temporary_external_launch_blocking(False):
        monkeypatch.setattr(external_launch, "_ORIGINAL_QDESKTOPSERVICES_OPENURL", None)
        assert external_launch.open_external_url("https://example.test/fallback") is False

        called = []
        monkeypatch.setattr(
            external_launch,
            "_ORIGINAL_SUBPROCESS_RUN",
            lambda *args, **kwargs: called.append((args, kwargs))
            or subprocess.CompletedProcess(args[0], 7, stdout="ok", stderr=""),
        )
        result = external_launch.run_external_launcher_subprocess(
            ["python", "-V"],
            text=True,
            source="unblocked-test",
            metadata={"fixture": str(tmp_path)},
        )
        assert result.returncode == 7
        assert called

    assert external_launch.external_launch_history()[-1].source == "unblocked-test"
