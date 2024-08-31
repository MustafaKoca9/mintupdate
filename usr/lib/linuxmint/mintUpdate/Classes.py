#!/usr/bin/python3

import gi
from gi.repository import Gio, GLib

import datetime
import gettext
import html
import json
import os
import subprocess
import time
import re

gettext.install("mintupdate", "/usr/share/locale")

PRIORITY_UPDATES = ["mintupdate", "mint-upgrade-info"]

settings = Gio.Settings(schema_id="com.linuxmint.updates")

SUPPORTED_KERNEL_TYPES = [
    "-generic",
    "-lowlatency",
    "-aws",
    "-azure",
    "-gcp",
    "-kvm",
    "-oem",
    "-oracle",
]
KERNEL_PKG_NAMES = [
    "linux-headers-VERSION",
    "linux-headers-VERSION-KERNELTYPE",
    "linux-image-VERSION-KERNELTYPE",
    "linux-modules-VERSION-KERNELTYPE",
    "linux-modules-extra-VERSION-KERNELTYPE",
]
KERNEL_PKG_NAMES.append("linux-image-extra-VERSION-KERNELTYPE")

CONFIGURED_KERNEL_TYPE = settings.get_string("selected-kernel-type")
if CONFIGURED_KERNEL_TYPE not in SUPPORTED_KERNEL_TYPES:
    CONFIGURED_KERNEL_TYPE = "-generic"

CONFIG_PATH = os.path.expanduser("~/.linuxmint/mintupdate")


def get_release_dates():
    release_dates = {}
    distro_info = []

    if os.path.isfile("/usr/share/distro-info/ubuntu.csv"):
        with open("/usr/share/distro-info/ubuntu.csv", "r") as f:
            distro_info += f.readlines()

    if os.path.isfile("/usr/share/distro-info/debian.csv"):
        with open("/usr/share/distro-info/debian.csv", "r") as f:
            distro_info += f.readlines()

    if distro_info:
        for distro in distro_info[1:]:
            try:
                distro = distro.split(",")
                if len(distro) < 6:
                    continue

                release_date = time.mktime(time.strptime(distro[4], "%Y-%m-%d"))
                release_date = datetime.datetime.fromtimestamp(release_date)
                support_end = time.mktime(time.strptime(distro[5].rstrip(), "%Y-%m-%d"))
                support_end = datetime.datetime.fromtimestamp(support_end)

                release_dates[distro[2]] = [release_date, support_end]
            except ValueError as e:
                print(f"ValueError: {e} for distro: {distro}")
            except Exception as e:
                print(f"An error occurred: {e} for distro: {distro}")

    return release_dates


class KernelVersion:
    def __init__(self, version):
        field_length = 3
        self.version = version
        self.version_id = []
        version_id = self.version.replace("-", ".").split(".")

        suffix = next((x for x in version_id if x.startswith("rc")), None)
        if not suffix:
            suffix = "z"

        for element in version_id:
            if element.isnumeric():
                self.version_id.append("0" * (field_length - len(element)) + element)

        while len(self.version_id) < 4:
            self.version_id.append("0" * field_length)

        if len(self.version_id) == 4:
            self.version_id.append(
                "%s%s"
                % (
                    "".join(
                        (
                            x[: field_length - 2].lstrip("0") + x[field_length - 2 :]
                            for x in self.version_id
                        )
                    ),
                    suffix,
                )
            )
        elif len(self.version_id) > 4 and len(self.version_id[4]) == 6:
            self.version_id[4] += suffix

        self.series = tuple(self.version_id[:3])
        self.shortseries = tuple(self.version_id[:2])


