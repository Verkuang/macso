"""Use GitHub's short-lived identity; keep JWTs out of logs and files."""
import json
import os
import subprocess
import urllib.parse
import urllib.request


def connect():
    audience = os.environ['TS_OIDC_AUDIENCE']
    url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']
    url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'audience': audience})
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urllib.request.urlopen(request, timeout=30) as response:
        identity = json.load(response)['value']
    # Same preapproval/ephemeral options as the official Tailscale GitHub action.
    binary = subprocess.check_output(['brew', '--prefix'], text=True).strip() + '/bin/tailscale'
    result = subprocess.run([
        'sudo', binary, '--socket=' + os.environ['TS_SOCKET'], 'up',
        '--client-id=' + os.environ['TS_OIDC_CLIENT_ID'] + '?preauthorized=true&ephemeral=true',
        '--id-token=' + identity, '--advertise-tags=tag:macso-desktop',
        '--hostname=macso-web-' + os.environ['GITHUB_RUN_ID'],
        '--accept-routes=false', '--accept-dns=false', '--timeout=2m'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=150)
    if result.returncode:
        raise SystemExit('Automatic private-network login failed; check the Tailscale trust rule.')
    print('Automatic private-network login completed.')


if __name__ == '__main__':
    connect()
