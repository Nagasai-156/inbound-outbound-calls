with open("src/agent.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if any(k in line.lower() for k in ("session.start", "greeting", "first", "outbound")):
        print(f"{i+1}: {ascii(line.strip())}")