class Update:
    def __init__(self, package=None, input_string=None, source_name=None):
        self.package_names = []
        if package is not None:
            self.package_names.append(package.name)
            self.source_packages = {
                "%s=%s"
                % (package.candidate.source_name, package.candidate.source_version)
            }
            self.main_package_name = package.name
            self.package_name = package.name
            self.new_version = package.candidate.version
            if package.installed is None:
                self.old_version = ""
            else:
                self.old_version = package.installed.version
            self.size = package.candidate.size
            self.real_source_name = package.candidate.source_name
            if source_name is not None:
                self.source_name = source_name
            else:
                self.source_name = self.real_source_name
            self.display_name = self.source_name
            self.short_description = package.candidate.raw_description
            self.description = package.candidate.description
            self.archive = ""
            if self.new_version != self.old_version:
                self.type = "package"
                self.origin = ""
                for origin in package.candidate.origins:
                    self.origin = origin.origin
                    self.site = origin.site
                    self.archive = origin.archive
                    if origin.origin == "Ubuntu":
                        self.origin = "ubuntu"
                    elif origin.origin == "Debian":
                        self.origin = "debian"
                    elif origin.origin.startswith("LP-PPA"):
                        self.origin = origin.origin
                    if origin.origin == "Ubuntu" and "-security" in origin.archive:
                        self.type = "security"
                        break
                    if origin.origin == "Debian" and "-Security" in origin.label:
                        self.type = "security"
                        break
                    if source_name in ["firefox", "thunderbird", "chromium"]:
                        self.type = "security"
                        break
                    if origin.origin == "linuxmint":
                        if origin.component == "romeo":
                            self.type = "unstable"
                            break
                if (
                    package.candidate.section == "kernel"
                    or self.package_name.startswith("linux-headers")
                    or self.real_source_name
                    in ["linux", "linux-kernel", "linux-signed", "linux-meta"]
                ):
                    self.type = "kernel"
        else:
            self.parse(input_string)

    def add_package(self, pkg):
        self.package_names.append(pkg.name)
        self.source_packages.add(
            "%s=%s" % (pkg.candidate.source_name, pkg.candidate.source_version)
        )
        self.size += pkg.candidate.size
        if self.main_package_name is None or pkg.name == self.source_name:
            self.overwrite_main_package(pkg)
            return

        if self.main_package_name != self.source_name:
            for suffix in [
                "-dev",
                "-dbg",
                "-common",
                "-core",
                "-data",
                "-doc",
                ":i386",
                ":amd64",
            ]:
                if self.main_package_name.endswith(suffix) and not pkg.name.endswith(
                    suffix
                ):
                    self.overwrite_main_package(pkg)
                    return
            # Overwrite lib packages
            for prefix in ["lib", "gir1.2"]:
                if self.main_package_name.startswith(
                    prefix
                ) and not pkg.name.startswith(prefix):
                    self.overwrite_main_package(pkg)
                    return
            for keyword in ["-locale-", "-l10n-", "-help-"]:
                if (keyword in self.main_package_name) and (keyword not in pkg.name):
                    self.overwrite_main_package(pkg)
                    return

    def overwrite_main_package(self, pkg):
        self.description = pkg.candidate.description
        self.short_description = pkg.candidate.raw_description
        self.main_package_name = pkg.name

    def serialize(self):
        output_string = (
            "###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s---EOL---"
            % (
                self.display_name,
                self.source_name,
                self.real_source_name,
                ", ".join(self.source_packages),
                self.main_package_name,
                ", ".join(self.package_names),
                self.new_version,
                self.old_version,
                self.size,
                self.type,
                self.origin,
                self.short_description,
                self.description,
                self.site,
                self.archive,
            )
        )
        print(output_string.encode("ascii", "xmlcharrefreplace"))

    def parse(self, input_string):
        try:
            input_string = html.unescape(input_string)
        except:
            pass
        values = input_string.split("###")[1:]
        (
            self.display_name,
            self.source_name,
            self.real_source_name,
            source_packages,
            self.main_package_name,
            package_names,
            self.new_version,
            self.old_version,
            size,
            self.type,
            self.origin,
            self.short_description,
            self.description,
            self.site,
            self.archive,
        ) = values
        self.size = int(size)
        self.package_names = package_names.split(", ")
        self.source_packages = source_packages.split(", ")


