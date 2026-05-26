import requests
import pymysql
import json
from datetime import datetime

# =========================================================
# CONFIGURACIÓN BOXHERO
# =========================================================
BOXHERO_API_URL = "https://rest.boxhero-app.com/v1/items"
BOXHERO_API_KEY = "fc6b7a53-c4ea-4b42-9385-47320a638139"

headers_boxhero = {
    "Authorization": f"Bearer {BOXHERO_API_KEY}",
    "Content-Type": "application/json"
}

# =========================================================
# CONFIGURACIÓN BASE DE DATOS
# =========================================================
conn = pymysql.connect(
    host="localhost",
    user="admin",
    password="24315",
    database="boxhero_inventory",
    cursorclass=pymysql.cursors.DictCursor
)

# =========================================================
# CONFIGURACIÓN PROACTIVANET
# =========================================================
API_URL = "https://itjets.proactivanet.com/panet/api/Devices"

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJqY3NvbGlzQGl0amV0cy5jb20iLCJvdnIiOiJmYWxzZSIsImF1dCI6IjAiLCJuYmYiOjE3NzA4MzExODYsImV4cCI6MTgwMjM2NzE4NiwiaWF0IjoxNzcwODMxMTg2LCJpc3MiOiJwcm9hY3RpdmFuZXQiLCJhdWQiOiJhcGkifQ.bYDadvpPVl6CO0wecNGQoQSN5_16RMf8o19kuC78vWo"

headers_proactiva = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# =========================================================
# FUNCIÓN CREAR DEVICE EN PROACTIVANET
# =========================================================
def crear_device(name, description, federated_code=""):
    payload = {
        "Name": name,
        "Description": description,
        "Serial": "00000000-0000-0000-0000-000000000000",  # Ajusta si BoxHero da un serial real
        "PanDeviceTypes_id": "c4896740-bcac-4ccd-bfc7-1235c796cc84",
    }

    print("\nPayload enviado:\n", json.dumps(payload, indent=2))

    response = requests.post(API_URL, headers=headers_proactiva, json=payload)

    print("\nRespuesta del servidor:\n")
    print(json.dumps({
        "status_code": response.status_code,
        "ok": response.ok,
        "text": response.text
    }, indent=2))

# =========================================================
# OBTENER PRODUCTOS DE BOXHERO
# =========================================================
def obtener_productos_boxhero():
    response = requests.get(BOXHERO_API_URL, headers=headers_boxhero)
    response.raise_for_status()
    return response.json().get("items", [])

# =========================================================
# PROCESAR PRODUCTOS
# =========================================================
def procesar_producto(producto):
    with conn.cursor() as cursor:

        # Buscar producto existente
        cursor.execute("SELECT * FROM productos WHERE id_boxhero=%s", (producto['id'],))
        existente = cursor.fetchone()

        # =========================
        # PRODUCTO NUEVO
        # =========================
        if not existente:
            cursor.execute("""
                INSERT INTO productos (id_boxhero, nombre, sku, barcode, costo, precio, cantidad_total)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                producto['id'],
                producto.get('name', ''),
                producto.get('sku', ''),
                producto.get('barcode', ''),
                producto.get('cost', 0),
                producto.get('price', 0),
                producto.get('quantity', 0)
            ))
            conn.commit()

            title = f"Creación de producto: {producto.get('name', '')}"
            description = f"""
Producto nuevo detectado en BoxHero

Nombre: {producto.get('name', '')}
SKU: {producto.get('sku', '')}
Código de barras: {producto.get('barcode', '')}
Costo: {producto.get('cost', 0)}
Precio: {producto.get('price', 0)}
Stock total: {producto.get('quantity', 0)}
"""
            crear_device(title, description, federated_code=producto['id'])

        # =========================
        # PRODUCTO EXISTENTE
        # =========================
        else:
            stock_anterior = existente['cantidad_total']
            stock_actual = producto.get('quantity', 0)

            if stock_actual > stock_anterior:
                diferencia = stock_actual - stock_anterior
                crear_device(
                    f"Ingreso de producto: {producto.get('name', '')}",
                    f"Movimiento detectado en inventario\nProducto: {producto.get('name', '')}\nCantidad ingresada: {diferencia}\nStock anterior: {stock_anterior}\nStock actual: {stock_actual}",
                    federated_code=producto['id']
                )
            elif stock_actual < stock_anterior:
                diferencia = stock_anterior - stock_actual
                crear_device(
                    f"Retiro de producto: {producto.get('name', '')}",
                    f"Movimiento detectado en inventario\nProducto: {producto.get('name', '')}\nCantidad retirada: {diferencia}\nStock anterior: {stock_anterior}\nStock actual: {stock_actual}",
                    federated_code=producto['id']
                )

            # Actualizar producto
            cursor.execute("""
                UPDATE productos SET 
                    nombre=%s, sku=%s, barcode=%s, costo=%s, precio=%s, cantidad_total=%s
                WHERE id_boxhero=%s
            """, (
                producto.get('name', ''),
                producto.get('sku', ''),
                producto.get('barcode', ''),
                producto.get('cost', 0),
                producto.get('price', 0),
                stock_actual,
                producto['id']
            ))
            conn.commit()

        # =========================
        # LOCACIONES
        # =========================
        for loc in producto.get("quantities", []):
            # Buscar locación existente en la tabla locations
            cursor.execute("SELECT * FROM locations WHERE boxhero_id=%s", (loc['location_id'],))
            existe_loc = cursor.fetchone()

            if not existe_loc:
                cursor.execute("""
                    INSERT INTO locations (boxhero_id, name, type)
                    VALUES (%s,%s,%s)
                """, (
                    loc['location_id'],
                    loc.get('name', f"Locación {loc['location_id']}"),
                    loc.get('type', 'default')
                ))
                conn.commit()

                crear_device(
                    "Nueva locación detectada",
                    f"Producto: {producto.get('name', '')}\nLocation ID: {loc['location_id']}\nCantidad inicial: {loc.get('quantity', 0)}",
                    federated_code=f"{producto['id']}_{loc['location_id']}"
                )

# =========================================================
# EJECUCIÓN PRINCIPAL
# =========================================================
if __name__ == "__main__":
    productos = obtener_productos_boxhero()
    for producto in productos:
        procesar_producto(producto)
    conn.close()