import requests, json, os
from dotenv import load_dotenv
load_dotenv()
url = os.getenv("OPENAI_BASE_URL","").rstrip("/") + "/chat/completions"
key = os.getenv("OPENAI_API_KEY","")
model = os.getenv("OPENAI_MODEL","")

def test_prompt(sys_prompt, name):
    payload = {
        "model": model,
        "messages": [
            {"role":"system","content": sys_prompt},
            {"role":"user","content": "Give one short answer that is most likely to match another participant from the UK.\nCategory: Name a city"}
        ],
        "temperature": 1.0,
        "max_tokens": 512,
        "stream": False
    }
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=60)
        with open(f"log_{name}.txt", "w", encoding="utf-8") as f:
            f.write(f"Status: {r.status_code}\n")
            f.write(f"Text: {r.text}\n")
        print(f"Done {name}, status {r.status_code}")
    except Exception as e:
        print(f"Fail {name}: {e}")

test_prompt("You are taking part in a pure coordination task. Respond ONLY with the final city name. DO NOT include any Thinking Process, reasoning, or internal analysis. NO EXPLANATIONS.", "hard_instruction")
test_prompt("Respond with exactly one word. Forbidden to think or reason.", "one_word")
