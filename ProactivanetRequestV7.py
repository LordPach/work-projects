import requests
import pymysql
import json
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =========================================================
# CONFIG De las API y DB
# =========================================================
BOXHERO_API_URL = "https://rest.boxhero-app.com/v1/items"
BOXHERO_API_KEY = "box hero token"

API_URL = "Services api url here"
TOKEN = "Services api token here"

headers_boxhero = {
    "Authorization": f"Bearer {BOXHERO_API_KEY}",
    "Content-Type": "application/json"
}

headers_proactiva = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

conn = pymysql.connect(
    host="localhost",
    user="admin",
    password="24315",
    database="boxhero_inventory",
    cursorclass=pymysql.cursors.DictCursor
)

# =========================================================
# Ajuste para enviar el correo al finalizar el proceso con el resumen de errores
# =========================================================
EMAIL_FROM = "jesusanria@gmail.com"
EMAIL_PASSWORD = "vxfe psdp wngl huys"
EMAIL_TO = "roketkevin@gmail.com"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# =========================================================
# MAPEO TIPOS(categorias de producto) en boxhero a los IDs de ProactivaNet
# =========================================================
PAN_DEVICE_TYPES = {
    "Maquinaria": "c4896740-bcac-4ccd-bfc7-1235c796cc84",
    "Electrodomestico": "d2a00121-b07c-43db-ba3a-f4714b4e2c15",
    "Bricolaje (Jardineria)": "544e4ab9-7c06-41a6-8784-57d5db1c86e3"
}

# =========================================================
# LOG para las acciones del script, con timestamp para mejor seguimiento
# =========================================================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# =========================================================
# UTILIDADES
# =========================================================
def obtener_tipo_producto(producto):
    for attr in producto.get("attrs", []):
        if attr.get("name") == "Tipo":
            return attr.get("value")
    return None

def normalizar_producto(producto, tipo):
    return {
        "nombre": producto.get("name", ""),
        "tipo": tipo,
        "sku": producto.get("sku", ""),
        "barcode": producto.get("barcode", "")
    }

# =========================================================
# API
# =========================================================
def crear_device(name, description, tipo_producto):

    pan_device_id = PAN_DEVICE_TYPES.get(tipo_producto)

    if not pan_device_id:
        return False, "TIPO_INVALIDO"

    payload = {
        "Name": name,
        "Description": description,
        "Serial": "00000000-0000-0000-0000-000000000000",
        "PanDeviceTypes_id": pan_device_id,
        "PanHardwareStatus_id": "256dea94-f9c0-4645-b2ee-619347e4b8f7"
    }

    try:
        response = requests.post(API_URL, headers=headers_proactiva, json=payload)

        if response.status_code in [200, 201]:
            return True, "OK"
        else:
            return False, f"API_ERROR {response.status_code}"

    except Exception as e:
        return False, str(e)

# =========================================================
# OBTENER PRODUCTOS
# =========================================================
def obtener_productos_boxhero():
    response = requests.get(BOXHERO_API_URL, headers=headers_boxhero)

    if response.status_code != 200:
        log(f"❌ Error BoxHero: {response.status_code} {response.text}")
        return []

    return response.json().get("items", [])

# =========================================================
# PROCESAMIENTO
# =========================================================
productos_error = []

def procesar_producto(producto):

    nombre = producto.get("name", "")
    tipo = obtener_tipo_producto(producto)

    log(f"Procesando: {nombre}")
    log(f"Tipo detectado: {tipo}")

    # 🔴 FILTRO
    if tipo not in PAN_DEVICE_TYPES or not tipo:
        log(f"⛔ Tipo inválido → {tipo}")
        productos_error.append(normalizar_producto(producto, tipo))
        return

    with conn.cursor() as cursor:

        cursor.execute("SELECT * FROM productos WHERE id_boxhero=%s", (producto['id'],))
        existente = cursor.fetchone()

        stock_actual = int(producto.get('quantity', 0))

        # =====================================================
        # 🟢 PRODUCTO NUEVO
        # =====================================================
        if not existente:

            creado, motivo = crear_device(
                f"Creación: {nombre}",
                f"Stock inicial: {stock_actual}",
                tipo
            )

            if not creado:
                log(f"❌ Fallo API (nuevo) → {motivo}")
                productos_error.append(normalizar_producto(producto, tipo))
                return

            cursor.execute("""
                INSERT INTO productos
                (id_boxhero,nombre,sku,barcode,costo,precio,cantidad_total)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,(
                producto['id'],
                nombre,
                producto.get('sku',''),
                producto.get('barcode',''),
                producto.get('cost',0),
                producto.get('price',0),
                stock_actual
            ))

            conn.commit()
            log("✅ Insertado en DB y API")

        # =====================================================
        # 🟡 PRODUCTO EXISTENTE
        # =====================================================
        else:

            stock_anterior = existente['cantidad_total']

            if stock_actual == stock_anterior:
                log("ℹ️ Sin cambios de stock")
                return

            diferencia = stock_actual - stock_anterior

            # 🧠 mensaje inteligente
            if diferencia > 0:
                descripcion = f"Ingreso de {diferencia} unidades"
            else:
                descripcion = f"Retiro de {abs(diferencia)} unidades"

            creado, motivo = crear_device(
                f"Movimiento: {nombre}",
                f"{descripcion} | {stock_anterior} → {stock_actual}",
                tipo
            )

            if not creado:
                log(f"❌ Fallo API (update) → {motivo}")
                productos_error.append(normalizar_producto(producto, tipo))
                return

            # ✅ SOLO si API OK
            cursor.execute("""
                UPDATE productos SET cantidad_total=%s
                WHERE id_boxhero=%s
            """,(stock_actual,producto['id']))

            conn.commit()
            log("🔄 Actualizado en DB y API")

# =========================================================
# EMAIL
# =========================================================
def enviar_correo_reporte():

    if not productos_error:
        return

    mensaje = "Productos con errores en ProactivaNet:\n\n"

    for p in productos_error:
        mensaje += f"""
Nombre: {p.get('nombre','')}
Tipo: {p.get('tipo','')}
SKU: {p.get('sku','')}
Barcode: {p.get('barcode','')}
----------------------------------
"""

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = "Errores de sincronización ProactivaNet"

    msg.attach(MIMEText(mensaje, "plain"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        server.quit()

        log("📧 Correo enviado")

    except Exception as e:
        log(f"❌ Error enviando correo: {e}")

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":

    productos = obtener_productos_boxhero()

    log(f"Total productos recibidos: {len(productos)}")

    for producto in productos:
        try:
            procesar_producto(producto)
        except Exception as e:
            log(f"💥 Error inesperado: {e}")

    log("=================================")
    log(f"Productos con error: {len(productos_error)}")

    for p in productos_error:
        log(f"❌ {p['nombre']} | Tipo: {p['tipo']}")

    # 📧 ENVÍO FINAL
    enviar_correo_reporte()

    conn.close()
