#!/usr/bin/python3

import argparse
import fnmatch
import os
import subprocess
import sys
import traceback
import logging

from checkAPT import APTCheck
from Classes import PRIORITY_UPDATES

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def is_blacklisted(blacklisted_packages, source_name, version):
    """Check if a package is blacklisted based on source name and version."""
    for blacklist in blacklisted_packages:
        bl_pkg, bl_ver = (blacklist.split("=", 1) + [None])[:2]
        if fnmatch.fnmatch(source_name, bl_pkg) and (
            bl_ver is None or bl_ver == version
        ):
            logging.info(f"Package {source_name} version {version} is blacklisted.")
            return True
    return False


def refresh_cache():
    """Refresh the APT cache."""
    try:
        subprocess.run(["sudo", "/usr/bin/mint-refresh-cache"], check=True)
        logging.info("APT cache refreshed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to refresh APT cache: {e}")
        sys.exit(1)


def load_blacklist(ignore_list):
    """Load the blacklist from file and combine with ignore list."""
    blacklisted = set()
    if os.path.exists("/etc/mintupdate.blacklist"):
        with open("/etc/mintupdate.blacklist") as blacklist_file:
            blacklisted = {
                line.strip()
                for line in blacklist_file
                if line.strip() and not line.strip().startswith("#")
            }
    if ignore_list:
        blacklisted.update(ignore_list.split(","))
    return blacklisted


def filter_updates(check, blacklisted, args):
    """Filter updates based on user options and blacklist."""
    updates = []
    for source_name in sorted(check.updates.keys()):
        update = check.updates[source_name]
        if (
            source_name in PRIORITY_UPDATES
            or (args.only_kernel and update.type == "kernel")
            or (args.only_security and update.type == "security")
            or not is_blacklisted(
                blacklisted, update.real_source_name, update.new_version
            )
        ):
            updates.append(update)
    return updates


def handle_list_command(updates):
    """Handle the 'list' command by printing the available updates."""
    for update in updates:
        print(f"{update.type:<15} {update.source_name:<45} {update.new_version}")


def handle_upgrade_command(updates, args):
    """Handle the 'upgrade' command by performing the package upgrade."""
    packages = [pkg for update in updates for pkg in update.package_names]
    arguments = ["apt-get", "install"] + packages

    if args.dry_run:
        arguments.append("--simulate")
    if args.yes:
        arguments.append("--assume-yes")
        if not args.keep_configuration:
            arguments.extend(["--option", "Dpkg::Options::=--force-confnew"])
    if args.install_recommends:
        arguments.append("--install-recommends")
    if args.keep_configuration:
        arguments.extend(["--option", "Dpkg::Options::=--force-confold"])

    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    try:
        result = subprocess.run(arguments, env=env, check=True)
        if result.returncode != 0:
            logging.error("Upgrade command failed.")
            sys.exit(result.returncode)
        logging.info("Upgrade completed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Upgrade command failed: {e}")
        sys.exit(e.returncode)


def main():
    """Main function to handle command-line arguments and perform actions."""
    parser = argparse.ArgumentParser(prog="mintupdate-cli")
    parser.add_argument(
        "command", help="Command to run (possible commands are: list, upgrade)"
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-k", "--only-kernel", action="store_true", help="Only include kernel updates"
    )
    group.add_argument(
        "-s",
        "--only-security",
        action="store_true",
        help="Only include security updates",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        help="List of updates to ignore (comma-separated list of source package names). To ignore a specific version, use format package=version.",
    )
    parser.add_argument(
        "-r", "--refresh-cache", action="store_true", help="Refresh the APT cache"
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Simulation mode, don't upgrade anything",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically answer yes to all questions",
    )
    parser.add_argument(
        "--install-recommends", action="store_true", help="Install recommended packages"
    )
    parser.add_argument(
        "--keep-configuration",
        action="store_true",
        default=False,
        help="Always keep local changes in configuration files",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="1.0.0",
        help="Display the current version",
    )

    args = parser.parse_args()

    if args.command not in ["list", "upgrade"]:
        logging.error("Invalid command. Possible commands are: list, upgrade.")
        sys.exit(1)

    try:
        if args.refresh_cache:
            refresh_cache()

        check = APTCheck()
        check.find_changes()

        blacklisted = load_blacklist(args.ignore)

        updates = filter_updates(check, blacklisted, args)

        if args.command == "list":
            handle_list_command(updates)
        elif args.command == "upgrade":
            handle_upgrade_command(updates, args)
    except Exception as e:
        logging.error("An error occurred:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

