#!/usr/bin/python3

import os
import sys
import apt
import gettext
import tempfile
import subprocess
import shutil
import syslog
from contextlib import contextmanager

# Localization
gettext.install("mintupdate", "/usr/share/locale")

# Global cache for disk space
_disk_space_cache = None


def print_error_and_exit(message):
    """Prints an error message to stdout and syslog, then exits the script."""
    print(f"ERROR: {message}")
    syslog.syslog(syslog.LOG_ERR, message)
    sys.exit(1)


def print_info(message):
    """Prints an informational message to stdout."""
    print(f"INFO: {message}")


def report_status(step):
    """Reports the status of a given step."""
    print(f"Starting: {step}")


def check_dependencies():
    """Checks if required dependencies are installed."""
    dependencies = ["synaptic", "update-grub", "apt-get"]
    for dep in dependencies:
        if shutil.which(dep) is None:
            print_error_and_exit(f"Required dependency {dep} is not installed.")


def get_disk_space():
    """Returns the available disk space in gigabytes."""
    global _disk_space_cache
    if _disk_space_cache is None:
        statvfs = os.statvfs("/")
        _disk_space_cache = (statvfs.f_frsize * statvfs.f_bavail) / 1024**3
    return _disk_space_cache


def check_disk_space(required_space_gb):
    """Checks if there is enough disk space available."""
    available_space_gb = get_disk_space()
    if available_space_gb < required_space_gb:
        print_error_and_exit(
            f"Not enough disk space. Required: {required_space_gb}GB, Available: {available_space_gb:.2f}GB"
        )


@contextmanager
def temporary_file():
    """Context manager for creating and cleaning up a temporary file."""
    f = tempfile.NamedTemporaryFile(delete=False)
    try:
        yield f
    finally:
        f.close()
        os.remove(f.name)


def run_command(command, error_message):
    """Runs a command and handles errors."""
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print_info(result.stdout)
    except subprocess.CalledProcessError as e:
        print_error_and_exit(
            f"{error_message} (Command: {' '.join(command)}): {e.stderr}"
        )


def manage_packages(packages, action, window_id):
    """Manages packages using Synaptic."""
    valid_packages = [pkg for pkg in packages if check_package_exists(pkg)]
    if valid_packages:
        cmd = [
            "sudo",
            "/usr/sbin/synaptic",
            "--hide-main-window",
            "--non-interactive",
            "--parent-window-id",
            str(window_id),
            "-o",
            "Synaptic::closeZvt=true",
            "--set-selections-file",
        ]
        with temporary_file() as f:
            for package in valid_packages:
                f.write(f"{package}\t{action}\n".encode("utf-8"))
            cmd.append(f.name)
        run_command(cmd, "Failed to manage packages")


def check_package_exists(package_name):
    """Checks if a package exists in the APT cache."""
    try:
        cache = apt.Cache()
        return package_name in cache
    except Exception as e:
        print_error_and_exit(f"Failed to check package {package_name}: {e}")


def file_to_list(filename):
    """Reads a file and returns a list of non-comment, non-empty lines."""
    if os.path.exists(filename):
        with open(filename, "r") as file_handle:
            return [
                line.strip()
                for line in file_handle
                if line.strip() and not line.startswith("#")
            ]
    return []


def backup_file(filepath):
    """Creates a backup of the specified file."""
    backup_path = f"{filepath}.bak"
    try:
        shutil.copy(filepath, backup_path)
        print_info(f"Backup created for {filepath}")
    except IOError as e:
        print_error_and_exit(f"Failed to create backup for {filepath}: {e}")
    return backup_path


def restore_backup(backup_path):
    """Restores a file from its backup."""
    original_path = backup_path.replace(".bak", "")
    try:
        shutil.move(backup_path, original_path)
        print_info(f"Backup restored for {original_path}")
    except IOError as e:
        print_error_and_exit(f"Failed to restore backup for {original_path}: {e}")


def update_apt_sources(sources_list):
    """Updates the APT sources list."""
    report_status("Updating APT sources")
    target_path = "/etc/apt/sources.list.d/official-package-repositories.list"
    backup_file(target_path)
    if os.path.exists(target_path):
        os.remove(target_path)
    shutil.copy(sources_list, target_path)


def upgrade_system(cache):
    """Upgrades the system using APT."""
    report_status("Upgrading system")
    try:
        cache.update()
        cache.open(None)
        cache.upgrade(True)
        cache.commit()
    except apt.cache.FetchFailedException as e:
        print_error_and_exit(f"APT update failed: {e}")
    except apt.cache.LockFailedException as e:
        print_error_and_exit(f"APT cache lock failed: {e}")
    except Exception as e:
        print_error_and_exit(f"Failed to perform system upgrade: {e}")


def update_grub():
    """Updates GRUB and adjusts the title."""
    report_status("Updating GRUB")
    run_command(["sudo", "update-grub"], "Couldn't update GRUB")
    adjust_grub_script = (
        "/usr/share/ubuntu-system-adjustments/systemd/adjust-grub-title"
    )
    if os.path.exists(adjust_grub_script):
        run_command([adjust_grub_script], "Couldn't adjust GRUB title")


def clean_system():
    """Cleans up unnecessary packages and APT cache."""
    report_status("Cleaning system")
    run_command(
        ["sudo", "apt-get", "autoremove", "-y"], "Failed to autoremove packages"
    )
    run_command(["sudo", "apt-get", "clean"], "Failed to clean APT cache")


if __name__ == "__main__":
    if os.getuid() != 0:
        print_error_and_exit("Run this code as root!")

    if len(sys.argv) != 3:
        print_error_and_exit(f"Usage: {sys.argv[0]} <codename> <window_id>")

    codename = sys.argv[1]
    window_id = int(sys.argv[2])
    base_path = os.path.join("/usr/share/mint-upgrade-info", codename)

    sources_list = os.path.join(base_path, "official-package-repositories.list")
    blacklist_filename = os.path.join(base_path, "blacklist")
    additions_filename = os.path.join(base_path, "additions")
    removals_filename = os.path.join(base_path, "removals")

    check_dependencies()
    check_disk_space(2)

    required_files = [
        sources_list,
        blacklist_filename,
        additions_filename,
        removals_filename,
    ]
    for file in required_files:
        if not os.path.exists(file):
            print_error_and_exit(f"Required file {file} not found.")

    try:
        update_apt_sources(sources_list)
        run_command(
            [
                "sudo",
                "/usr/sbin/synaptic",
                "--hide-main-window",
                "--update-at-startup",
                "--non-interactive",
                "--parent-window-id",
                str(window_id),
            ],
            "Failed to update APT cache",
        )

        cache = apt.Cache()
        upgrade_system(cache)

        additions = file_to_list(additions_filename)
        if additions:
            manage_packages(additions, "install", window_id)

        removals = file_to_list(removals_filename)
        if removals:
            manage_packages(removals, "deinstall", window_id)

        update_grub()
        clean_system()

    except Exception as e:
        print_error_and_exit(f"An unexpected error occurred: {e}")
