#!/usr/bin/python3

import configparser
import gettext
import os
import tempfile
from subprocess import PIPE, Popen
import sys
import time
import threading
import shutil
import signal

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import apt

gettext.install("mintupdate", "/usr/share/locale")


class Assistant:

    def __init__(self):

        self.assistant = Gtk.Assistant()
        self.assistant.set_position(Gtk.WindowPosition.CENTER)
        self.assistant.set_title(_("System Upgrade"))
        self.assistant.connect("apply", self.apply_button_pressed)
        self.assistant.connect("cancel", self.cancel_button_pressed)
        self.assistant.connect("close", self.close_button_pressed)
        self.assistant.set_resizable(True)
        self.assistant.set_default_size(640, 480)

        # Intro page
        self.vbox_intro = Gtk.VBox()
        self.vbox_intro.set_border_width(60)
        page = self.assistant.append_page(self.vbox_intro)
        self.assistant.set_page_type(self.vbox_intro, Gtk.AssistantPageType.INTRO)
        self.assistant.set_page_title(self.vbox_intro, _("Introduction"))
        self.assistant.set_icon_name("mintupdate-release-upgrade")

        if not os.path.exists("/etc/linuxmint/info"):
            self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("Your system is missing critical components. A package corresponding to your edition of Linux Mint should provide the virtual package 'mint-info' and the file /etc/linuxmint/info."))
        else:
            self.current_codename = 'unknown'
            self.current_edition = 'unknown'
            with open("/etc/linuxmint/info", "r") as info:
                for line in info:
                    line = line.strip()
                    if "EDITION=" in line:
                        self.current_edition = line.split('=')[1].replace('"', '').split()[0]
                    if "CODENAME=" in line:
                        self.current_codename = line.split('=')[1].replace('"', '').split()[0]
            rel_path = "/usr/share/mint-upgrade-info/%s" % self.current_codename
            if not os.path.exists(rel_path):
                self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/info.png', _("No upgrades were found."))
            else:
                config = configparser.ConfigParser()
                config.read(os.path.join(rel_path, "info"))
                self.rel_target_name = config['general']['target_name']
                self.rel_target_codename = config['general']['target_codename']
                self.rel_editions = config['general']['editions']
                if self.current_edition.lower() in self.rel_editions:
                    label = Gtk.Label()
                    label.set_markup(_("A new version of Linux Mint is available!"))
                    self.vbox_intro.pack_start(label, False, False, 6)
                    image = Gtk.Image.new_from_file(os.path.join(rel_path, "%s.png" % self.current_edition.lower()))
                    self.vbox_intro.pack_start(image, False, False, 0)
                    label = Gtk.Label()
                    label.set_markup("<b>%s</b>" % self.rel_target_name)
                    self.vbox_intro.pack_start(label, False, False, 0)
                    self.assistant.set_page_complete(self.vbox_intro, True)
                    self.build_assistant()
                else:
                    self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/info.png', _("An upgrade was found but it is not available yet for the %s edition.") % self.current_edition)

        self.assistant.show_all()

    def build_assistant(self):
        # Known issues
        self.vbox_rel_notes = Gtk.VBox()
        self.vbox_rel_notes.set_border_width(60)
        self.assistant.append_page(self.vbox_rel_notes)
        self.assistant.set_page_title(self.vbox_rel_notes, _("Release notes"))
        self.assistant.set_page_type(self.vbox_rel_notes, Gtk.AssistantPageType.CONTENT)
        vbox_content = Gtk.HBox()
        image = Gtk.Image.new_from_file('/usr/lib/linuxmint/mintUpdate/rel_upgrades/info.png')
        vbox_content.pack_start(image, False, False, 0)
        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_markup(_("Please read the release notes before upgrading. They explain all the known issues, workarounds and solutions associated with the new version."))
        vbox_content.pack_start(label, False, False, 6)
        self.vbox_rel_notes.pack_start(vbox_content, False, False, 6)
        link = Gtk.Label()
        link.set_markup("<a href='https://www.linuxmint.com/rel_%s.php'><b>%s</b></a>" % (self.rel_target_codename, _("Release notes for %s") % self.rel_target_name))
        self.vbox_rel_notes.pack_start(link, False, False, 6)
        label = Gtk.Label()
        label.set_markup("<i><b>%s</b></i>" % _("Click on the link to open the release notes."))
        self.vbox_rel_notes.pack_start(label, False, False, 6)
        self.assistant.set_page_complete(self.vbox_rel_notes, True)

        # New features
        self.vbox_new_features = Gtk.VBox()
        self.vbox_new_features.set_border_width(60)
        self.assistant.append_page(self.vbox_new_features)
        self.assistant.set_page_title(self.vbox_new_features, _("New features"))
        self.assistant.set_page_type(self.vbox_new_features, Gtk.AssistantPageType.CONTENT)
        vbox_content = Gtk.HBox()
        image = Gtk.Image.new_from_file('/usr/lib/linuxmint/mintUpdate/rel_upgrades/features.png')
        vbox_content.pack_start(image, False, False, 0)
        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_markup(_("Please look at the new features introduced in the new version."))
        vbox_content.pack_start(label, False, False, 6)
        self.vbox_new_features.pack_start(vbox_content, False, False, 6)
        link = Gtk.Label()
        link.set_markup("<a href='https://www.linuxmint.com/rel_%s_whatsnew.php'><b>%s</b></a>" % (self.rel_target_codename, _("New features in %s") % self.rel_target_name))
        self.vbox_new_features.pack_start(link, False, False, 6)
        label = Gtk.Label()
        label.set_markup("<i><b>%s</b></i>" % _("Click on the link to browse the new features."))
        self.vbox_new_features.pack_start(label, False, False, 6)
        self.assistant.set_page_complete(self.vbox_new_features, True)

        # Warnings and risks
        self.vbox_prerequesites = Gtk.VBox()
        self.vbox_prerequesites.set_border_width(60)
        self.assistant.append_page(self.vbox_prerequesites)
        self.assistant.set_page_title(self.vbox_prerequesites, _("Requirements"))
        self.assistant.set_page_type(self.vbox_prerequesites, Gtk.AssistantPageType.CONFIRM)

        self.vbox_meta = Gtk.VBox()
        meta = "mint-meta-%s" % self.current_edition.lower()
        vbox_content = Gtk.HBox()
        image = Gtk.Image.new_from_file('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png')
        vbox_content.pack_start(image, False, False, 0)
        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_markup(_("The package %s needs to be installed before upgrading.") % meta)
        vbox_content.pack_start(label, False, False, 6)
        self.vbox_meta.pack_start(vbox_content, False, False, 6)
        button = Gtk.Button()
        button.set_label(_("Install %s") % meta)
        packages = [meta]
        button.connect("button-release-event", self.install_pkgs, packages)
        self.vbox_meta.pack_start(button, False, False, 6)
        label = Gtk.Label()
        label.set_markup("<i><b>%s</b></i>" % _("Click on the button to install the missing package."))
        self.vbox_meta.pack_start(label, False, False, 6)
        self.vbox_meta.pack_start(Gtk.Separator(), False, False, 6)
        self.vbox_prerequesites.pack_start(self.vbox_meta, False, False, 10)

        if self.check_meta():
            self.vbox_meta.set_no_show_all(True)
            self.vbox_meta.hide()

        vbox_content = Gtk.HBox()
        image = Gtk.Image.new_from_file('/usr/lib/linuxmint/mintUpdate/rel_upgrades/risks.png')
        vbox_content.pack_start(image, False, False, 0)
        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_markup(_("New releases provide bug fixes and new features but they also sometimes introduce new issues. Upgrading always represents a risk. Your data is safe but new issues can potentially affect your operating system."))
        vbox_content.pack_start(label, False, False, 6)
        self.vbox_prerequesites.pack_start(vbox_content, False, False, 6)
        self.check_button = Gtk.CheckButton()
        self.check_button.set_label(_("I understand the risk. I want to upgrade to %s.") % self.rel_target_name)
        self.check_button.connect("toggled", self.understood)
        self.vbox_prerequesites.pack_start(self.check_button, False, False, 6)

        self.assistant.set_page_complete(self.vbox_prerequesites, False)

        # Summary
        self.vbox_summary = Gtk.VBox()
        self.vbox_summary.set_border_width(60)
        self.assistant.append_page(self.vbox_summary)
        self.assistant.set_page_title(self.vbox_summary, _("Summary"))
        self.assistant.set_page_type(self.vbox_summary, Gtk.AssistantPageType.SUMMARY)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_text(_("0%"))
        self.progress_bar.set_fraction(0.0)
        self.vbox_summary.pack_start(self.progress_bar, False, False, 6)

        # Add a label to display the current status
        self.status_label = Gtk.Label()
        self.status_label.set_markup(_("Preparing to upgrade..."))
        self.vbox_summary.pack_start(self.status_label, False, False, 6)

        # Add a button to cancel the upgrade
        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_button.connect("clicked", self.cancel_upgrade)
        self.vbox_summary.pack_start(self.cancel_button, False, False, 6)


    def install_pkgs(self, widget, event, packages):
        """
        Installs the given packages using synaptic.
        """
        cmd = [
            "pkexec", "/usr/sbin/synaptic",
            "--hide-main-window",
            "--non-interactive",
            "-o", "Synaptic::closeZvt=true"
        ]

        if os.environ.get("XDG_SESSION_TYPE", "x11") == "x11":
            cmd += ["--parent-window-id", "%s" % self.assistant.get_window().get_xid()]

        f = tempfile.NamedTemporaryFile()
        for pkg in packages:
            pkg_line = "%s\tinstall\n" % pkg
            f.write(pkg_line.encode("utf-8"))
        cmd.append("--set-selections-file")
        cmd.append("%s" % f.name)
        f.flush()
        try:
            comnd = Popen(' '.join(cmd), shell=True)
            returnCode = comnd.wait()
        except Exception as e:
            print(f"Error running synaptic: {e}")
            self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("An error occurred while installing the missing package. Please try again later."))
            return
        finally:
            f.close()
        self.check_reqs()

    def check_meta(self):
        """
        Checks if the `mint-meta-edition` package is installed.
        """
        meta = "mint-meta-%s" % self.current_edition.lower()
        cache = apt.Cache()
        if meta in cache:
            if cache[meta].is_installed:
                return True
        return False

    def understood(self, button):
        """
        Updates the assistant page completion status based on the user's choice.
        """
        self.check_reqs()

    def check_reqs(self):
        """
        Checks if the required packages are installed and updates the assistant page completion status.
        """
        if self.check_meta():
            self.vbox_meta.hide()
            if self.check_button.get_active():
                self.assistant.set_page_complete(self.vbox_prerequesites, True)
            else:
                self.assistant.set_page_complete(self.vbox_prerequesites, False)

    def show_message(self, icon, msg):
        """
        Displays a message box with an icon and a message.
        """
        dialog = Gtk.MessageDialog(
            parent=self.assistant.get_window(),
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=msg
        )
        dialog.set_icon_from_file(icon)
        dialog.run()
        dialog.destroy()

    def cancel_button_pressed(self, assistant):
        """
        Handles the cancel button press event.
        """
        Gtk.main_quit()

    def close_button_pressed(self, assistant):
        """
        Handles the close button press event.
        """
        Gtk.main_quit()

    def apply_button_pressed(self, assistant):
        """
        Handles the apply button press event.
        """

        # Turn off the screensaver during the upgrade
        screensaver_setting = None
        screensaver_enabled = "true"
        if self.current_edition.lower() == "cinnamon":
            screensaver_setting = "org.cinnamon.desktop.screensaver lock-enabled"
        elif self.current_edition.lower() == "mate":
            screensaver_setting = "org.mate.screensaver lock-enabled"
        if screensaver_setting is not None:
            try:
                enabled = os.popen("gsettings get %s" % screensaver_setting).readlines()[0].strip()
                if enabled == "false":
                    screensaver_enabled = "false"
                else:
                    os.system("gsettings set %s false" % screensaver_setting)
            except Exception as e:
                print(f"Error managing screensaver: {e}")
                self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("An error occurred while managing the screensaver. Please try again later."))
                return

        # Start the upgrade process in a separate thread
        upgrade_thread = threading.Thread(target=self.upgrade_process)
        upgrade_thread.start()

        # Show the summary page and progress bar
        self.assistant.set_page(self.vbox_summary)
        self.vbox_summary.show_all()

    def upgrade_process(self):
        """
        Performs the system upgrade in a separate thread.
        """
        cmd = [
            "pkexec", "/usr/bin/mint-release-upgrade-root",
            "%s" % self.current_codename
        ]

        if os.environ.get("XDG_SESSION_TYPE", "x11") == "x11":
            cmd += ["%s" % self.assistant.get_window().get_xid()]

        try:
            # Start the upgrade process
            comnd = Popen(' '.join(cmd), shell=True)
            returnCode = comnd.wait()

            # Update the progress bar and status label
            self.update_progress_bar(100)
            self.update_status_label(_("Upgrade complete. Please reboot."))

            # Reset the screensaver the way it was before the upgrade
            if screensaver_setting is not None:
                try:
                    os.system("gsettings set %s %s" % (screensaver_setting, screensaver_enabled))
                except Exception as e:
                    print(f"Error restoring screensaver: {e}")
                    self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("An error occurred while restoring the screensaver. Please try again later."))
                    return

            # Check the upgrade status
            new_codename = 'unknown'
            if os.path.exists("/etc/linuxmint/info"):
                try:
                    with open("/etc/linuxmint/info", "r") as info:
                        for line in info:
                            line = line.strip()
                            if "CODENAME=" in line:
                                new_codename = line.split('=')[1].replace('"', '').split()[0]
                                break
                except Exception as e:
                    print(f"Error reading info file: {e}")
                    self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("An error occurred while reading the system information. Please try again later."))
                    return

            if new_codename == self.rel_target_codename:
                image_result = "success"
                message_text = _("Your operating system was successfully upgraded. Please reboot your computer for all changes to take effect.")
            else:
                image_result = "failure"
                message_text = _("The upgrade did not succeed. Make sure you are connected to the Internet and try to upgrade again.")

                # Display the failure message
                self.update_progress_bar(0)
                self.update_status_label(message_text)
                self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/%s.png' % image_result, message_text)

        except Exception as e:
            print(f"Error during upgrade process: {e}")
            self.update_progress_bar(0)
            self.update_status_label(_("An error occurred during the upgrade process. Please try again later."))
            self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/failure.png', _("An error occurred during the upgrade process. Please try again later."), Gtk.MessageType.ERROR)
            return

    def update_progress_bar(self, percentage):
        """
        Updates the progress bar with the given percentage.
        """
        fraction = percentage / 100.0
        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text("%s%%" % percentage)

    def update_status_label(self, text):
        """
        Updates the status label with the given text.
        """
        self.status_label.set_markup(text)

    def cancel_upgrade(self, widget):
        """
        Cancels the upgrade process.
        """
        # Send a signal to the upgrade thread to stop
        os.kill(os.getpid(), signal.SIGINT)
        self.update_progress_bar(0)
        self.update_status_label(_("Upgrade canceled."))
        self.show_message('/usr/lib/linuxmint/mintUpdate/rel_upgrades/cancel.png', _("Upgrade canceled."), Gtk.MessageType.INFO)


Assistant()
Gtk.main()
