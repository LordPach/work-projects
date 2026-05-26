import requests
from datetime import datetime

# ================= CONFIGURACIÓN =================
BASE_URL = "your api link here"
TOKEN = "Your token here."
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# ID de los campos personalizados
TICKET_CUSTOM_FIELD_ID = "Custom tiket field ID here"
USER_CUSTOM_FIELD_ID = "Custom User field ID here"

# 📝 Nombre del log con fecha
LOG_FILE = f"log_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


# ================= FUNCIONES =================


# -------------------------------------------------
# Función de logging (imprime y guarda en archivo)
# -------------------------------------------------
def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{level}] {timestamp} - {message}"
    print(formatted)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")


# -------------------------------------------------
# Obtiene todos los tickets desde el endpoint Incidents
# Sin paginación para evitar duplicados y conteos inflados
# Retorna una lista de tickets o lista vacía en caso de error
# -------------------------------------------------
def get_all_incidents():
    try:
        log("🔄 Solicitando lista de tickets...")
        response = requests.get(f"{BASE_URL}/Incidents", headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Algunos ambientes devuelven formato {"Items":[...]}
        if isinstance(data, dict) and "Items" in data:
            log("Formato recibido: dict con 'Items'")
            return data["Items"]

        # Otros devuelven directamente una lista
        elif isinstance(data, list):
            log("Formato recibido: lista directa")
            return data

        log("⚠️ Formato inesperado de respuesta", "WARNING")
        return []

    except Exception as e:
        log(f"⛔ Error obteniendo tickets: {e}", "ERROR")
        return None


# -------------------------------------------------
# Obtiene los campos personalizados asociados a un ticket
# Se usa para verificar si el campo objetivo ya tiene valor
# Retorna lista de campos o lista vacía si falla la consulta
# -------------------------------------------------
def get_ticket_custom_fields(ticket_id):
    try:
        response = requests.get(
            f"{BASE_URL}/Incidents/{ticket_id}/customFields",
            headers=HEADERS,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"⛔ Error obteniendo campos del ticket {ticket_id}: {e}", "ERROR")
        return None


# -------------------------------------------------
# Obtiene los campos personalizados del usuario creador
# Es la fuente del valor que será copiado al ticket
# Retorna lista de campos o lista vacía en caso de error
# -------------------------------------------------
def get_user_custom_fields(user_id):
    try:
        response = requests.get(
            f"{BASE_URL}/Users/{user_id}/customFields",
            headers=HEADERS,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"⛔ Error obteniendo campos del usuario {user_id}: {e}", "ERROR")
        return None


# -------------------------------------------------
# Actualiza el campo personalizado del ticket
# Retorna True si el API confirma actualización exitosa
# Retorna False en caso de rechazo o error
# -------------------------------------------------
def update_ticket_custom_field(ticket_id, value):

    payload = [
        {
            "CustomField_id": TICKET_CUSTOM_FIELD_ID,
            "Value": value
        }
    ]

    try:
        response = requests.put(
            f"{BASE_URL}/Incidents/{ticket_id}/customFields",
            headers=HEADERS,
            json=payload,
            timeout=10
        )

        # Éxito real de actualización
        if response.status_code in (200, 204):
            return True, "OK"

        # El API respondió pero no lo permitió
        return False, response.text

    except Exception as e:
        return False, str(e)


# ================= LÓGICA PRINCIPAL =================

def main():
    log("===== INICIO DE EJECUCIÓN =====")
    log(f"🕒 {datetime.now()}")

    print("🔄 Analizando tickets...")

    all_incidents = get_all_incidents()

    if all_incidents is None:
        log("⛔ No se pudo obtener la lista de tickets. Abortando ejecución.", "ERROR")
        return

    total_tickets = len(all_incidents)

    log(f"📊 Total de tickets obtenidos: {total_tickets}")

    evaluated = 0
    candidates = 0
    updated = 0
    failed_updates = 0

    # Listas para auditoría
    updated_tickets = []
    failed_tickets = []

    for ticket in all_incidents:

        evaluated += 1

        ticket_id = ticket.get("Id")
        user_id = ticket.get("PanUsers_idSource")
        archived = ticket.get("Archived", False)

        # Ignorar tickets sin usuario, sin ID o archivados
        if not ticket_id or not user_id:
            log(f"⚠️ Ticket inválido detectado: {ticket}", "WARNING")
            continue

        if archived:
            log(f"📦 Ticket archivado ignorado: {ticket_id}", "INFO")
            continue

        ticket_fields = get_ticket_custom_fields(ticket_id)
        user_fields = get_user_custom_fields(user_id)

        # Control de errores en lectura
        if ticket_fields is None:
            failed_updates += 1
            failed_tickets.append((ticket_id, "Error obteniendo campos del ticket"))
            continue

        if user_fields is None:
            failed_updates += 1
            failed_tickets.append((ticket_id, "Error obteniendo campos del usuario"))
            continue

        # Buscar valor actual del ticket
        ticket_value = next(
            (f.get("Value") for f in ticket_fields
             if f.get("CustomField_id") == TICKET_CUSTOM_FIELD_ID),
            None
        )

        # Si ya tiene valor → no modificar
        if ticket_value:
            log(f"ℹ️ Ticket {ticket_id} ya tiene valor. Se omite.", "INFO")
            continue

        # Buscar valor del usuario
        user_value = next(
            (f.get("Value") for f in user_fields
             if f.get("CustomField_id") == USER_CUSTOM_FIELD_ID),
            None
        )

        # Si el usuario no tiene valor → no es candidato válido
        if not user_value:
            log(f"⚠️ Usuario {user_id} sin valor requerido. Ticket {ticket_id} descartado.", "WARNING")
            continue

        candidates += 1

        # Intentar actualización
        success, response_msg = update_ticket_custom_field(ticket_id, user_value)

        if success:
            updated += 1
            updated_tickets.append(ticket_id)
            log(f"✅ Ticket actualizado: {ticket_id}", "INFO")
        else:
            failed_updates += 1
            failed_tickets.append((ticket_id, response_msg))
            log(f"❌ Error en ticket {ticket_id} → {response_msg}", "ERROR")

        # Log cada 100 procesados
        if evaluated % 100 == 0:
            log(f"📌 Evaluados: {evaluated} | Candidatos: {candidates} | Actualizados: {updated}")

    # ================= RESULTADO FINAL =================
    log("\n===== RESULTADO FINAL =====")
    log(f"🧾 Tickets evaluados: {evaluated}")
    log(f"🟡 Candidatos válidos: {candidates}")
    log(f"✅ Tickets ACTUALIZADOS realmente: {updated}")
    log(f"⚠️ Fallos de actualización: {failed_updates}")

    # ================= DETALLE =================
    log("\n===== DETALLE ACTUALIZADOS =====")
    for t in updated_tickets:
        log(f"✔ {t}")

    log("\n===== DETALLE ERRORES =====")
    for t, err in failed_tickets:
        log(f"✖ {t} → {err}", "ERROR")

    log("\n===== FIN DE EJECUCIÓN =====")


if __name__ == "__main__":
    main()
