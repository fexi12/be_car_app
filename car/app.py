from car.__init__ import create_app

app = create_app()

if __name__ == "__main__":
    # Dev server (Werkzeug) — don't use this in prod
    app.run(host="0.0.0.0", port=5000, debug=True)