"""Crea el primer usuario admin del portal. Se ejecuta una sola vez:

    python bootstrap_admin.py

El PIN de acceso (4 dígitos) se crea después, la primera vez que ese
usuario entre a /login.html.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import auth as auth_module
from db import get_connection


def main():
    conn = get_connection()
    existentes = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    conn.close()
    if existentes > 0:
        print(f"Ya hay {existentes} usuario(s) creado(s). Usa la sección de Usuarios del portal para añadir más.")
        return

    print("Creando el primer usuario admin del portal.")
    username = input("Usuario (login): ").strip()
    nombre = input("Nombre a mostrar: ").strip()
    if not username:
        print("El usuario no puede estar vacío. Nada creado.")
        return

    auth_module.create_user(username, nombre or username, "admin")
    print(f"Usuario admin '{username}' creado. Entra a /login.html para crear tu PIN de 4 dígitos.")


if __name__ == "__main__":
    main()
