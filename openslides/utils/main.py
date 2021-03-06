import argparse
import ctypes
import os
import sys
import tempfile
import threading
import time
import webbrowser
from typing import Dict, Optional

from django.conf import ENVIRONMENT_VARIABLE
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import get_random_string
from mypy_extensions import NoReturn


DEVELOPMENT_VERSION = "Development Version"
UNIX_VERSION = "Unix Version"
WINDOWS_VERSION = "Windows Version"
WINDOWS_PORTABLE_VERSION = "Windows Portable Version"


class PortableDirNotWritable(Exception):
    pass


class PortIsBlockedError(Exception):
    pass


class DatabaseInSettingsError(Exception):
    pass


class UnknownCommand(Exception):
    pass


class ExceptionArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UnknownCommand(message)


def detect_openslides_type() -> str:
    """
    Returns the type of this OpenSlides version.
    """
    if sys.platform == "win32":
        if os.path.basename(sys.executable).lower() == "openslides.exe":
            # Note: sys.executable is the path of the *interpreter*
            #       the portable version embeds python so it *is* the interpreter.
            #       The wrappers generated by pip and co. will spawn the usual
            #       python(w).exe, so there is no danger of mistaking them
            #       for the portable even though they may also be called
            #       openslides.exe
            openslides_type = WINDOWS_PORTABLE_VERSION
        else:
            openslides_type = WINDOWS_VERSION
    else:
        openslides_type = UNIX_VERSION
    return openslides_type


def get_default_settings_dir(openslides_type: str = None) -> str:
    """
    Returns the default settings path according to the OpenSlides type.

    The argument 'openslides_type' has to be one of the three types mentioned in
    openslides.utils.main.
    """
    if openslides_type is None:
        openslides_type = detect_openslides_type()

    if openslides_type == UNIX_VERSION:
        parent_directory = os.environ.get(
            "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
        )
    elif openslides_type == WINDOWS_VERSION:
        parent_directory = get_win32_app_data_dir()
    elif openslides_type == WINDOWS_PORTABLE_VERSION:
        parent_directory = get_win32_portable_dir()
    else:
        raise TypeError(f"{openslides_type} is not a valid OpenSlides type.")
    return os.path.join(parent_directory, "openslides")


def get_local_settings_dir() -> str:
    """
    Returns the path to a local settings.

    On Unix systems: 'personal_data/var/'
    """
    return os.path.join("personal_data", "var")


def setup_django_settings_module(
    settings_path: str = None, local_installation: bool = False
) -> None:
    """
    Sets the environment variable ENVIRONMENT_VARIABLE, that means
    'DJANGO_SETTINGS_MODULE', to the given settings.

    If no settings_path is given and the environment variable is already set,
    then this function does nothing.

    If the argument settings_path is set, then the environment variable is
    always overwritten.
    """
    if settings_path is None and os.environ.get(ENVIRONMENT_VARIABLE, ""):
        return

    if settings_path is None:
        if local_installation:
            settings_dir = get_local_settings_dir()
        else:
            settings_dir = get_default_settings_dir()
        settings_path = os.path.join(settings_dir, "settings.py")

    settings_file = os.path.basename(settings_path)
    settings_module_name = ".".join(settings_file.split(".")[:-1])
    if "." in settings_module_name:
        raise ImproperlyConfigured(
            "'.' is not an allowed character in the settings-file"
        )

    # Change the python path. Also set the environment variable python path, so
    # change of the python path also works after a reload
    settings_module_dir = os.path.abspath(os.path.dirname(settings_path))
    sys.path.insert(0, settings_module_dir)
    try:
        os.environ["PYTHONPATH"] = os.pathsep.join(
            (settings_module_dir, os.environ["PYTHONPATH"])
        )
    except KeyError:
        # The environment variable is empty
        os.environ["PYTHONPATH"] = settings_module_dir

    # Set the environment variable to the settings module
    os.environ[ENVIRONMENT_VARIABLE] = settings_module_name


def get_default_settings_context(user_data_dir: str = None) -> Dict[str, str]:
    """
    Returns the default context values for the settings template:
    'openslides_user_data_path', 'import_function' and 'debug'.

    The argument 'user_data_path' is a given path for user specific data or None.
    """
    # Setup path for user specific data (SQLite3 database, media, ...):
    # Take it either from command line or get default path
    default_context = {}
    if user_data_dir:
        default_context["openslides_user_data_dir"] = repr(user_data_dir)
        default_context["import_function"] = ""
    else:
        openslides_type = detect_openslides_type()
        if openslides_type == WINDOWS_PORTABLE_VERSION:
            default_context[
                "openslides_user_data_dir"
            ] = "get_win32_portable_user_data_dir()"
            default_context[
                "import_function"
            ] = "from openslides.utils.main import get_win32_portable_user_data_dir"
        else:
            data_dir = get_default_user_data_dir(openslides_type)
            default_context["openslides_user_data_dir"] = repr(
                os.path.join(data_dir, "openslides")
            )
            default_context["import_function"] = ""
    default_context["debug"] = "False"
    return default_context


