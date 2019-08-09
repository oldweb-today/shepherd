import os
import time
import hmac
import hashlib
import base64
import re
import urllib.parse

#=============================================================================
class WebRTCTurnCredentials():
    @staticmethod
    def get_credentials(reqid):
        time_limit = int(os.environ.get("WEBRTC_TURN_TIME_LIMIT", '3600'))
        separator = os.environ.get("WEBRTC_TURN_REST_API_SEPARATOR", '_').encode()
        turn_username = reqid.encode()
        turn_secret = os.environ.get("WEBRTC_TURN_SECRET").encode()
        now = "{}".format(int(time.time() + time_limit)).encode()

        username = separator.join([now, turn_username])
        password = base64.b64encode(hmac.new(turn_secret, username, digestmod=hashlib.sha1).digest())

        return {"username": username.decode("utf8"), "password": password.decode("utf8")}

    @staticmethod
    def get_credential_for_webrtcbin(reqid):
        credentials = WebRTCTurnCredentials.get_credentials(reqid)
        username = urllib.parse.quote_plus(credentials["username"])
        password = urllib.parse.quote_plus(credentials["password"])

        reg = '(turn:)?(//)?(?P<host>[a-zA-Z0-9\.\-]+):(?P<port>[0-9]+).*'
        result = re.search(reg, os.environ.get('WEBRTC_TURN_SERVER'))
        if result:
            host = result.group('host')
            port = result.group('port')
        else:
            print("Cannot parse Turn server URI")
        webrtc_url = 'turn://{username}:{password}@{host}:{port}'.format(**locals())

        return webrtc_url