"""Kontoauszuege – Backend with Claude proxy via OpenRouter."""
import json
import os
import re
from flask import Flask, request, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder=".")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CLASSIFIED_FILE = os.path.join(DATA_DIR, "classified.json")

# API key from environment or .env
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_KEY:
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    OPENROUTER_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4"

CATEGORIES = [
    "Wohnen & Kredit", "Lebensmittel", "Amazon & Shopping",
    "Auto & Mobilitaet", "Versicherungen", "KI & Software",
    "Telefon & Internet", "Streaming & Abos", "Gastronomie",
    "Bildung & Sprachen", "Kleidung & Mode", "Gesundheit",
    "Sport & Freizeit", "Heim & Garten", "Drogerie",
    "Sparen & Invest", "Steuern & Abgaben", "Spenden",
    "Bankgebuehren", "Sonstiges"
]

CATEGORIES_ORIG = [
    "Wohnen & Kredit", "Lebensmittel", "Amazon & Shopping",
    "Auto & Mobilität", "Versicherungen", "KI & Software",
    "Telefon & Internet", "Streaming & Abos", "Gastronomie",
    "Bildung & Sprachen", "Kleidung & Mode", "Gesundheit",
    "Sport & Freizeit", "Heim & Garten", "Drogerie",
    "Sparen & Invest", "Steuern & Abgaben", "Spenden",
    "Bankgebühren", "Sonstiges"
]

RULES = [
    {"kw": "amazon|amzn|audible", "cat": "Amazon & Shopping"},
    {"kw": "rewe|edeka|aldi|penny|netto|lidl|marktkauf|wez|e.center|denn.s|biomarkt|picnic|fleischerei|getraenke", "cat": "Lebensmittel"},
    {"kw": "kfz|tankstelle|shell|classic.tank|joiss.tank|total.service|hem.tank|mr.wash|autowaesch", "cat": "Auto & Mobilität"},
    {"kw": "versicherung|unfall|brandkasse|lvm|getsafe|hanse", "cat": "Versicherungen"},
    {"kw": "claude|anthropic|openai|cursor|lovable|perplexity|chatgpt|polygon|vercel|hostinger", "cat": "KI & Software"},
    {"kw": "vodafone|klarmobil|drillisch|handyvertrag", "cat": "Telefon & Internet"},
    {"kw": "netflix|apple services|google pay|playstation|spotify|exaring|waipu", "cat": "Streaming & Abos"},
    {"kw": "doener|kebap|pizza|falafel|ristorante|mcdonalds|steinofen|backfactory|baeckerei|kamps|neotaste|restaurant|wilma", "cat": "Gastronomie"},
    {"kw": "preply|sprachkurs|kurs|schule|bildung", "cat": "Bildung & Sprachen"},
    {"kw": "zalando|deichmann|temu|h&m|h.m.de|rituals|vinted", "cat": "Kleidung & Mode"},
    {"kw": "apotheke|arzt|zahnarzt|dzr|kranken", "cat": "Gesundheit"},
    {"kw": "fitnessstudio|wellpass|egym|sport|deisterflieger", "cat": "Sport & Freizeit"},
    {"kw": "hellweg|obi|baumarkt|hagebau|samenhandlung", "cat": "Heim & Garten"},
    {"kw": "rossmann|dm.drogerie|drogerie", "cat": "Drogerie"},
    {"kw": "sparen|ruecklagen|depot|etf|invest|vorabpauschale", "cat": "Sparen & Invest"},
    {"kw": "finanzamt|steuern|grunderwerbsteuer|bundeskasse", "cat": "Steuern & Abgaben"},
    {"kw": "greenpeace|spende|foerdererbeitrag", "cat": "Spenden"},
    {"kw": "hauskredit|kredit|darlehen|finanzierung", "cat": "Wohnen & Kredit"},
    {"kw": "dkb.*entgelt|dkb.*zinsen|abrechnung.*zinsen|girokarte", "cat": "Bankgebühren"},
]


def quick_classify(empfaenger, verwendung):
    combined = (empfaenger + " " + verwendung).lower()
    for rule in RULES:
        try:
            if re.search(rule["kw"], combined, re.IGNORECASE):
                return rule["cat"]
        except re.error:
            pass
    return "Sonstiges"


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/classify", methods=["POST"])
def classify():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    batch = data.get("batch", [])
    rules_raw = data.get("rules", [])

    if not batch:
        return jsonify({"categories": []})

    if not OPENROUTER_KEY:
        results = [quick_classify(t.get("Empfaenger", ""), t.get("Verwendung", "")) for t in batch]
        return jsonify({"categories": results})

    rules_str = "\n".join(
        f'- Enthaelt "{r["kw"]}" -> "{r["cat"]}"'
        for r in (rules_raw[:15] if rules_raw else RULES[:15])
    )
    txn_list = "\n".join(
        f'{i}: {t.get("Empfaenger", "")} | {t.get("Verwendung", "")} | {t.get("Betrag", 0)}Eur'
        for i, t in enumerate(batch)
    )
    cat_list = ", ".join(CATEGORIES_ORIG)

    prompt = (
        f"Buchhalter-KI: Klassifiziere jede Transaktion in genau eine Kategorie.\n\n"
        f"REGELN:\n{rules_str}\n\n"
        f"KATEGORIEN: {cat_list}\n\n"
        f"TRANSAKTIONEN:\n{txn_list}\n\n"
        f"Nur JSON-Array mit {len(batch)} Kategorien. Beispiel: [\"Lebensmittel\",\"KI & Software\"]"
    )

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["choices"][0]["message"]["content"]

        json_match = re.search(r"\[.*?\]", text, re.DOTALL)
        if json_match:
            cats = json.loads(json_match.group(0))
        else:
            cats = []

        if len(cats) != len(batch):
            cats = [quick_classify(t.get("Empfaenger", ""), t.get("Verwendung", "")) for t in batch]

        cats = [c if c in CATEGORIES_ORIG else "Sonstiges" for c in cats]
        return jsonify({"categories": cats})

    except Exception as e:
        results = [quick_classify(t.get("Empfaenger", ""), t.get("Verwendung", "")) for t in batch]
        return jsonify({"categories": results, "fallback": True, "error": str(e)})


@app.route("/api/data", methods=["GET"])
def get_data():
    """Return Hermes-preclassified data from classified.json."""
    if os.path.exists(CLASSIFIED_FILE):
        with open(CLASSIFIED_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"transactions": data, "source": "hermes"})
    return jsonify({"transactions": [], "source": "none"})


if __name__ == "__main__":
    port = int(os.environ.get("TOOL_PORT", "5111"))
    app.run(host="0.0.0.0", port=port, debug=False)
