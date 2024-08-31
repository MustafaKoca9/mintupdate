import subprocess
from urllib.parse import quote

# GSettings command to fetch proxy configurations
GSETTINGS_CMDLINE = "gsettings list-recursively org.gnome.system.proxy"
CANNOT_PARSE_WARNING = "Cannot parse gsettings value: %r"
MISSING_KEY_WARNING = "Missing expected gsettings key: %r"
UNSUPPORTED_MODE_WARNING = "Unsupported proxy mode: %r"


def parse_proxy_hostspec(hostspec):
    """
    Parse the hostspec to extract protocol, hostname, username, and password.
    Supports parsing of full URLs (e.g., http://username:password@hostname:port).
    """
    protocol, username, password, hostname = None, None, None, hostspec

    if "://" in hostname:
        protocol, hostname = hostname.split("://", 1)
    if "@" in hostname:
        user_info, hostname = hostname.rsplit("@", 1)
        if ":" in user_info:
            username, password = user_info.split(":", 1)
        else:
            username = user_info

    return protocol, hostname, username, password


def proxy_url_from_settings(scheme, gsettings):
    """
    Construct the proxy URL for a given scheme (e.g., 'http', 'https') using gsettings data.
    Handles cases with/without authentication, and custom ports.
    """
    hostspec = gsettings.get(f"{scheme}.host", "")
    if not hostspec:
        print(MISSING_KEY_WARNING % f"{scheme}.host")
        return None

    protocol, host, username, password = parse_proxy_hostspec(hostspec)

    # If no host is specified, return None to indicate no proxy for this scheme
    if not host:
        return None

    port = gsettings.get(
        f"{scheme}.port", 8080
    )  # Default to port 8080 if not specified
    if not isinstance(port, int) or port <= 0:
        print(f"Invalid or missing port for {scheme}, defaulting to 8080.")
        port = 8080

    if scheme == "http" and gsettings.get("http.use-authentication", False):
        username = gsettings.get("http.authentication-user", username)
        password = gsettings.get("http.authentication-password", password)

    # URL encoding for username and password
    if username:
        username = quote(username)
        if password:
            password = quote(password)
            proxy_url = f"{username}:{password}@{host}:{port}"
        else:
            proxy_url = f"{username}@{host}:{port}"
    else:
        proxy_url = f"{host}:{port}"

    if protocol:
        proxy_url = f"{protocol}://{proxy_url}"

    return proxy_url


def get_proxy_settings():
    """
    Parse Gnome's proxy settings and return a dictionary containing proxy URLs
    for supported schemes (http, https). Includes handling for manual, auto, and direct modes.
    """
    try:
        output = subprocess.check_output(GSETTINGS_CMDLINE.split()).decode("utf-8")
    except subprocess.CalledProcessError as e:
        print(f"Error executing gsettings command: {e}")
        return {}

    gsettings = {}
    base_len = len("org.gnome.system.proxy.")

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            path, key, value = line.split(" ", 2)
        except ValueError:
            print(CANNOT_PARSE_WARNING % line)
            continue

        # Parse the value based on its type
        if value.startswith("'"):
            parsed_value = value[1:-1]
        elif value.startswith(("[", "@")):
            parsed_value = value
        elif value in ("true", "false"):
            parsed_value = value == "true"
        elif value.isdigit():
            parsed_value = int(value)
        else:
            print(CANNOT_PARSE_WARNING % value)
            parsed_value = value

        relative_key = (path + "." + key)[base_len:]
        gsettings[relative_key] = parsed_value

    mode = gsettings.get("mode", "none").lower()
    settings = {}

    if mode == "manual":
        for scheme in ["http", "https"]:
            scheme_settings = proxy_url_from_settings(scheme, gsettings)
            if scheme_settings:
                settings[scheme] = scheme_settings
    elif mode == "auto":
        pac_url = gsettings.get("autoconfig-url")
        if pac_url:
            settings["pac"] = pac_url
        else:
            print(MISSING_KEY_WARNING % "autoconfig-url")
    elif mode == "none" or mode == "direct":
        settings["direct"] = True
    else:
        print(UNSUPPORTED_MODE_WARNING % mode)

    return settings


def validate_proxy_settings(settings):
    """
    Validate the proxy settings dictionary to ensure all necessary information is present.
    Returns True if valid, False otherwise.
    """
    if not settings:
        print("No proxy settings found.")
        return False

    if "http" in settings:
        print(f"HTTP Proxy: {settings['http']}")
    if "https" in settings:
        print(f"HTTPS Proxy: {settings['https']}")
    if "pac" in settings:
        print(f"PAC URL: {settings['pac']}")
    if "direct" in settings:
        print("Direct connection (no proxy).")

    return True


def main():
    """
    Main function to fetch, validate, and display the proxy settings.
    """
    settings = get_proxy_settings()
    if validate_proxy_settings(settings):
        print("Proxy settings are valid and ready to use.")
    else:
        print("Proxy settings validation failed.")


if __name__ == "__main__":
    main()
