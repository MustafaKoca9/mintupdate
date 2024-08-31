#!/usr/bin/python3

import os
import sys
import shutil
import logging

# Configure logging
logging.basicConfig(
    filename="/var/log/synaptic_config_manager.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Constants for configuration file paths
SYNAPTIC_CONF = "/root/.synaptic/synaptic.conf"
WORKAROUND_CONF = "/root/.synaptic/synaptic-mintupdate-workaround.conf"
SYNAPTIC_DIR = "/root/.synaptic"
BACKUP_SUFFIX = ".bak"


def usage():
    print(
        f"Usage: {os.path.basename(sys.argv[0])} [enable|disable] [--test]",
        file=sys.stderr,
    )
    print("Note: This script must be run with root privileges.", file=sys.stderr)


def check_root():
    if os.geteuid() != 0:
        print("This script must be run with root privileges.", file=sys.stderr)
        sys.exit(1)


def ensure_directory_exists(directory):
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            logging.info(f"Created directory: '{directory}'")
        except Exception as e:
            logging.error(f"Failed to create directory '{directory}': {e}")
            sys.exit(1)


def backup_file(file_path):
    if os.path.isfile(file_path):
        backup_path = f"{file_path}{BACKUP_SUFFIX}"
        try:
            shutil.copy2(file_path, backup_path)
            logging.info(f"Backup created: '{backup_path}'")
            return backup_path
        except Exception as e:
            logging.error(f"Failed to create backup for '{file_path}': {e}")
            sys.exit(1)
    return None


def move_file(src, dst):
    try:
        shutil.move(src, dst)
        logging.info(f"Moved '{src}' to '{dst}'")
    except FileNotFoundError:
        logging.error(f"Source file '{src}' does not exist.")
    except PermissionError:
        logging.error(f"Permission denied while moving '{src}' to '{dst}'.")
    except Exception as e:
        logging.error(f"Error moving file '{src}' to '{dst}': {e}")


def prompt_user(message):
    while True:
        response = input(f"{message} [y/n]: ").strip().lower()
        if response in ["y", "n"]:
            return response == "y"
        print("Invalid response. Please enter 'y' or 'n'.")


def rename_conf_files(action, test_mode=False):
    ensure_directory_exists(SYNAPTIC_DIR)

    synaptic_exists = os.path.isfile(SYNAPTIC_CONF)
    workaround_exists = os.path.isfile(WORKAROUND_CONF)

    if action == "enable":
        if synaptic_exists:
            logging.info(f"'{SYNAPTIC_CONF}' already exists. No action needed.")
            return False
        if workaround_exists:
            if not test_mode and prompt_user(
                f"Are you sure you want to enable and move '{WORKAROUND_CONF}' to '{SYNAPTIC_CONF}'?"
            ):
                move_file(WORKAROUND_CONF, SYNAPTIC_CONF)
                logging.info(f"Enabled: '{SYNAPTIC_CONF}' has been restored.")
                return True
            elif test_mode:
                logging.info(
                    f"Test mode: Would move '{WORKAROUND_CONF}' to '{SYNAPTIC_CONF}'."
                )
            return False
        logging.info("Neither configuration file found. No action taken.")
        return False

    elif action == "disable":
        if not synaptic_exists:
            logging.info(f"'{SYNAPTIC_CONF}' does not exist. No action needed.")
            return False
        if workaround_exists:
            logging.info(f"'{WORKAROUND_CONF}' already exists. Cannot disable.")
            return False
        if not test_mode and prompt_user(
            f"Are you sure you want to disable and move '{SYNAPTIC_CONF}' to '{WORKAROUND_CONF}'?"
        ):
            backup_file(SYNAPTIC_CONF)  # Backup before moving
            move_file(SYNAPTIC_CONF, WORKAROUND_CONF)
            logging.info(f"Disabled: '{WORKAROUND_CONF}' has been created.")
            return True
        elif test_mode:
            logging.info(
                f"Test mode: Would move '{SYNAPTIC_CONF}' to '{WORKAROUND_CONF}'."
            )
        return False


def main():
    check_root()  # Check for root privileges

    if len(sys.argv) < 2 or sys.argv[1] not in ("enable", "disable"):
        usage()
        sys.exit(1)

    action = sys.argv[1]
    test_mode = "--test" in sys.argv

    success = rename_conf_files(action, test_mode)
    if not success and not test_mode:
        sys.exit(1)


if __name__ == "__main__":
    main()

