"""
Package File Search
Licensed under MIT
Copyright (c) 2012 Isaac Muse <isaacmuse@gmail.com>
"""

import sublime
import sublime_plugin
from os.path import join, basename, exists, isdir, dirname, normpath
from os import listdir, mkdir, chmod, rmdir, remove
import stat
import re
import zipfile
import tempfile
import shutil
from .lib.package_search import *

EXCLUDES = [".svn", ".hg", ".git", ".DS_Store"]

def log(s):
    print("PackageFileSearch: %s" % s)


def get_encoding(view):
    mapping = [
        ("with BOM", ""),
        ("Windows", "cp"),
        ("-", "_"),
        (" ", "")
    ]
    encoding = view.encoding()
    orig = encoding
    m = re.match(r'.+\((.*)\)', encoding)
    if m is not None:
        encoding = m.group(1)

    for item in mapping:
        encoding = encoding.replace(item[0], item[1])

    return ("utf_8", "UTF-8") if encoding in ["Undefined", "Hexidecimal"] else (encoding, orig)


def on_rm_error(func, path, exc_info):
    excvalue = exc_info[1]
    if func in (rmdir, remove):
        chmod(path, stat.S_IRWXU| stat.S_IRWXG| stat.S_IRWXO) # 0777
        try:
            func(path)
        except:
            if sublime.platform() == "windows":
                # Why are you being so stubborn windows?
                # This situation only randomly occurs
                log("Windows is being stubborn...go through rmdir to remove temp folder")
                import subprocess
                cmd = ["rmdir", "/S", path]
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    shell=False
                )
                returncode = process.returncode
                if returncode:
                    log("Why won't you play nice, Windows!")
                    log(process.communicate()[0])
                    raise
            else:
                raise
    else:
        raise

def open_package_file_zip(pth, resource):
    found = False
    win = sublime.active_window()
    with zipfile.ZipFile(pth, 'r') as z:
        for item in z.infolist():
            if resource == item.filename:
                found = True
                text = z.read(z.getinfo(resource))
                file_name = normpath(join(pth, resource))

                # Unpack the file in a temporary location
                d = tempfile.mkdtemp(prefix="pkgfs")
                with open(join(d, basename(file_name)), "wb") as f:
                    f.write(text)

                # Open and then close the file in a view in order
                # to let sublime guess encoding and syntax
                view = win.open_file(f.name)
                encoding, st_encoding = get_encoding(view)
                win.focus_view(view)
                win.run_command("close_file")
                syntax = view.settings().get('syntax')
                shutil.rmtree(d, onerror=on_rm_error)

                # When a file is opened from disk, you can't rename the
                # the path location.  If you try and use new_file,
                # you can give it a nice file path name, but the tab
                # will be huge.  If you use open_file, with a bogus path,
                # the view will be created with the desired filepath, and
                # it will properly display the basename as the tab name,
                # it will just report an issue reading the file in the console.
                # Reopen a new view and configure it with the
                # syntax and name and give the view a friendly name
                # opposed to an ugly temp directory
                view = win.open_file(file_name)
                view.set_syntax_file(syntax)
                view.set_encoding(st_encoding)
                try:
                    WriteArchivedPackageContentCommand.bfr = text.decode(encoding).replace('\r', '')
                except:
                    view.set_encoding("UTF-8")
                    WriteArchivedPackageContentCommand.bfr = text.decode("utf-8").replace('\r', '')
                sublime.set_timeout(lambda: view.run_command("write_archived_package_content"), 0)
                break
    return found


