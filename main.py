import os
from flask import Flask, request, jsonify
import google.genai as genai

app = Flask(__name__)

# It's highly recommended to load secrets from a secure source.
# For Cloud Run, you can mount secrets from Google Secret Manager as environment variables.
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("The GEMINI_API_KEY environment variable is not set.")

genai.configure(api_key=API_KEY)

# Initialize the model
model = genai.GenerativeModel("gemini-1.5-flash-latest")

@app.route('/generate', methods=['POST'])
def generate_text():
    if not request.json or 'prompt' not in request.json:
        return jsonify({'error': 'The "prompt" field is required.'}), 400

    prompt = request.json['prompt']
    try:
        response = model.generate_content(prompt)
        return jsonify({'text': response.text})
    except Exception as e:
        app.logger.error(f"Error generating content: {e}")
        return jsonify({'error': 'An error occurred while generating content.'}), 500

if __name__ == '__main__':
    # Cloud Run provides the PORT environment variable.
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
