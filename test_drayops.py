import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drayops import create_app
from drayops.services.executor import ActionExecutor
from drayops.services.presets import PresetService
from drayops.services.registry import RegistryService


class TestDrayOpsServices(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.data_dir = self.temp_dir / "data"
        self.registry = RegistryService(self.data_dir)
        self.repo_root = Path(__file__).resolve().parent
        self.presets = PresetService(self.repo_root / "drayops" / "presets")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_list_presets(self):
        preset_ids = {preset["id"] for preset in self.presets.list_presets()}
        self.assertIn("aion-vast", preset_ids)
        self.assertIn("aion-local-wsl", preset_ids)
        self.assertIn("syncforge-local", preset_ids)

    def test_create_target(self):
        preset = self.presets.get_preset("aion-vast")
        target = self.registry.create_target(preset, {"name": "Aion Prod", "instance_id": "123"})
        self.assertEqual(target["name"], "Aion Prod")
        self.assertEqual(target["config"]["instance_id"], "123")
        self.assertTrue(target["config_fields"])
        self.assertEqual(len(self.registry.list_targets()), 1)

    def test_update_target(self):
        preset = self.presets.get_preset("syncforge-local")
        target = self.registry.create_target(preset, {"name": "SyncForge Test"})

        updated = self.registry.update_target(
            target["id"],
            {"name": "SyncForge Local", "config": {"project_path": "C:\\projects\\filetransfer"}},
        )

        self.assertEqual(updated["name"], "SyncForge Local")
        self.assertEqual(updated["config"]["project_path"], "C:\\projects\\filetransfer")

    def test_delete_target(self):
        preset = self.presets.get_preset("syncforge-local")
        target = self.registry.create_target(preset, {"name": "Delete Me"})

        deleted = self.registry.delete_target(target["id"])

        self.assertTrue(deleted)
        self.assertEqual(self.registry.list_targets(), [])

    @patch("drayops.services.executor.subprocess.run")
    def test_local_action_executes_command(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "ok"
        mock_run.return_value.stderr = ""
        executor = ActionExecutor()
        target = {
            "name": "Local SyncForge",
            "target_type": "local",
            "config": {"project_path": "C:\\projects\\merge_syncforge"},
            "actions": {"start": {"command": "echo hi", "cwd": "C:\\aion", "timeout": 10}},
        }

        result = executor.execute(target, "start", {})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["command"], "echo hi")
        self.assertFalse(result["run_in_wsl"])

    @patch("drayops.services.executor.os.name", "nt")
    @patch("drayops.services.executor.subprocess.run")
    def test_local_action_can_run_in_wsl(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "ok"
        mock_run.return_value.stderr = ""
        executor = ActionExecutor()
        target = {
            "name": "WSL SyncForge",
            "target_type": "local",
            "config": {"project_path": "C:\\projects\\merge_syncforge", "run_in_wsl": "true"},
            "actions": {"deploy": {"command": "bash deploy.sh", "timeout": 10}},
        }

        result = executor.execute(target, "deploy", {})

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["run_in_wsl"])
        self.assertEqual(
            result["resolved_command"],
            ["wsl", "bash", "-lc", "cd /mnt/c/projects/merge_syncforge && bash deploy.sh"],
        )
        mock_run.assert_called_once()
        called_args, called_kwargs = mock_run.call_args
        self.assertEqual(called_args[0], ["wsl", "bash", "-lc", "cd /mnt/c/projects/merge_syncforge && bash deploy.sh"])
        self.assertFalse(called_kwargs["shell"])
        self.assertIsNone(called_kwargs["cwd"])

    @patch("drayops.services.executor.os.name", "posix")
    @patch("drayops.services.executor.subprocess.run")
    def test_local_action_uses_bash_directly_when_running_in_wsl(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "ok"
        mock_run.return_value.stderr = ""
        executor = ActionExecutor()
        target = {
            "name": "WSL Native",
            "target_type": "local",
            "config": {"project_path": "C:\\aion", "run_in_wsl": "true"},
            "actions": {"start": {"command": "pwd", "timeout": 10}},
        }

        result = executor.execute(target, "start", {})

        self.assertEqual(result["resolved_command"], ["bash", "-lc", "cd /mnt/c/aion && pwd"])

    @patch("drayops.services.executor.subprocess.run")
    def test_local_action_renders_template_values(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "200"
        mock_run.return_value.stderr = ""
        executor = ActionExecutor()
        target = {
            "name": "Aion Local",
            "target_type": "local",
            "config": {
                "project_path": "C:\\aion",
                "run_in_wsl": "true",
                "host": "127.0.0.1",
                "port": "5001",
            },
            "actions": {
                "health": {
                    "command": ".venv/bin/python3 -c \"print('http://{{host}}:{{port}}/')\"",
                    "timeout": 10,
                }
            },
        }

        result = executor.execute(target, "health", {})

        self.assertEqual(result["status"], "completed")
        self.assertIn("http://127.0.0.1:5001/", result["resolved_command"][-1])

    @patch("drayops.services.executor.vast.redeploy_code")
    def test_vast_redeploy_requires_connection_info(self, mock_redeploy):
        executor = ActionExecutor()
        target = {
            "name": "Aion Vast",
            "target_type": "vast",
            "config": {"instance_id": "123"},
            "actions": {"redeploy": {}},
        }

        with self.assertRaisesRegex(ValueError, "ssh_port is required"):
            executor.execute(target, "redeploy", {})

        mock_redeploy.assert_not_called()

    @patch("drayops.services.executor.vast.build_ssh_command", return_value="ssh root@test")
    @patch("drayops.services.executor.vast.get_ssh_details")
    @patch("drayops.services.executor.subprocess.Popen")
    @patch.dict("drayops.services.executor.os.environ", {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False)
    def test_vast_connect_syncs_and_returns_command(self, mock_popen, mock_get_ssh_details, mock_build_ssh):
        mock_get_ssh_details.return_value = {
            "instance_id": 123,
            "ssh_host": "ssh4.vast.ai",
            "ssh_port": 30123,
            "status": "running",
        }
        executor = ActionExecutor()
        target = {
            "name": "Aion Vast",
            "target_type": "vast",
            "config": {"instance_id": "123"},
            "actions": {"connect": {}},
        }

        result = executor.execute(target, "connect", {})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["ssh_command"], "ssh root@test")
        self.assertEqual(result["config_updates"]["ssh_host"], "ssh4.vast.ai")
        mock_popen.assert_called_once()
        self.assertEqual(result["terminal_launch"]["mode"], "wsl-terminal")
        mock_build_ssh.assert_called_once_with("ssh4.vast.ai", 30123)

    @patch("drayops.services.executor.vast.get_ssh_details")
    @patch("drayops.services.executor.vast.deploy_on_offer")
    def test_deploy_vast_instance_handles_numeric_contract_id(self, mock_deploy, mock_get_ssh_details):
        mock_deploy.return_value = {"success": True, "new_contract": 4321}
        mock_get_ssh_details.return_value = {
            "instance_id": 4321,
            "ssh_host": "ssh4.vast.ai",
            "ssh_port": 30123,
            "status": "running",
        }
        executor = ActionExecutor()

        result = executor.deploy_vast_instance("aion-vast", 999, {"disk_gb": 40})

        self.assertEqual(result["instance_id"], 4321)
        self.assertEqual(result["config_updates"]["ssh_port"], "30123")


class TestDrayOpsApi(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo_root = Path(__file__).resolve().parent
        self.app.config["TESTING"] = True
        self.app.config["DRAYOPS_BASE_DIR"] = self.temp_dir
        (self.temp_dir / "presets").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "data").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.repo_root / "drayops" / "presets" / "syncforge-local.json",
            self.temp_dir / "presets" / "syncforge-local.json",
        )
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_target_patch_updates_config(self):
        create_response = self.client.post(
            "/api/targets",
            json={"preset_id": "syncforge-local", "overrides": {"name": "SyncForge API"}},
        )
        self.assertEqual(create_response.status_code, 201)
        target_id = create_response.get_json()["target"]["id"]

        update_response = self.client.patch(
            f"/api/targets/{target_id}",
            json={"config": {"project_path": "C:\\projects\\merge_syncforge_alt"}},
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(
            update_response.get_json()["target"]["config"]["project_path"],
            "C:\\projects\\merge_syncforge_alt",
        )


if __name__ == "__main__":
    unittest.main()
