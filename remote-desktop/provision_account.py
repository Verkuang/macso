"""Recreate the authorized test administrator on a fresh temporary Mac."""
import getpass
import os
import subprocess
import sys

ACCOUNT = "desktop"

def run(arguments):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=45)

def main():
    if os.geteuid() != 0:
        print("Run this helper as the temporary Mac's administrator.", file=sys.stderr)
        return 1
    password = os.environ.pop("MACOS_ACCOUNT_PASSWORD", "")
    if "--prompt" in sys.argv:
        password = getpass.getpass("New desktop account password: ")
        if password != getpass.getpass("Confirm desktop account password: "):
            print("Passwords did not match. No account was created.")
            return 1
    if not password or any(c in password for c in ("\n", "\r", "\x00")):
        print("A nonempty MACOS_ACCOUNT_PASSWORD secret is required.", file=sys.stderr)
        return 1
    exists = run(["/usr/bin/id", ACCOUNT]).returncode == 0
    if not exists:
        result = run([
            "/usr/sbin/sysadminctl", "-addUser", ACCOUNT,
            "-fullName", "Project Test Desktop", "-admin", "-password", password,
        ])
        if result.returncode != 0:
            print("Desktop account creation failed. The password was not logged.", file=sys.stderr)
            return 1
    # sysadminctl may return zero on failure; verify both authentication and group.
    auth = run(["/usr/bin/dscl", ".", "-authonly", ACCOUNT, password])
    membership = run(["/usr/sbin/dseditgroup", "-o", "checkmember", "-m", ACCOUNT, "admin"])
    if auth.returncode != 0 or membership.returncode != 0 or not membership.stdout.lower().startswith("yes"):
        print("Desktop account authentication or administrator membership failed.", file=sys.stderr)
        return 1
    print("DESKTOP_ACCOUNT_READY: desktop authentication and administrator membership verified.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError):
        print("Desktop account provisioning failed or timed out. Credentials were not logged.", file=sys.stderr)
        sys.exit(1)
