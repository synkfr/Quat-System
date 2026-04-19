import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def test_ai():
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("AI_MODEL", "google/gemini-2.0-flash-001")
    base_url = "https://openrouter.ai/api/v1/chat/completions"
    
    print(f"Testing AI with model: {model}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello, are you working?"}
        ],
    }
    
    try:
        response = requests.post(base_url, headers=headers, json=payload, timeout=30)
        print(f"Status: {response.status_code}")
        result = response.json()
        if "choices" in result:
            print(f"Response: {result['choices'][0]['message']['content']}")
        else:
            print(f"Error Result: {result}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_ai()
