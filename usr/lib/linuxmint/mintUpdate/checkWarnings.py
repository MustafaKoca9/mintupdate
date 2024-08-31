
#!/usr/bin/python3

import sys
import apt_pkg
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def initialize_apt():
    try:
        apt_pkg.init()
        cache = apt_pkg.Cache()
        depcache = apt_pkg.DepCache(cache)
        depcache.init()
        logging.info("APT initialized successfully.")
        return cache, depcache
    except Exception as e:
        logging.error(f"Error initializing APT: {e}")
        sys.exit(1)


def process_packages(selection, depcache, cache):
    packages_to_install = set()
    packages_to_remove = set()

    try:
        with apt_pkg.ActionGroup(depcache):
            for package in selection:
                if package in cache:
                    pkg = cache[package]
                    depcache.mark_install(pkg)
                    logging.info(f"Marked for installation: {pkg.name}")
                else:
                    logging.warning(f"Package '{package}' not found in cache.")
    except Exception as e:
        logging.error(f"Error marking packages for installation: {e}")

    try:
        if not depcache.fix_broken():
            logging.warning("Could not fix broken dependencies.")
    except Exception as e:
        logging.error(f"Error fixing broken dependencies: {e}")

    try:
        for pkg in cache.packages:
            is_marked_install = depcache.marked_install(pkg) or depcache.marked_upgrade(
                pkg
            )
            is_marked_delete = depcache.marked_delete(pkg)

            if (
                not depcache.marked_keep(pkg)
                and is_marked_install
                and pkg.name not in selection
            ):
                packages_to_install.add(pkg.name)

            if is_marked_delete:
                packages_to_remove.add(pkg.name)

    except Exception as e:
        logging.error(f"Error processing packages: {e}")

    return packages_to_install, packages_to_remove


def print_results(packages_to_install, packages_to_remove):
    installations = " ".join(packages_to_install) or "None"
    removals = " ".join(packages_to_remove) or "None"
    print(f"Install: {installations} ### Remove: {removals}")


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: {} <package1> <package2> ...".format(sys.argv[0]), file=sys.stderr
        )
        sys.exit(1)

    selection = sys.argv[1:]

    try:
        cache, depcache = initialize_apt()
        packages_to_install, packages_to_remove = process_packages(
            selection, depcache, cache
        )
        print_results(packages_to_install, packages_to_remove)
    except KeyError as e:
        logging.error(f"Package not found: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


