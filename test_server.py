import requests
import json

BASE_URL = "http://127.0.0.1:8069/v1"

def test_list_models():
    print("Testing GET /v1/models...")
    try:
        response = requests.get(f"{BASE_URL}/models")
        if response.status_code == 200:
            print("✅ Success")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_chat_completion():
    print("\nTesting POST /v1/chat/completions (Non-streaming)...")
    payload = {
        "model": "gemini-3-pro",
        "messages": [{"role": "user", "content": "Hello, are you running as a server?"}],
        "stream": False
    }
    
    try:
        response = requests.post(f"{BASE_URL}/chat/completions", json=payload)
        if response.status_code == 200:
            print("✅ Success")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_list_models()
    test_chat_completion()
