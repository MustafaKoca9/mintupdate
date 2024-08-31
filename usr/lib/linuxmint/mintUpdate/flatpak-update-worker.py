#!/usr/bin/python3
# -*- coding: utf-8 -*-

import functools
import os
import argparse
import json
import sys
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Flatpak", "1.0")
from gi.repository import Gtk, GLib, Flatpak, Gio

from mintcommon.installer import installer
from mintcommon.installer import _flatpak
from Classes import FlatpakUpdate

CHUNK_SIZE = 4096
LOG_PATH = os.path.join(
    GLib.get_home_dir(), ".linuxmint", "mintupdate", "flatpak-updates.log"
)

DEBUG_MODE = os.getenv("DEBUG", "0") == "1"


def debug(*args):
    """Print debug messages if debug mode is enabled."""
    if DEBUG_MODE:
        sanitized = [str(arg) for arg in args if arg is not None]
        argstr = " ".join(sanitized)
        print(f"flatpak-update-worker (DEBUG): {argstr}", file=sys.stderr, flush=True)


def warn(*args):
    """Print warning messages."""
    sanitized = [str(arg) for arg in args if arg is not None]
    argstr = " ".join(sanitized)
    print(f"flatpak-update-worker (WARN): {argstr}", file=sys.stderr, flush=True)