class Alias:
    def __init__(
        self, name=None, short_description=None, description=None, translator=None
    ):

        self.translator = translator or (lambda x: x)
        self.name = self._process_text(name)
        self.short_description = self._process_text(short_description)
        self.description = self._process_text(description)

    def _process_text(self, text):

        if text:
            text = text.strip()
            if text.startswith('_("') and text.endswith('")'):
                return self.translator(text[3:-2])
        return text

    def __repr__(self):

        return f"Alias(name={self.name!r}, short_description={self.short_description!r}, description={self.description!r})"


class UpdateTracker:
    def __init__(self, settings, logger):

        os.makedirs(CONFIG_PATH, exist_ok=True)
        self.path = os.path.join(CONFIG_PATH, "updates.json")

        self.test_mode = False
        test_path = f"/usr/share/linuxmint/mintupdate/tests/{os.getenv('MINTUPDATE_TEST', '')}.json"
        if os.path.exists(test_path):
            os.makedirs(CONFIG_PATH, exist_ok=True)
            os.system(f"cp {test_path} {self.path}")
            self.test_mode = True

        self.tracker_version = 1
        self.settings = settings
        self.tracked_updates = {}
        self.refreshed_update_names = []
        self.today = datetime.date.today().strftime("%Y.%m.%d")
        self.max_days = 0
        self.oldest_since_date = self.today
        self.active = True
        self.security_only = self.settings.get_boolean("tracker-security-only")
        self.logger = logger

        self._initialize_tracker()

    def _initialize_tracker(self):

        try:
            with open(self.path) as f:
                self.tracked_updates = json.load(f)
                self._validate_tracker_data()
        except Exception as e:
            self.logger.write(f"Tracker exception: {e}")
            self.tracked_updates = {
                "updates": {},
                "version": self.tracker_version,
                "checked": self.today,
                "notified": self.today,
            }

    def _validate_tracker_data(self):

        if (
            self.tracked_updates["version"] < self.tracker_version
            or self.tracked_updates["checked"] > self.today
            or self.tracked_updates["notified"] > self.today
        ):
            raise Exception("Invalid tracker data")

        if self.tracked_updates["checked"] == self.today:
            self.active = False

    def update(self, update):

        self.refreshed_update_names.append(update.real_source_name)
        if update.real_source_name not in self.tracked_updates["updates"]:
            update_record = {"type": update.type, "since": self.today, "days": 1}
            self.tracked_updates["updates"][update.real_source_name] = update_record
        else:
            update_record = self.tracked_updates["updates"][update.real_source_name]
            update_record["type"] = update.type
            if self.today > self.tracked_updates["checked"]:
                update_record["days"] += 1

        if update.type in ["security", "kernel"] or not self.security_only:
            self.max_days = max(self.max_days, update_record["days"])
            self.oldest_since_date = min(self.oldest_since_date, update_record["since"])

    def get_days_since_date(self, date_str: str, date_format: str) -> int:

        if date_str:
            datetime_object = datetime.datetime.strptime(date_str, date_format)
            return (datetime.date.today() - datetime_object.date()).days
        return 999

    def get_days_since_timestamp(self, timestamp: float) -> int:

        if timestamp:
            datetime_object = datetime.datetime.fromtimestamp(timestamp)
            return (datetime.date.today() - datetime_object.date()).days
        return 999

    def get_latest_apt_upgrade(self):

        latest_upgrade_date = self._get_latest_upgrade_from_log(
            "/var/log/apt/history.log"
        )
        if not latest_upgrade_date:
            try:
                latest_upgrade_date = self._get_latest_upgrade_from_log(
                    "zcat /var/log/apt/history.log*gz"
                )
            except Exception as e:
                print("Failed to check compressed APT logs", e)
        return latest_upgrade_date

    def _get_latest_upgrade_from_log(self, log_path):

        latest_upgrade_date = None
        logs = subprocess.getoutput(log_path)
        for event in logs.split("\n\n"):
            if "Upgrade: " not in event:
                continue
            end_date = None
            for line in event.split("\n"):
                line = line.strip()
                if line.startswith("End-Date: "):
                    end_date = line.replace("End-Date: ", "").split()[0]
            if end_date and (
                latest_upgrade_date is None or end_date > latest_upgrade_date
            ):
                latest_upgrade_date = end_date
        return latest_upgrade_date

    def notify(self) -> bool:

        if self.settings.get_boolean("tracker-disable-notifications"):
            return False

        notified_age = self.get_days_since_date(
            self.tracked_updates["notified"], "%Y.%m.%d"
        )
        if notified_age < self.settings.get_int("tracker-days-between-notifications"):
            self.logger.write(
                f"Tracker: Notification age is too small: {notified_age} days"
            )
            return False

        notification_needed = False

        if self.max_days >= self.settings.get_int("tracker-max-days"):
            self.logger.write(f"Tracker: Max days reached: {self.max_days} days")
            notification_needed = True
        else:
            max_age = self.get_days_since_date(self.oldest_since_date, "%Y.%m.%d")
            if max_age >= self.settings.get_int("tracker-max-age"):
                self.logger.write(f"Tracker: Max age reached: {max_age} days")
                notification_needed = True

        if not self.test_mode:
            last_install_age = self.get_days_since_timestamp(
                self.settings.get_int("install-last-run")
            )
            if last_install_age <= self.settings.get_int("tracker-grace-period"):
                self.logger.write(
                    f"Tracker: Mintupdate update button was pressed recently: {last_install_age} days ago"
                )
                notification_needed = False
            else:
                last_apt_upgrade = self.get_latest_apt_upgrade()
                if last_apt_upgrade:
                    last_apt_upgrade_age = self.get_days_since_date(
                        last_apt_upgrade, "%Y-%m-%d"
                    )
                    if last_apt_upgrade_age <= self.settings.get_int(
                        "tracker-grace-period"
                    ):
                        self.logger.write(
                            f"Tracker: APT upgrades were taken recently: {last_apt_upgrade_age} days ago"
                        )
                        notification_needed = False

        if notification_needed:
            self.tracked_updates["notified"] = self.today
            return True
        return False

    def record(self):

        self.tracked_updates["updates"] = {
            name: record
            for name, record in self.tracked_updates["updates"].items()
            if name in self.refreshed_update_names
        }
        self.tracked_updates["checked"] = self.today
        with open(self.path, "w") as f:
            json.dump(self.tracked_updates, f, indent=2)


