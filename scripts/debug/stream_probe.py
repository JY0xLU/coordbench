import requests, json, os
from dotenv import load_dotenv
load_dotenv()
url = os.getenv("OPENAI_BASE_URL","").rstrip("/") + "/chat/completions"
key = os.getenv("OPENAI_API_KEY","")
model = os.getenv("OPENAI_MODEL","")

# Test with higher token count AND extra_body to try disabling thinking
payload = {
    "model": model,
    "messages": [
        {"role":"system","content":"Return exactly one short answer."},
        {"role":"user","content":"Name a city."}
    ],
    "temperature": 1.0,
    "max_tokens": 4096,
    "stream": True
}
s = requests.Session()
s.trust_env = False
r = s.post(url, headers={
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "Accept": "text/event-stream, application/json",
}, json=payload, stream=True, timeout=120)
print(f"Status: {r.status_code}")
full_text = ""
event_count = 0
for raw_line in r.iter_lines():
    if not raw_line:
        continue
    line = raw_line.strip()
    if not line.startswith(b"data:"):
        continue
    data_str = line.decode("utf-8","ignore")
    if data_str.strip() in ("data: [DONE]", "data:[DONE]"):
        break
    try:
        chunk = json.loads(data_str[5:].strip())
    except:
        continue
    event_count += 1
    choices = chunk.get("choices",[])
    if choices:
        delta = choices[0].get("delta",{})
        content = delta.get("content")
        if isinstance(content, str):
            full_text += content
print(f"Total events: {event_count}")
print(f"Full text length: {len(full_text)} chars")
print("---FULL TEXT---")
print(full_text)
print("---END---")

# Check if </think> is present
if "</think>" in full_text.lower():
    parts = full_text.split("</think>")
    answer_part = parts[-1].strip()
    print(f"\nExtracted answer after </think>: [{answer_part}]")
else:
    print("\nNo </think> tag found - text was likely truncated")
