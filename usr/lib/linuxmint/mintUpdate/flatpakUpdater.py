#!/usr/bin/python3

import os
import json
import subprocess
import sys
import gi
import logging
from contextlib import contextmanager

gi.require_version("GLib", "2.0")
from gi.repository import GLib

LOG_PATH = os.path.join(
    GLib.get_home_dir(), ".linuxmint", "mintupdate", "flatpak-updates.log"
)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

try:
    if not GLib.find_program_in_path("flatpak"):
        raise RuntimeError("Flatpak is not installed or not in PATH")
    gi.require_version("Flatpak", "1.0")
    from gi.repository import Flatpak
except Exception as e:
    logging.error(f"No Flatpak support - {e}")
    raise NotImplementedError

from Classes import FlatpakUpdate

UPDATE_WORKER_PATH = "/usr/lib/linuxmint/mintUpdate/flatpak-update-worker.py"


@contextmanager
def managed_subprocess(argv):
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


class FlatpakUpdater:
    def __init__(self):
        self.updates = []
        self.error = None
        self.proc = None
        self.in_pipe = None
        self.out_pipe = None

    def run_subprocess(self, argv, timeout=30):
        try:
            result = subprocess.run(
                argv,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            result.check_returncode()
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logging.error(f"Flatpaks: timed out trying to run command {argv}")
            return None
        except subprocess.CalledProcessError as e:
            logging.error(f"Flatpaks: error during command {argv} - {e.stderr.strip()}")
            return None
        except Exception as e:
            logging.error(f"Flatpaks: unexpected error - {e}")
            return None

    def refresh(self):
        self.kill_any_helpers()
        self.run_subprocess([UPDATE_WORKER_PATH, "--refresh"])

    def fetch_updates(self):
        self.kill_any_helpers()
        output = self.run_subprocess([UPDATE_WORKER_PATH, "--fetch-updates"])

        if not output:
            logging.info("Flatpaks: no updates")
            return

        if output == "no-installed":
            logging.info("Flatpaks: skipping update check - nothing installed")
            return

        if output.startswith("error:"):
            self.error = output[6:]
            logging.error(f"Flatpaks: error from fetch-updates call: {self.error}")
            return

        try:
            json_data = json.loads(output)
            self.updates = [FlatpakUpdate.from_json(item) for item in json_data]
        except json.JSONDecodeError:
            logging.error("Flatpaks: unable to parse updates list")

        logging.info("Flatpak: done generating updates")

    def prepare_start_updates(self, updates):
        argv = [UPDATE_WORKER_PATH, "--update-packages"] + [
            update.ref.format_ref() for update in updates
        ]

        with managed_subprocess(argv) as proc:
            self.proc = proc
            self.in_pipe = proc.stdin
            self.out_pipe = proc.stdout

            if self.out_pipe.readline().strip() != "ready":
                raise RuntimeError("Unexpected response from worker - expected 'ready'")

    def confirm_start(self):
        try:
            self.in_pipe.write("confirm\n")
            self.in_pipe.flush()

            if self.out_pipe.readline().strip() == "yes":
                return True
            else:
                self.terminate_helper()
                return False
        except Exception as e:
            logging.error(f"Flatpaks: Could not complete confirmation: {e}")
            self.terminate_helper()
            return False

    def perform_updates(self):
        try:
            self.in_pipe.write("start\n")
            self.in_pipe.flush()

            response = self.out_pipe.readline().strip()
            if response == "done":
                logging.info("Flatpaks: updates complete")
            elif response.startswith("error:"):
                self.error = response[6:]
                logging.error(f"Flatpaks: error performing updates: {self.error}")
        except Exception as e:
            logging.error(f"Flatpaks: Could not perform updates: {e}")
        finally:
            self.terminate_helper()

    def terminate_helper(self):
        if self.proc:
            if self.proc.poll() is None:  # Process is still running
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            if self.in_pipe:
                self.in_pipe.close()
            if self.out_pipe:
                self.out_pipe.close()
            self.proc = None

    def kill_any_helpers(self):
        try:
            subprocess.run(["pkill", "-f", "flatpak-update-worker"], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error killing helpers: {e}")


if __name__ == "__main__":
    updater = FlatpakUpdater()
    updater.refresh()
    updater.fetch_updates()
    if updater.updates:
        updater.prepare_start_updates(updater.updates)
        if updater.confirm_start():
            updater.perform_updates()