def open_package_file(pth):
    resource = pth.replace("\\", '/').replace("Packages/", "", 1)
    parts = resource.split('/')
    zip_pkg = "%s.sublime-package" % parts.pop(0)
    zip_resource = '/'.join(parts)
    installed, default, user = sublime_package_paths()
    user_res = normpath(join(user, resource))
    installed_res = join(installed, zip_pkg)
    default_res = join(default, zip_pkg)
    if exists(user_res):
        win = sublime.active_window()
        if win is not None:
            win.open_file(user_res)
    else:
        found = False
        if exists(installed_res):
            found = open_package_file_zip(installed_res, zip_resource)
        if not found and exists(default_res):
            found = open_package_file_zip(default_res, zip_resource)


class WriteArchivedPackageContentCommand(sublime_plugin.TextCommand):
    bfr = None
    def run(self, edit):
        cls = WriteArchivedPackageContentCommand
        if cls.bfr is not None:
            self.view.set_read_only(False)
            self.view.set_scratch(True)
            self.view.replace(edit, sublime.Region(0, self.view.size()), cls.bfr)
            sels = self.view.sel()
            sels.clear()
            sels.add(0)
            cls.bfr = None
            self.view.set_read_only(True)


class PackageFileSearchNavCommand(sublime_plugin.WindowCommand):
    def folder_select(self, value, folder_items, cwd, package_folder):
        if value > -1:
            item = folder_items[value]
            sublime.set_timeout(lambda: self.nav_package(cwd, item, package_folder), 100)

    def nav_package(self, cwd, child, package_folder):
        target = cwd
        if child is not None:
            if target == package_folder and child == "..":
                sublime.set_timeout(self.show_packages, 100)
                return
            elif child == "..":
                target = dirname(target[:-1]) + '/'
            else:
                target = join(target, child)
        target = target.replace("\\", '/')
        folders = []
        files = []
        if not target.endswith('/'):
            open_package_file(target)
            return
        for c in get_package_contents(package_folder):
            if not c.startswith(target):
                continue
            parts = c.replace(target, "").split('/')
            if parts[0] in EXCLUDES:
                continue
            if len(parts) > 1 and parts[0] + '/' not in folders:
                folders.append(parts[0] + '/')
            elif parts[0] not in files:
                files.append(parts[0])
        folders.sort()
        files.sort()
        folder_items = [".."] + folders + files
        self.window.show_quick_panel(
            folder_items,
            lambda x: self.folder_select(x, folder_items, target, package_folder)
        )

    def open_pkg(self, value):
        if value > -1:
            pkg = self.packages[value]
            sublime.set_timeout(lambda: self.nav_package("Packages/%s/" % pkg, None, "Packages/%s/" % pkg), 100)

    def show_packages(self):
        if len(self.packages):
            self.window.show_quick_panel(
                self.packages,
                self.open_pkg
            )

    def run(self):
        self.packages = get_packages()
        self.show_packages()


class _GetPackageFilesInputCommand(sublime_plugin.WindowCommand):
    find_mode = False

    def find_pattern(self, pattern, find_all=False):
        regex = False
        if pattern != "":
            m = re.match(r"^[ \t]*`(.*)`[ \t]*$", pattern)
            if m != None:
                regex = True
                pattern = m.group(1)
            self.window.run_command(
                "package_file_search",
                {
                    "pattern": pattern,
                    "regex": regex,
                    "find_all": find_all
                }
            )

    def run(self):
        self.window.show_input_panel(
            "File Pattern: ",
            "",
            lambda x: self.find_pattern(x, find_all=self.find_mode),
            None,
            None
        )

class PackageFileSearchInputCommand(_GetPackageFilesInputCommand):
    find_mode = False

    def is_enabled(self):
        return not FIND_ALL_MODE


class PackageFileSearchAllInputCommand(_GetPackageFilesInputCommand):
    find_mode = True

    def is_enabled(self):
        return FIND_ALL_MODE


