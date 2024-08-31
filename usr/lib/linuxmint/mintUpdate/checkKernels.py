import os
import re
import sys
import datetime
import apt

from Classes import (CONFIGURED_KERNEL_TYPE, SUPPORTED_KERNEL_TYPES,
                     KernelVersion, get_release_dates)

def get_kernel_info():
    """Sistemdeki Linux çekirdek paketleri hakkında bilgi toplar."""

    release_dates = get_release_dates()
    current_version = os.uname().release
    cache = apt.Cache()
    signed_kernels = ['']
    local_kernels = {}
    kernel_regex = re.compile(r'^(?:linux-image-)(?:unsigned-)?(\d.+?)(%s)$' % "|".join(SUPPORTED_KERNEL_TYPES))

    for package_name in cache.keys():
        installed = 0
        used = 0
        installable = 0
        package_version = ""
        package_match = kernel_regex.match(package_name)

        if package_match:
            package = cache[package_name]
            package_data = None
            if package.candidate:
                package_data = package.candidate
            elif package.installed:
                package_data = package.installed
            else:
                continue

            version = package_match.group(1)
            kernel_type = package_match.group(2)
            full_version = version + kernel_type

            if package.is_installed:
                installed = 1
                package_version = package.installed.version
            else:
                if kernel_type != CONFIGURED_KERNEL_TYPE:
                    continue
                if package.candidate and package.candidate.downloadable:
                    installable = 1
                    package_version = package.candidate.version

            if full_version in signed_kernels:
                continue
            signed_kernels.append(full_version)

            if full_version == current_version:
                used = 1

            versions = KernelVersion(package_version).version_id

            origin = 0
            if package_data.origins[0].origin == 'Ubuntu':
                origin = 1
            elif package_data.origins[0].origin:
                origin = 2

            archive = package_data.origins[0].archive

            supported_tag = package_data.record.get("Supported")
            if not supported_tag and origin == 1 and "-proposed" not in package_data.origins[0].archive:
                distro = package.candidate.origins[0].archive.split("-")[0]
                if distro in release_dates:
                    try:
                        start_date, end_date = release_dates[distro]
                        distro_lifetime = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
                        if distro_lifetime >= 12:
                            supported_tag = "%sy" % (distro_lifetime // 12)
                        else:
                            supported_tag = "%sm" % distro_lifetime
                    except Exception as e:
                        print(f"Warning: Error calculating distro support duration: {e}", file=sys.stderr)
                        supported_tag = None

            if supported_tag:
                if supported_tag.endswith("y"):
                    if "-hwe" in package_data.source_name:
                        support_duration = -1
                    else:
                        support_duration = int(supported_tag[:-1]) * 12
                elif supported_tag.endswith("m"):
                    support_duration = int(supported_tag[:-1])
                else:
                    support_duration = 0
            else:
                support_duration = 0

            release_date = None
            try:
                release_date_str = package_data.record.get("ReleaseDate")
                if release_date_str:
                    release_date = datetime.datetime.strptime(release_date_str, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as e:
                print(f"Warning: ReleaseDate parsing error: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Unexpected error parsing ReleaseDate: {e}", file=sys.stderr)

            resultString = "KERNEL###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s###%s" % \
                (".".join(versions), version, package_version, installed, used, installable,
                    origin, archive, support_duration, kernel_type, release_date)
            print(resultString.encode("utf-8").decode('ascii', 'xmlcharrefreplace'))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in SUPPORTED_KERNEL_TYPES:
        CONFIGURED_KERNEL_TYPE = sys.argv[1]

    try:
        get_kernel_info()
    except Exception as e:
        print("ERROR###ERROR###ERROR###ERROR")
        print("%s: %s\n" % (e.__class__.__name__, e), file=sys.stderr)
        sys.exit(1)

