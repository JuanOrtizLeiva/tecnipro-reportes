"""Gestión de usuarios por línea de comandos.

Uso:
    python -m src.web.user_manager add --email user@test.cl --nombre "Nombre" --rol admin --password "pass"
    python -m src.web.user_manager add --email user@test.cl --nombre "Nombre" --rol comprador --cursos 140 143 --empresa "ACME Inc" --password "pass"
    python -m src.web.user_manager list
    python -m src.web.user_manager password --email user@test.cl --password "nueva"
    python -m src.web.user_manager remove --email user@test.cl
    python -m src.web.user_manager add-curso --email user@test.cl --curso 143
"""

import argparse
import json
import sys
from pathlib import Path

# Asegurar que config sea importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import settings
from src.web.auth import hash_password


def _load_users():
    """Carga usuarios.json. Retorna dict con clave 'usuarios'."""
    path = settings.USUARIOS_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"usuarios": []}


def _save_users(data):
    """Guarda usuarios.json."""
    path = settings.USUARIOS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_user_data(email):
    """Busca un usuario por email. Retorna dict o None."""
    for u in _load_users().get("usuarios", []):
        if u["email"].lower() == email.lower():
            return u
    return None


def add_user(email, nombre, rol, password, cursos=None, empresa=None):
    """Agrega un usuario nuevo."""
    data = _load_users()

    # Verificar si ya existe
    for u in data["usuarios"]:
        if u["email"].lower() == email.lower():
            print(f"ERROR: El usuario {email} ya existe.")
            return False

    if rol not in ("admin", "comprador"):
        print(f"ERROR: Rol inválido '{rol}'. Usar 'admin' o 'comprador'.")
        return False

    user = {
        "email": email,
        "password_hash": hash_password(password),
        "nombre": nombre,
        "rol": rol,
        "cursos": cursos or [],
        "empresa": empresa or "",
    }
    data["usuarios"].append(user)
    _save_users(data)
    print(f"Usuario {email} ({rol}) creado exitosamente.")
    return True


def list_users():
    """Lista todos los usuarios."""
    data = _load_users()
    usuarios = data.get("usuarios", [])
    if not usuarios:
        print("No hay usuarios registrados.")
        return

    print(f"\n{'Email':<35} {'Nombre':<30} {'Rol':<12} {'Cursos'}")
    print("-" * 95)
    for u in usuarios:
        cursos_str = ", ".join(str(c) for c in u.get("cursos", []))
        print(f"{u['email']:<35} {u['nombre']:<30} {u['rol']:<12} {cursos_str or '—'}")
    print(f"\nTotal: {len(usuarios)} usuarios")


def remove_user(email):
    """Elimina un usuario."""
    data = _load_users()
    original_count = len(data["usuarios"])
    data["usuarios"] = [
        u for u in data["usuarios"] if u["email"].lower() != email.lower()
    ]

    if len(data["usuarios"]) == original_count:
        print(f"ERROR: Usuario {email} no encontrado.")
        return False

    _save_users(data)
    print(f"Usuario {email} eliminado.")
    return True


def change_password(email, password):
    """Cambia la contraseña de un usuario."""
    data = _load_users()
    for u in data["usuarios"]:
        if u["email"].lower() == email.lower():
            u["password_hash"] = hash_password(password)
            _save_users(data)
            print(f"Contraseña de {email} actualizada.")
            return True

    print(f"ERROR: Usuario {email} no encontrado.")
    return False


def add_curso(email, curso_id):
    """Agrega un curso a un comprador."""
    data = _load_users()
    for u in data["usuarios"]:
        if u["email"].lower() == email.lower():
            cursos = u.get("cursos", [])
            if curso_id in cursos:
                print(f"El curso {curso_id} ya está asignado a {email}.")
                return True
            cursos.append(curso_id)
            u["cursos"] = cursos
            _save_users(data)
            print(f"Curso {curso_id} asignado a {email}.")
            return True

    print(f"ERROR: Usuario {email} no encontrado.")
    return False


def main():
    """Punto de entrada CLI."""
    parser = argparse.ArgumentParser(
        description="Gestión de usuarios Tecnipro",
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando")

    # add
    add_parser = subparsers.add_parser("add", help="Agregar usuario")
    add_parser.add_argument("--email", required=True)
    add_parser.add_argument("--nombre", required=True)
    add_parser.add_argument("--rol", required=True, choices=["admin", "comprador"])
    add_parser.add_argument("--password", required=True)
    add_parser.add_argument("--cursos", type=int, nargs="*", default=[])
    add_parser.add_argument("--empresa", default="")

    # list
    subparsers.add_parser("list", help="Listar usuarios")

    # remove
    rm_parser = subparsers.add_parser("remove", help="Eliminar usuario")
    rm_parser.add_argument("--email", required=True)

    # password
    pw_parser = subparsers.add_parser("password", help="Cambiar contraseña")
    pw_parser.add_argument("--email", required=True)
    pw_parser.add_argument("--password", required=True)

    # add-curso
    ac_parser = subparsers.add_parser("add-curso", help="Agregar curso a usuario")
    ac_parser.add_argument("--email", required=True)
    ac_parser.add_argument("--curso", type=int, required=True)

    args = parser.parse_args()

    if args.command == "add":
        add_user(args.email, args.nombre, args.rol, args.password, args.cursos, args.empresa)
    elif args.command == "list":
        list_users()
    elif args.command == "remove":
        remove_user(args.email)
    elif args.command == "password":
        change_password(args.email, args.password)
    elif args.command == "add-curso":
        add_curso(args.email, args.curso)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