def get_default_user_data_dir(openslides_type: str) -> str:
    """
    Returns the default directory for user specific data according to the OpenSlides
    type.

    The argument 'openslides_type' has to be one of the three types mentioned
    in openslides.utils.main.
    """
    if openslides_type == UNIX_VERSION:
        default_user_data_dir = os.environ.get(
            "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
        )
    elif openslides_type == WINDOWS_VERSION:
        default_user_data_dir = get_win32_app_data_dir()
    elif openslides_type == WINDOWS_PORTABLE_VERSION:
        default_user_data_dir = get_win32_portable_dir()
    else:
        raise TypeError(f"{openslides_type} is not a valid OpenSlides type.")
    return default_user_data_dir


def get_win32_app_data_dir() -> str:
    """
    Returns the directory of Windows' AppData directory.
    """
    shell32 = ctypes.WinDLL("shell32.dll")  # type: ignore
    SHGetFolderPath = shell32.SHGetFolderPathW
    SHGetFolderPath.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    )
    SHGetFolderPath.restype = ctypes.c_uint32

    CSIDL_LOCAL_APPDATA = 0x001C
    MAX_PATH = 260

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    res = SHGetFolderPath(0, CSIDL_LOCAL_APPDATA, 0, 0, buf)
    if res != 0:
        # TODO: Write other exception
        raise Exception("Could not determine Windows' APPDATA path")

    return buf.value  # type: ignore


def get_win32_portable_dir() -> str:
    """
    Returns the directory of the Windows portable version.
    """
    # NOTE: sys.executable will be the path to openslides.exe
    #       since it is essentially a small wrapper that embeds the
    #       python interpreter
    portable_dir = os.path.dirname(os.path.abspath(sys.executable))
    try:
        fd, test_file = tempfile.mkstemp(dir=portable_dir)
    except OSError:
        raise PortableDirNotWritable(
            "Portable directory is not writeable. "
            "Please choose another directory for settings and data files."
        )
    else:
        os.close(fd)
        os.unlink(test_file)
    return portable_dir


def get_win32_portable_user_data_dir() -> str:
    """
    Returns the user data directory to the Windows portable version.
    """
    return os.path.join(get_win32_portable_dir(), "openslides")


def write_settings(
    settings_dir: str = None,
    settings_filename: str = "settings.py",
    template: str = None,
    **context: str,
) -> str:
    """
    Creates the settings file at the given dir using the given values for the
    file template.

    Retuns the path to the created settings.
    """
    if settings_dir is None:
        settings_dir = get_default_settings_dir()
    settings_path = os.path.join(settings_dir, settings_filename)

    if template is None:
        with open(
            os.path.join(os.path.dirname(__file__), "settings.py.tpl")
        ) as template_file:
            template = template_file.read()

    # Create a random SECRET_KEY to put it in the settings.
    # from django.core.management.commands.startproject
    chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
    context.setdefault("secret_key", get_random_string(50, chars))
    for key, value in get_default_settings_context().items():
        context.setdefault(key, value)

    content = template % context
    settings_module = os.path.realpath(settings_dir)
    if not os.path.exists(settings_module):
        os.makedirs(settings_module)
    with open(settings_path, "w") as settings_file:
        settings_file.write(content)

    if context["openslides_user_data_dir"] == "get_win32_portable_user_data_dir()":
        openslides_user_data_dir = get_win32_portable_user_data_dir()
    else:
        openslides_user_data_dir = context["openslides_user_data_dir"].strip("'")
    os.makedirs(os.path.join(openslides_user_data_dir, "static"), exist_ok=True)
    return os.path.realpath(settings_path)


def open_browser(host: str, port: int) -> None:
    """
    Launches the default web browser at the given host and port and opens
    the webinterface. Uses start_browser internally.
    """
    if host == "0.0.0.0":
        # Windows does not support 0.0.0.0, so use 'localhost' instead
        start_browser(f"http://localhost:{port}")
    else:
        start_browser(f"http://{host}:{port}")


def start_browser(browser_url: str) -> None:
    """
    Launches the default web browser at the given url and opens the
    webinterface.
    """
    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        print("Could not locate runnable browser: Skipping start")
    else:

        def function() -> None:
            # TODO: Use a nonblocking sleep event here. Tornado has such features.
            time.sleep(1)
            browser.open(browser_url)

        thread = threading.Thread(target=function)
        thread.start()


def get_database_path_from_settings() -> Optional[str]:
    """
    Retrieves the database path out of the settings file. Returns None,
    if it is not a SQLite3 database.

    Needed for the backupdb command.
    """
    from django.conf import settings as django_settings
    from django.db import DEFAULT_DB_ALIAS

    db_settings = django_settings.DATABASES
    default = db_settings.get(DEFAULT_DB_ALIAS)
    if not default:
        raise DatabaseInSettingsError("Default databases is not configured")
    database_path = default.get("NAME")
    if not database_path:
        raise DatabaseInSettingsError("No path or name specified for default database.")
    if default.get("ENGINE") != "django.db.backends.sqlite3":
        database_path = None
    return database_path


def is_local_installation() -> bool:
    """
    Returns True if the command is called for a local installation

    This is the case if manage.py is used, or when the --local-installation flag is set.
    """
    return (
        True
        if "--local-installation" in sys.argv or "manage.py" in sys.argv[0]
        else False
    )


def is_windows() -> bool:
    """
    Returns True if the current system is Windows. Returns False otherwise.
    """
    return sys.platform == "win32"
