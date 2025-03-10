# shkhose@
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import auth_flow  # Import the entire module

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/token")
def get_token():
    try:
        # Step 1: Get the Salesforce token.
        sf_token = auth_flow.get_salesforce_token()

        # Step 2: Exchange the Salesforce token for a Google token.
        google_token_response = auth_flow.exchange_for_google_token(sf_token)

        # Step 3: Extract the access token and (optionally) expiry.
        access_token = google_token_response.get("access_token")
        expires_in = google_token_response.get("expires_in", 3600)  # Default to 1 hour

        if not access_token:
            raise ValueError("Google access token not found in response.")

        # Step 4: Return the token to the client.
        return jsonify({"access_token": access_token, "expires_in": expires_in})

    except TimeoutError as e:
        return jsonify({"error": "Authentication timed out.", "detail": str(e)}), 408 # 408 Request Timeout
    except ValueError as e:
        return jsonify({"error": "Authentication error.", "detail": str(e)}), 401  # 401 Unauthorized
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "detail": str(e)}), 500  # 500 Internal Server Error

# Start the server
if __name__ == "__main__":
    app.run(host="localhost", port=8001) # Remove debug=True for production