"""Tests for roomba_v4.__main__ CLI."""

from unittest.mock import patch

import pytest

from roomba_v4.__main__ import main


class TestCLIDiscover:
    @patch("roomba_v4.__main__.cmd_discover")
    def test_discover(self, mock_cmd):
        with patch("sys.argv", ["roomba-v4", "discover"]):
            main()
        mock_cmd.assert_called_once()


class TestCLICredentials:
    def test_start_requires_credentials(self):
        with (
            patch("sys.argv", ["roomba-v4", "start"]),
            patch.dict(
                "os.environ",
                {"ROOMBA_IP": "", "ROOMBA_BLID": "", "ROOMBA_PASSWORD": ""},
                clear=False,
            ),
        ):
            import roomba_v4.__main__ as cli_mod

            with (
                patch.object(cli_mod, "DEFAULT_IP", ""),
                patch.object(cli_mod, "DEFAULT_BLID", ""),
                patch.object(cli_mod, "DEFAULT_PASS", ""),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    cli_mod.main()
                assert exc_info.value.code == 1

    @patch("roomba_v4.__main__.cmd_robot")
    def test_start_with_args(self, mock_cmd):
        with patch(
            "sys.argv",
            [
                "roomba-v4",
                "start",
                "--ip",
                "10.0.0.1",
                "--blid",
                "TESTBLID",
                "--password",
                "testpass",
            ],
        ):
            main()
        mock_cmd.assert_called_once()
        args = mock_cmd.call_args[0][0]
        assert args.ip == "10.0.0.1"
        assert args.blid == "TESTBLID"


class TestCLIGetblid:
    @patch("roomba_v4.__main__.cmd_getblid")
    def test_getblid_command(self, mock_cmd):
        with patch("sys.argv", ["roomba-v4", "getblid", "--target", "10.0.0.1"]):
            main()
        mock_cmd.assert_called_once()

    def test_getblid_requires_target(self):
        import roomba_v4.__main__ as cli_mod

        with (
            patch("sys.argv", ["roomba-v4", "getblid"]),
            patch.object(cli_mod, "DEFAULT_IP", ""),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_mod.main()
            assert exc_info.value.code == 1

    @patch("roomba_v4.discovery.discover", return_value=[{"blid": "AABBCCDD"}])
    def test_getblid_prints_blid(self, mock_discover, capsys):
        with patch("sys.argv", ["roomba-v4", "getblid", "--target", "10.0.0.1"]):
            main()
        assert capsys.readouterr().out.strip() == "AABBCCDD"


class TestCLIGetpassword:
    @patch("roomba_v4.__main__.cmd_getpassword")
    def test_getpassword_command(self, mock_cmd):
        with patch("sys.argv", ["roomba-v4", "getpassword"]):
            main()
        mock_cmd.assert_called_once()

    def test_getpassword_empty_email_exits(self):
        with (
            patch("sys.argv", ["roomba-v4", "getpassword"]),
            patch("builtins.input", return_value=""),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestCLICommands:
    def test_unknown_command(self):
        with patch("sys.argv", ["roomba-v4", "nonexistent"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    @patch("roomba_v4.__main__.cmd_robot")
    def test_dock_command(self, mock_cmd):
        with patch(
            "sys.argv",
            [
                "roomba-v4",
                "dock",
                "--ip",
                "10.0.0.1",
                "--blid",
                "TESTBLID",
                "--password",
                "testpass",
            ],
        ):
            main()
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[0][0].command == "dock"

    def test_mop_only_on_start(self):
        """--mop is not accepted on non-start commands."""
        with patch(
            "sys.argv",
            [
                "roomba-v4",
                "stop",
                "--mop",
                "--ip",
                "1.2.3.4",
                "--blid",
                "X",
                "--password",
                "Y",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
