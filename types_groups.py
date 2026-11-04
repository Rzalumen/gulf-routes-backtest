"""ICAO type -> group: one list for make_patterns.py (map patterns.json) and inspect_day.py (4 Nov 2026 review).
make_patterns.py's list + the codes only patterns.py had (added at the end of their group, so every code
make_patterns.py already knew keeps its group). First group wins (A332 = tanker, GLF5 = ISR).
patterns.py keeps its own list until the GLF5 / GLF6 (ISR or VIP) and MQ9 (ISR or DRONE) question is settled."""
GROUPS = {
    'TANKER': 'K35R K35E K35T KC135 KC46 B762 KC10 DC10 A332 A330 MRTT K30 B703 B707 KC30 KC390 C390 K46 KC2 KC39 C135',
    'AIRLIFT': 'C17 C5M C5 C30J C130 A400 C2 B744 IL76 C27J CN35 C295 A124 Y20',
    'ISR': 'R135 E3TF E3CF E3 E7 E737 E8 E6 P8 P3 E2 GLF5 GLF6 G550 U2 Q4 RQ4 GLEX R1 CL60 SHAD DH8C B350 E390 RC12 E767 E2C E2D MQ4 GLHK W135 EA37',
    'DRONE': 'Q9 MQ9 MQ1 HRON HERN Q1 Q4 RQ4 TB2 HER MQ1C',
    'BOMBER': 'B52 B1 B2 B21',
    'FIGHTER': 'F35 F16 F15 F18 FA18 F18S EUFI A10 F22 TOR RFAL M2K EA18 F15E',
    'VIP': 'C32 C37 C40 VC25 B742 B748 GLF4 GLF5 A319 A320 A321 A332 B737 B738 B752 B763 B77W FA7X F900 C750 C25B CL35 GLF6 IL96 T154 T214 IL62 LJ35 C560 C21 C12 F2TH B757 GA7C',
    'HELO': 'H60 S70 H47 CH47 H53 V22 H64 AS32 EC35 NH90 MRH9 H1 UH1Y AH1 H72',
}
TG = {}
for g, ts in GROUPS.items():
    for t in ts.split():
        TG.setdefault(t, g)

def group(t):
    return TG.get(((t or '').upper().split(' ') or [''])[0], 'OTHER')
