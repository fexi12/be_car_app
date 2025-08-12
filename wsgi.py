# wsgi.py
from car.app_bcl import app  # your app lives in car/app.py
if __name__ == "__main__":
    app.run()