class _GetPackageFilesMenuCommand(sublime_plugin.WindowCommand):
    find_mode = False

    def find_files(self, value, patterns, find_all):
        if value > -1:
            pat = patterns[value]
            sublime.set_timeout(
                lambda: self.window.run_command(
                    "package_file_search",
                    {
                        "pattern": pat["pattern"],
                        "regex": pat.get("regex", False),
                        "find_all": find_all
                    }
                ),
                100
            )

    def run(self, pattern_list=None):
        patterns = []
        if pattern_list is None:
            pattern_list = sublime.load_settings("package_file_search.sublime-settings").get("pattern_list", [])
        types = []
        for item in pattern_list:
            patterns.append(item["search"])
            types.append(item["caption"])
        if len(types) == 1:
            self.find_files(0, patterns, self.find_mode)
        elif len(types):
            self.window.show_quick_panel(
                types,
                lambda x: self.find_files(x, patterns=patterns, find_all=self.find_mode)
            )


class PackageFileSearchMenuCommand(_GetPackageFilesMenuCommand):
    find_mode = False

    def is_enabled(self):
        return not FIND_ALL_MODE


class PackageFileSearchAllMenuCommand(_GetPackageFilesMenuCommand):
    find_mode = True

    def is_enabled(self):
        return FIND_ALL_MODE


class PackageFileSearchExtractCommand(sublime_plugin.WindowCommand):
    def extract(self, value, packages):
        if value > -1:
            pkg = packages[value]
            name = packagename(pkg)
            dest = join(sublime.packages_path(), name)
            if not exists(dest):
                mkdir(dest)
            with zipfile.ZipFile(pkg) as z:
                z.extractall(dest)

    def run(self):
        defaults, installed, _ = get_packages_location()
        packages = defaults + installed
        if len(packages):
            self.window.show_quick_panel(
                [packagename(pkg) for pkg in packages],
                lambda x: self.extract(x, packages)
            )


class _PackageSearchCommand(sublime_plugin.WindowCommand, PackageSearch):
    def run(self, **kwargs):
        self.search(**kwargs)


class PackageFileSearchCommand(_PackageSearchCommand):
    def open_zip_file(self, fn):
        file_name = None
        zip_package = None
        zip_file = None
        for zp in sublime_package_paths():
            items = fn.replace('\\', '/').split('/')
            zip_package = items.pop(0)
            zip_file = '/'.join(items)
            if exists(join(zp, zip_package)):
                zip_package = join(zp, zip_package)
                file_name = join(zp, fn)
                break

        if file_name is not None:
            open_package_file_zip(zip_package, zip_file)

    def process_file(self, value, settings):
        if value > -1:
            if self.find_all:
                if value >= self.zipped_idx:
                    self.open_zip_file(settings[value][0])
                else:
                    self.window.open_file(join(self.packages, settings[value][0]))
            else:
                self.window.run_command("open_file", {"file": settings[value].replace("Packages", "${packages}", 1)})


class PackageFileSearchColorSchemeCommand(_PackageSearchCommand):
    def on_select(self, value, settings):
        if value != -1:
            sublime.load_settings("Preferences.sublime-settings").set("color_scheme", settings[value])

    def process_file(self, value, settings):
        if value != -1:
            sublime.load_settings("Preferences.sublime-settings").set("color_scheme", settings[value])
        else:
            if self.current_color_scheme is not None:
                sublime.load_settings("Preferences.sublime-settings").set("color_scheme", self.current_color_scheme)

    def pre_process(self, **kwargs):
        self.current_color_scheme = sublime.load_settings("Preferences.sublime-settings").get("color_scheme")
        return {"pattern": "*.tmTheme"}


class TogglePackageSearchFindAllModeCommand(sublime_plugin.ApplicationCommand):
    def run(self):
        global FIND_ALL_MODE
        FIND_ALL_MODE = False if FIND_ALL_MODE else True
        sublime.status_message("Package File Search: Find All = %s" % str(FIND_ALL_MODE))


def plugin_loaded():
    global FIND_ALL_MODE
    FIND_ALL_MODE = sublime.load_settings("package_file_search.sublime-settings").get("find_all_by_default", False)