class FlatpakUpdateWorker:
    def __init__(self):
        self.installer = installer.Installer(installer.PKG_TYPE_FLATPAK)
        self.fp_sys = _flatpak.get_fp_sys()
        self.task = None
        self.cancellable = Gio.Cancellable()
        self.stdin = Gio.UnixInputStream.new(sys.stdin.fileno(), True)
        self.updates = []

        if not self.check_for_any_installed():
            self.send_to_updater("no-installed")
            self.cancellable.cancel()
            self.quit()

    def check_for_any_installed(self):
        """Check if there are any installed Flatpak applications."""
        try:
            installed = self.fp_sys.list_installed_refs(self.cancellable)
        except GLib.Error as e:
            warn(f"GLib error while listing installed refs: {str(e)}")
            installed = []
        except Exception as e:
            warn(f"Unexpected error while listing installed refs: {str(e)}")
            installed = []

        if not installed:
            debug("No Flatpaks installed, exiting without refreshing")
            return False

        debug(f"{len(installed)} Flatpaks installed, continuing")
        return True

    def refresh(self, init=True):
        """Refresh local Flatpak cache and appstream information."""
        if self.cancellable.is_cancelled():
            return

        self.fp_sys.cleanup_local_refs_sync(None)
        self.fp_sys.prune_local_repo(None)

        if init:
            self.installer.init_sync()

        self.installer.force_new_cache_sync()

    def fetch_updates(self):
        """Fetch available Flatpak updates."""
        if self.cancellable.is_cancelled():
            return

        if not self.installer.init_sync():
            warn("Cache not valid, refreshing")
            self.refresh(False)
        else:
            debug("Cache valid")

        self.installer.generate_uncached_pkginfos()
        debug("Generating updates")
        _flatpak._initialize_appstream_thread()

        self.updates = []
        self.installer.select_flatpak_updates(
            None,
            self._fetch_task_ready,
            self._fetch_updates_error,
            None,
            None,
            use_mainloop=False,
        )

    def _fetch_task_ready(self, task):
        """Handle the task when fetching updates is ready."""
        debug(f"Task object: {task}, transaction: {task.transaction}")

        self.task = task
        self.error = task.error_message

        if not self.error and task.transaction:
            self._process_fetch_task(task)
            out = json.dumps(self.updates, default=lambda o: o.to_json(), indent=4)
            self.send_to_updater(out)
        else:
            if self.error:
                self.send_to_updater(self.error)

        self.quit()
        debug("Done generating updates", self.error)

    def _fetch_updates_error(self, task):
        """Handle errors that occur during the fetch operation."""
        warn(f"Fetch error: {task.error_message}")

    def _process_fetch_task(self, task):
        """Process the fetch task to extract updates."""
        trans = task.transaction
        ops = trans.get_operations()

        def cmp_ref_name(a, b):
            ref_a = Flatpak.Ref.parse(a.get_ref())
            ref_b = Flatpak.Ref.parse(b.get_ref())
            return len(ref_a.get_name().split(".")) - len(ref_b.get_name().split("."))

        ops.sort(key=functools.cmp_to_key(cmp_ref_name))
        ops.sort(key=lambda op: Flatpak.Ref.parse(op.get_ref()).get_name())

        for op in ops:
            ref = Flatpak.Ref.parse(op.get_ref())
            debug(f"Operation: {op.get_ref()}")

            if op.get_operation_type() == Flatpak.TransactionOperationType.UPDATE:
                self._process_update_operation(op, ref)
            elif op.get_operation_type() == Flatpak.TransactionOperationType.INSTALL:
                self._process_install_operation(op, ref)

        task.cancel()

    def _process_update_operation(self, op, ref):
        """Process an update operation."""
        try:
            installed_ref = self.fp_sys.get_installed_ref(
                ref.get_kind(), ref.get_name(), ref.get_arch(), ref.get_branch(), None
            )
            installed_ref.load_appdata()
        except GLib.Error as e:
            if e.code == Flatpak.Error.NOT_INSTALLED:
                installed_ref = None
            else:
                warn(f"Error loading appdata for {ref.format_ref()}: {e}")

        pkginfo = self.installer.find_pkginfo(
            ref.get_name(), installer.PKG_TYPE_FLATPAK, remote=op.get_remote()
        )
        try:
            update = FlatpakUpdate(
                op, self.installer, ref, installed_ref, None, pkginfo
            )

            if self.is_base_package(update) or not self.add_to_parent_update(update):
                self.updates.append(update)
        except Exception as e:
            warn(f"Problem creating FlatpakUpdate for {ref.format_ref()}: {e}")

    def _process_install_operation(self, op, ref):
        """Process an install operation."""
        try:
            remote_ref = self.fp_sys.fetch_remote_ref_sync(
                op.get_remote(),
                ref.get_kind(),
                ref.get_name(),
                ref.get_arch(),
                ref.get_branch(),
                None,
            )
        except GLib.Error as e:
            debug(f"Can't add ref to install: {e.message}")
            remote_ref = None

        pkginfo = self.installer.find_pkginfo(
            ref.get_name(), installer.PKG_TYPE_FLATPAK, remote=op.get_remote()
        )
        try:
            update = FlatpakUpdate(op, self.installer, ref, None, remote_ref, pkginfo)

            if self.is_base_package(update) or not self.add_to_parent_update(update):
                self.updates.append(update)
        except Exception as e:
            warn(f"Problem creating FlatpakUpdate for {ref.format_ref()}: {e}")

    def add_to_parent_update(self, update):
        """Add the update to a parent update if applicable."""
        for maybe_parent in self.updates:
            if update.ref_name.startswith(maybe_parent.ref_name):
                maybe_parent.add_package(update)
                return True

            if self._is_extension_for_parent(maybe_parent, update):
                maybe_parent.add_package(update)
                return True

        return False

    def _is_extension_for_parent(self, parent, update):
        """Check if the update is an extension for the parent package."""
        try:
            kf = parent.metadata
            built_extensions = kf.get_string_list("Build", "built-extensions")
        except Exception:
            built_extensions = self._parse_group_extensions(parent.metadata)

        return any(update.ref_name.startswith(ext) for ext in built_extensions)

    def _parse_group_extensions(self, metadata):
        """Parse extensions from metadata groups."""
        groups, _ = metadata.get_groups()
        return [group.replace("Extension ", "") for group in groups]

    def is_base_package(self, update):
        """Determine if the update is a base package."""
        name = update.ref_name
        if name.startswith("app"):
            return True

        try:
            kf = update.metadata
            runtime_ref_id = f"runtime/{kf.get_string('Runtime', 'runtime')}"
            runtime_ref = Flatpak.Ref.parse(runtime_ref_id)
            return name == runtime_ref.get_name()
        except Exception:
            return False

    def prepare_start_updates(self, updates):
        """Prepare to start the update process for the provided updates."""
        if self.cancellable.is_cancelled():
            return

        debug("Creating real update task")
        self.error = None

        self.installer.select_flatpak_updates(
            updates,
            self._start_task_ready,
            self._start_updates_error,
            self._execute_finished,
            None,
        )

    def _start_task_ready(self, task):
        """Handle the task when updates are ready to start."""
        self.task = task
        self.send_to_updater("ready")
        self.stdin.read_bytes_async(
            CHUNK_SIZE, GLib.PRIORITY_DEFAULT, None, self.message_from_updater
        )

    def _start_updates_error(self, task):
        """Handle errors that occur when starting updates."""
        warn(f"Start updates error: {task.error_message}")
        self.send_to_updater(task.error_message)

    def confirm_start(self):
        """Confirm the start of updates."""
        if self.task.confirm():
            self.send_to_updater("yes")
        else:
            self.send_to_updater("no")
            self.quit()

    def start_updates(self):
        """Start the update process."""
        self.installer.execute_task(self.task)

    def _execute_finished(self, task):
        """Handle the completion of the update execution."""
        self.error = task.error_message
        self.write_to_log(task)
        self.send_to_updater("done")
        self.quit()

    def write_to_log(self, task):
        """Write transaction log entries to the log file."""
        try:
            entries = task.get_transaction_log()
            directory = Path(LOG_PATH).parent
            os.makedirs(directory, exist_ok=True)
            with open(LOG_PATH, "a") as f:
                for entry in entries:
                    f.write(f"{entry}\n")
        except Exception as e:
            warn(f"Can't write to flatpak update log: {e}")

    def send_to_updater(self, msg):
        """Send a message to the updater."""
        print(msg, flush=True)

    def message_from_updater(self, pipe, res):
        """Handle messages received from the updater."""
        if self.cancellable.is_cancelled():
            return

        try:
            bytes_read = pipe.read_bytes_finish(res)
        except GLib.Error as e:
            if e.code != Gio.IOErrorEnum.CANCELLED:
                warn(f"Error reading from updater: {e.message}")
            return

        if bytes_read:
            message = bytes_read.get_data().decode().strip("\n")
            debug(f"Receiving from updater: '{message}'")

            if message == "confirm":
                self.confirm_start()
            elif message == "start":
                self.start_updates()

        # Avoid potential infinite loop by ensuring we only read if not cancelled
        if not self.cancellable.is_cancelled():
            pipe.read_bytes_async(
                CHUNK_SIZE,
                GLib.PRIORITY_DEFAULT,
                self.cancellable,
                self.message_from_updater,
            )

    def quit(self):
        """Quit the application."""
        GLib.timeout_add(0, self.quit_on_ml)

    def quit_on_ml(self):
        """Perform cleanup and exit."""
        if self.task:
            self.task.cancel()

        self.cancellable.cancel()
        Gtk.main_quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flatpak worker for mintupdate")
    parser.add_argument(
        "-d", "--debug", help="Print debugging information.", action="store_true"
    )
    parser.add_argument(
        "-r",
        "--refresh",
        help="Refresh local flatpak cache and appstream info.",
        action="store_true",
    )
    parser.add_argument(
        "-f",
        "--fetch-updates",
        help="Get a JSON list of update info.",
        action="store_true",
    )
    parser.add_argument(
        "-u",
        "--update-packages",
        help="Update packages - one or more flatpak ref strings must be supplied.",
        action="store_true",
    )
    parser.add_argument(
        "refs", metavar="ref", type=str, nargs="*", help="Flatpak refs to update"
    )

    args = parser.parse_args()
    updater = FlatpakUpdateWorker()

    try:
        if args.refresh:
            updater.refresh()
        elif args.fetch_updates:
            updater.fetch_updates()
        elif args.update_packages:
            if not args.refs:
                print("Expected one or more space-separated Flatpak refs")
                exit(1)
            updater.prepare_start_updates(args.refs)
        else:
            print("Nothing to do")
    except KeyboardInterrupt:
        Gtk.main_quit()
    except Exception as e:
        warn(f"Unexpected error: {e}")
        exit(1)

    Gtk.main()

