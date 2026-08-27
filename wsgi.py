"""
Entry point WSGI per PythonAnywhere (e per qualsiasi server WSGI).

PythonAnywhere importa questo modulo e usa l'oggetto `application`.
Per lo sviluppo locale continua a usare: py -3.12 app.py
"""
from app import app as application

if __name__ == "__main__":
    application.run()
