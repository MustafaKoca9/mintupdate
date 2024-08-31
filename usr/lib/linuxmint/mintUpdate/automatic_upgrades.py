#!/usr/bin/python3

import os
import subprocess
import logging
import sys

# Configure logging
logging.basicConfig(
    filename="/var/log/mintupdate.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Constants for file paths
OPTIONS_FILE = "/etc/mintupdate-automatic-upgrades.conf"
POWER_CONNECT_FILE = "/sys/class/power_supply/AC/online"
PKLA_SOURCE = "/usr/share/linuxmint/mintupdate/automation/99-mintupdate-temporary.pkla"
PKLA_TARGET = "/etc/polkit-1/localauthority/90-mandatory.d/99-mintupdate-temporary.pkla"

# Return codes
SUCCESS = 0
FAILURE = 1


def is_power_connected():
    """Check if the power supply is connected."""
    try:
        with open(POWER_CONNECT_FILE) as power_supply_file:
            return power_supply_file.read().strip() == "1"
    except FileNotFoundError:
        logging.warning(f"{POWER_CONNECT_FILE} not found. Ignoring power supply check.")
        return True
    except IOError as e:
        logging.error(f"IOError reading {POWER_CONNECT_FILE}: {e}")
        return False


def get_upgrade_arguments():
    """Parse the options file and return a list of arguments."""
    arguments = []
    if os.path.isfile(OPTIONS_FILE):
        try:
            with open(OPTIONS_FILE) as options:
                for line in options:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        arguments.append(line)
        except Exception as e:
            logging.error(f"Error reading {OPTIONS_FILE}: {e}")
    else:
        logging.warning(f"{OPTIONS_FILE} does not exist.")
    return arguments


def create_symlink():
    """Create a symlink for the shutdown and reboot blocker."""
    try:
        if os.path.islink(PKLA_TARGET):
            logging.info(
                f"{PKLA_TARGET} already exists as a symlink. Skipping symlink creation."
            )
        elif os.path.exists(PKLA_TARGET):
            logging.error(
                f"{PKLA_TARGET} exists but is not a symlink. Cannot create symlink."
            )
            return FAILURE
        else:
            os.symlink(PKLA_SOURCE, PKLA_TARGET)
            logging.info(f"Created symlink from {PKLA_SOURCE} to {PKLA_TARGET}.")
    except OSError as e:
        logging.error(f"Error creating symlink {PKLA_SOURCE} -> {PKLA_TARGET}: {e}")
        return FAILURE
    return SUCCESS


def remove_symlink():
    """Remove the symlink for the shutdown and reboot blocker."""
    try:
        if os.path.islink(PKLA_TARGET):
            os.unlink(PKLA_TARGET)
            logging.info(f"Removed symlink {PKLA_TARGET}.")
        else:
            logging.info(
                f"{PKLA_TARGET} does not exist or is not a symlink. Skipping removal."
            )
    except Exception as e:
        logging.error(f"Error removing symlink: {e}")


def run_upgrade_command(arguments):
    """Run the upgrade command using mintupdate-cli through systemd-inhibit."""
    cmd = [
        "/bin/systemd-inhibit",
        "--why=Performing automatic updates",
        "--who=Update Manager",
        "--what=shutdown",
        "--mode=block",
        "/usr/bin/mintupdate-cli",
        "upgrade",
        "--refresh-cache",
        "--yes",
    ]
    cmd.extend(arguments)

    logging.info(f"Running command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
        logging.info(f"mintupdate-cli output: {result.stdout.decode()}")
    except subprocess.CalledProcessError as e:
        logging.error(
            f"mintupdate-cli failed with return code {e.returncode}. Error: {e.stderr.decode()}"
        )
        return e.returncode
    return SUCCESS


def main():
    """Main function for automatic upgrades."""
    if not os.path.exists("/var/lib/linuxmint/mintupdate-automatic-upgrades-enabled"):
        logging.info("Automatic upgrades are not enabled.")
        return FAILURE

    logging.info("Automatic Upgrade starting.")

    if is_power_connected():
        if create_symlink() == FAILURE:
            return FAILURE

        arguments = get_upgrade_arguments()
        result_code = run_upgrade_command(arguments)

        remove_symlink()
        logging.info("Automatic Upgrade completed.")

        return result_code
    else:
        logging.warning("Power supply not connected, aborting automatic update.")
        return FAILURE


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

