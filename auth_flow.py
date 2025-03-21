# shkhose@
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
import jwt
import secrets
import webbrowser
import time
import hashlib
import base64
from urllib.parse import urlparse, parse_qs
from threading import Thread, Lock
import json


# --- Configuration ---
# Use Salesforce OAuth App Consumer Key used in Workforce Identity Federation
SALESFORCE_CLIENT_ID = "<your-Key>"
# Use Salesforce OAuth App Consumer Secret used in Workforce Identity Federation
SALESFORCE_CLIENT_SECRET = "<Your-Secret>"
SALESFORCE_REDIRECT_URI = "http://localhost:8000/callback"
SALESFORCE_DOMAIN = "<Your-Salesforce-Domain>"
WORKFORCE_POOL_ID = "<workforce-pool>"
WORKFORCE_PROVIDER_ID = "<OIDC-Provider>"
BILLING_PROJECT_NUMBER = "<Project-Number>"   
GOOGLE_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# --- Threading and State Management ---
auth_code = None
received_state = None
server_lock = Lock()
server_ready = False
code_verifier = None

# --- Callback Handler ---
class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, received_state
        query_params = parse_qs(urlparse(self.path).query)

        if "code" in query_params and "state" in query_params:
            with server_lock:
                auth_code = query_params["code"][0]
                received_state = query_params["state"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Authentication successful! Close this window.")
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Error: Missing code or state.")

def run_server():
    global server_ready
    httpd = HTTPServer(('localhost', 8000), CallbackHandler)
    with server_lock:
        server_ready = True
    httpd.handle_request()
    httpd.server_close()

# --- Helper Functions for PKCE ---
def generate_code_verifier():
    return secrets.token_urlsafe(64)

def generate_code_challenge(code_verifier):
    hashed = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(hashed).decode('utf-8').rstrip('=')

# --- Main Functions ---
def get_salesforce_token():
    global auth_code, received_state, server_ready, code_verifier
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)
    server_ready = False
    auth_code = None
    received_state = None

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    server_thread = Thread(target=run_server)
    server_thread.start()

    while not server_ready:
        time.sleep(0.1)

    auth_url = (
        f"https://{SALESFORCE_DOMAIN}/services/oauth2/authorize?"
        f"response_type=code&client_id={SALESFORCE_CLIENT_ID}&"
        f"redirect_uri={SALESFORCE_REDIRECT_URI}&"
        f"state={state}&nonce={nonce}&"
        f"code_challenge={code_challenge}&code_challenge_method=S256"
    )
    webbrowser.open(auth_url)

    timeout = 60
    start_time = time.time()
    while time.time() - start_time < timeout:
        with server_lock:
            if auth_code and received_state:
                break
        time.sleep(0.1)
    else:
        raise TimeoutError("Timeout waiting for callback.")
    server_thread.join()

    with server_lock:
        if received_state != state:
            raise ValueError("State mismatch.")
        if not auth_code:
            raise ValueError("No authorization code received")

        token_url = f"https://{SALESFORCE_DOMAIN}/services/oauth2/token"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": SALESFORCE_CLIENT_ID,
            "client_secret": SALESFORCE_CLIENT_SECRET,
            "redirect_uri": SALESFORCE_REDIRECT_URI,
            "code": auth_code,
            "code_verifier": code_verifier,
        }

    try:
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        token_response = response.json()
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("id_token missing.")
        print(f"Salesforce Token Response: {token_response}")

        decoded_token = jwt.decode(
            id_token,
            options={"verify_signature": False},
            audience=SALESFORCE_CLIENT_ID,
            algorithms=["RS256"],
        )
        print(f"Salesforce ID Token (decoded - no signature check): {decoded_token}")

        if decoded_token["nonce"] != nonce:
             raise ValueError("Nonce mismatch.")

    except requests.exceptions.RequestException as e:
        raise ValueError(f"Salesforce token request failed: {e}")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid ID token: {e}")

    return id_token


def exchange_for_google_token(sf_id_token):
    token_url = "https://sts.googleapis.com/v1/token"

    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "audience": f"//iam.googleapis.com/locations/global/workforcePools/{WORKFORCE_POOL_ID}/providers/{WORKFORCE_PROVIDER_ID}",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
        "subject_token": sf_id_token,
        "scope": GOOGLE_SCOPE,
    }

    if BILLING_PROJECT_NUMBER:
        data["options"] = json.dumps({"userProject": BILLING_PROJECT_NUMBER})

    try:
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        google_token_response = response.json()
        print("Google STS Response:", google_token_response)  # Print the entire response
        return google_token_response
    except requests.exceptions.RequestException as e:
        print("Google STS Request Data:", data)  # Print the request data
        raise ValueError(f"Google STS token exchange failed: {e}")


# # --- Main Execution ---
# if __name__ == "__main__":
#     try:
#         print("#################### SFDC Token ##################")
#         sf_token = get_salesforce_token()
#         print("#################### Google Tokens ##################")
#         google_token = exchange_for_google_token(sf_token)
#         print("Google Cloud Access Token:", google_token["access_token"])
#         print("Expires in:", google_token.get("expires_in", "Unknown"), "seconds")
#     except Exception as e:
#         print(f"Error: {e}")
#         if isinstance(e, requests.exceptions.RequestException) and e.response:
#             print("Server response:", e.response.text)