try:
    gi.require_version("Flatpak", "1.0")
    from gi.repository import Flatpak
except Exception as e:
    print(f"Flatpak module not found: {e}")


class FlatpakUpdate:
    def __init__(
        self,
        op=None,
        installer=None,
        ref=None,
        installed_ref=None,
        remote_ref=None,
        pkginfo=None,
    ):

        if op is None:
            # JSON parsing scenario
            return

        self.op = op
        self.installed_ref = installed_ref
        self.remote_ref = remote_ref
        self.pkginfo = pkginfo

        self.ref = ref
        self.ref_name = ref.get_name() if ref else ""
        self.metadata = op.get_metadata() if op else None
        self.size = op.get_download_size() if op else 0
        self.link = installer.get_homepage_url(pkginfo) if pkginfo else None
        self.flatpak_type = (
            "app" if ref and ref.get_kind() == Flatpak.RefKind.APP else "runtime"
        )
        self.old_version = ""
        self.new_version = ""
        self.name = ""
        self.summary = ""
        self.description = ""
        self.real_source_name = ""
        self.source_packages = []
        self.package_names = [self.ref_name]
        self.sub_updates: List["FlatpakUpdate"] = []
        self.origin = ""

        self._set_versions(installed_ref, pkginfo, installer)
        self._set_package_info(installer, pkginfo, installed_ref, ref)

    def _set_versions(self, installed_ref, pkginfo, installer):
        try:
            old_commit = installed_ref.get_commit()[:10] if installed_ref else ""
            iref_version = installed_ref.get_appdata_version() if installed_ref else ""
            appstream_version = installer.get_version(pkginfo) if pkginfo else ""
            new_commit = self.op.get_commit()[:10] if self.op else ""

            if iref_version and appstream_version:
                if iref_version != appstream_version:
                    self.old_version = iref_version
                    self.new_version = appstream_version
                else:
                    self.old_version = f"{iref_version} ({old_commit})"
                    self.new_version = f"{appstream_version} ({new_commit})"
            else:
                self.old_version = old_commit
                self.new_version = new_commit
        except Exception as e:
            logging.error(f"Error setting versions: {e}")

    def _set_package_info(self, installer, pkginfo, installed_ref, ref):

        try:
            if pkginfo:
                self.name = installer.get_display_name(pkginfo)
                self.summary = installer.get_summary(pkginfo)
                self.description = installer.get_description(pkginfo)
            elif installed_ref and self.flatpak_type != "runtime":
                self.name = installed_ref.get_appdata_name()
                self.summary = installed_ref.get_appdata_summary()
                self.description = ""
            else:
                self.name = ref.get_name() if ref else ""
                self.summary = ""
                self.description = ""

            if not self.description and self.flatpak_type == "runtime":
                self.summary = self.description = "A Flatpak runtime package"

            self.real_source_name = self.ref_name
            self.source_packages = [f"{self.ref_name}={self.new_version}"]
            self.package_names = [self.ref_name]
            self.sub_updates = []

            self.origin = (
                installed_ref.get_origin().capitalize()
                if installed_ref
                else remote_ref.get_remote_name()
                if remote_ref
                else ""
            )
        except Exception as e:
            logging.error(f"Error setting package info: {e}")

    def add_package(self, update):

        if hasattr(update, "ref_name") and hasattr(update, "size"):
            self.sub_updates.append(update)
            self.package_names.append(update.ref_name)
            self.size += update.size

    def to_json(self) -> dict:

        trimmed_dict = {
            "flatpak_type": self.flatpak_type,
            "name": self.name,
            "origin": self.origin,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "size": self.size,
            "summary": self.summary,
            "description": self.description,
            "real_source_name": self.real_source_name,
            "source_packages": self.source_packages,
            "package_names": self.package_names,
            "sub_updates": [
                update.to_json()
                for update in self.sub_updates
                if hasattr(update, "to_json")
            ],
            "link": self.link,
            "metadata": self.metadata.to_data()[0] if self.metadata else None,
            "ref": self.ref.format_ref() if self.ref else "",
        }
        return trimmed_dict

    @classmethod
    def from_json(cls, json_data: dict):
        inst = cls()
        inst.flatpak_type = json_data["flatpak_type"]
        inst.ref = Flatpak.Ref.parse(json_data["ref"])
        inst.ref_name = inst.ref.get_name()
        inst.name = json_data["name"]
        inst.origin = json_data["origin"]
        inst.old_version = json_data["old_version"]
        inst.new_version = json_data["new_version"]
        inst.size = json_data["size"]
        inst.summary = json_data["summary"]
        inst.description = json_data["description"]
        inst.real_source_name = json_data["real_source_name"]
        inst.source_packages = json_data["source_packages"]
        inst.package_names = json_data["package_names"]
        inst.sub_updates = json_data["sub_updates"]
        inst.link = json_data["link"]
        inst.metadata = GLib.KeyFile()

        try:
            b = GLib.Bytes.new(json_data["metadata"].encode())
            inst.metadata.load_from_bytes(b, GLib.KeyFileFlags.NONE)
        except GLib.Error as e:
            print("unable to decode op metadata: %s" % e.message)
            pass

        return inst
