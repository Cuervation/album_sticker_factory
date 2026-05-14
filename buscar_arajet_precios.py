#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca precios Arajet día por día usando el endpoint /pss/shop/airshop.

Salida Excel:
- Una fila por vuelo/itinerario encontrado.
- Precio = baseAmount.value, tal como indicó el usuario.
- FUEL = suma de charges.items donde code == "FUEL".

Instalación:
    pip install requests pandas openpyxl

Uso básico:
    python buscar_arajet_precios.py --end 2027-03-30

Si Arajet/Cloudflare exige cookies, cargarlas por variable de entorno en PowerShell:
    $env:ARAJET_COOKIE='cookie1=valor; cookie2=valor; cf_clearance=...'
    python buscar_arajet_precios.py --end 2027-03-30
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

BASE_URL = "https://www.arajet.com/pss/shop/airshop"
DEFAULT_PROMO = "VUELARG"
DEFAULT_CURRENCY = "USD"
DEFAULT_POINT_OF_SALE = "US"
DEFAULT_LANGUAGE = "EN"
DEFAULT_WORKERS = 3
DEFAULT_TIMEOUT = 35

# La API usa EZE para Buenos Aires. En la salida mostramos BUE como pediste.
ROUTES: List[Tuple[str, str, str]] = [
    ("BUE - PUJ", "EZE", "PUJ"),
    ("PUJ - BUE", "PUJ", "EZE"),
]


@dataclass(frozen=True)
class Config:
    start: date
    end: date
    promo: str
    currency: str
    point_of_sale: str
    language: str
    workers: int
    timeout: int
    output: str
    cookie: str
    sleep_min: float
    sleep_max: float


def parse_args() -> Config:
    today_plus_2 = date.today() + timedelta(days=2)
    default_output = f"arajet_precios_BUE_PUJ_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    parser = argparse.ArgumentParser(
        description="Recorre fechas de Arajet y exporta BUE-PUJ / PUJ-BUE a Excel."
    )
    parser.add_argument("--start", default=today_plus_2.isoformat(), help="Fecha inicio YYYY-MM-DD. Default: hoy + 2.")
    parser.add_argument("--end", default="2027-03-30", help="Fecha fin YYYY-MM-DD. Default: 2027-03-30.")
    parser.add_argument("--promo", default=DEFAULT_PROMO, help="Código promo. Default: VUELARG. Usar '' para no enviar promo.")
    parser.add_argument("--currency", default=DEFAULT_CURRENCY, help="Moneda. Default: USD.")
    parser.add_argument("--point-of-sale", default=DEFAULT_POINT_OF_SALE, help="Point of sale. Default: US.")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help="Idioma. Default: EN.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Hilos concurrentes por día. Default: 3.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout HTTP por request. Default: 35.")
    parser.add_argument("--output", default=default_output, help="Archivo Excel de salida.")
    parser.add_argument("--cookie", default=os.getenv("ARAJET_COOKIE", ""), help="Cookies opcionales. Mejor usar env ARAJET_COOKIE.")
    parser.add_argument("--sleep-min", type=float, default=0.20, help="Pausa mínima entre requests dentro de un día.")
    parser.add_argument("--sleep-max", type=float, default=0.80, help="Pausa máxima entre requests dentro de un día.")

    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if start > end:
        raise SystemExit(f"La fecha de inicio {start} es mayor que la fecha fin {end}.")
    if args.workers < 1:
        raise SystemExit("--workers debe ser >= 1.")

    return Config(
        start=start,
        end=end,
        promo=args.promo.strip(),
        currency=args.currency.strip().upper(),
        point_of_sale=args.point_of_sale.strip().upper(),
        language=args.language.strip().upper(),
        workers=args.workers,
        timeout=args.timeout,
        output=args.output,
        cookie=args.cookie.strip(),
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
    )


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_payload(day: date, origin: str, destination: str, cfg: Config) -> Dict[str, Any]:
    promo_items = [{"code": cfg.promo}] if cfg.promo else []
    return {
        "passengerTypes": {"items": [{"code": "ADT", "count": 1}]},
        "itineraryShops": {
            "items": [
                {
                    "dateTimeDepart": {"date": day.isoformat()},
                    "locationDepart": {"code": origin},
                    "locationArrive": {"code": destination},
                }
            ]
        },
        "promotions": {"items": promo_items},
        "attributeItems": {"items": [{"typeCode": "language", "code": cfg.language}]},
    }


def build_headers(day: date, origin: str, destination: str, cfg: Config) -> Dict[str, str]:
    referer = (
        "https://www.arajet.com/es-do/booking?"
        f"origin={origin}&destination={destination}&from={day.isoformat()}&to="
        f"&currency={cfg.currency}&promoCode={cfg.promo}&step=1&adt=1&chd=0&inf=0"
    )

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "es-AR,es-419;q=0.9,es;q=0.8,en;q=0.7",
        "content-type": "application/json",
        "language": cfg.language,
        "origin": "https://www.arajet.com",
        "priority": "u=1, i",
        "referer": referer,
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": (
            "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Mobile Safari/537.36"
        ),
        "x-correlation-id": str(uuid.uuid4()),
        "x-currency": cfg.currency,
        "x-point-of-sale": cfg.point_of_sale,
        "x-session-id": str(uuid.uuid4()),
    }

    # No hardcodear cookies en el script. Pasarlas por env var si el sitio las pide.
    if cfg.cookie:
        headers["cookie"] = cfg.cookie

    return headers


def safe_get(obj: Dict[str, Any], path: Iterable[str], default: Any = None) -> Any:
    current: Any = obj
    for part in path:
        if not isinstance(current, dict):
            return default
        current = current.get(part)
    return current if current is not None else default


def extract_fuel(price: Dict[str, Any]) -> float:
    charges = safe_get(price, ["charges", "items"], []) or []
    fuel_values = [float(ch.get("value") or 0) for ch in charges if ch.get("code") == "FUEL"]
    return round(sum(fuel_values), 2)


def promo_status(price: Dict[str, Any]) -> str:
    messages = safe_get(price, ["baseAmount", "adjustment", "messages", "items"], []) or []
    if not messages:
        return ""
    return " | ".join(
        f"{m.get('code', '')}:{m.get('description', '')}".strip(":")
        for m in messages
    )


def all_price_options(itinerary_item: Dict[str, Any]) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    fare_products = safe_get(itinerary_item, ["fareProducts", "items"], []) or []
    for fare_product in fare_products:
        for price in safe_get(fare_product, ["prices", "items"], []) or []:
            base_value = safe_get(price, ["baseAmount", "value"])
            if base_value is None:
                continue
            options.append(
                {
                    "fare_product_code": fare_product.get("code"),
                    "fare_product_type": fare_product.get("typeCode"),
                    "fare_product_key": fare_product.get("key"),
                    "fare_code": price.get("code"),
                    "fare_type": price.get("typeCode"),
                    "precio": float(base_value),  # baseAmount.value, como pediste
                    "fuel": extract_fuel(price),
                    "total_amount": safe_get(price, ["totalAmount", "value"]),
                    "currency": safe_get(price, ["baseAmount", "currency", "code"], ""),
                    "promo_status": promo_status(price),
                }
            )
    return options


def first_flight_value(itinerary_item: Dict[str, Any], field: str, default: str = "") -> str:
    flights = safe_get(itinerary_item, ["flights", "items"], []) or []
    if not flights:
        return default
    return str(flights[0].get(field, default) or default)


def flight_numbers(itinerary_item: Dict[str, Any]) -> str:
    flights = safe_get(itinerary_item, ["flights", "items"], []) or []
    nums = []
    for fl in flights:
        airline = safe_get(fl, ["airlineMarketing", "code"], "") or safe_get(fl, ["airlineOperating", "code"], "")
        num = fl.get("flightNumber", "")
        if airline or num:
            nums.append(f"{airline}{num}".strip())
    return " / ".join(nums)


def parse_airshop_response(
    data: Dict[str, Any],
    route_label: str,
    origin: str,
    destination: str,
    requested_day: date,
) -> List[Dict[str, Any]]:
    content = data.get("content", data)
    items = safe_get(content, ["flightSegmentItineraries", "items"], []) or []

    if not items:
        return [
            {
                "Ruta": route_label,
                "Origen_API": origin,
                "Destino_API": destination,
                "Fecha_Buscada": requested_day.isoformat(),
                "Fecha_Salida": requested_day.isoformat(),
                "Hora_Salida": "",
                "Precio": None,
                "FUEL": None,
                "TotalAmount_API": None,
                "Moneda": "",
                "Vuelo": "",
                "Estado": "SIN_DISPONIBILIDAD",
                "Detalle": "No se encontraron flightSegmentItineraries.items",
            }
        ]

    rows: List[Dict[str, Any]] = []
    for itinerary_item in items:
        options = all_price_options(itinerary_item)
        if not options:
            best = {
                "precio": None,
                "fuel": None,
                "total_amount": None,
                "currency": "",
                "fare_code": "",
                "fare_type": "",
                "fare_product_type": "",
                "promo_status": "",
            }
        else:
            # Para cada vuelo/itinerario, nos quedamos con la tarifa más barata.
            best = min(options, key=lambda x: x["precio"])

        itinerary = itinerary_item.get("itinerary", {}) or {}
        dt_depart = itinerary.get("dateTimeDepart", {}) or {}
        dt_arrive = itinerary.get("dateTimeArrive", {}) or {}
        loc_depart = itinerary.get("locationDepart", {}) or {}
        loc_arrive = itinerary.get("locationArrive", {}) or {}

        # Fallback por si el nodo itinerary no viniera completo.
        if not dt_depart:
            dt_depart = safe_get(itinerary_item, ["flights", "items"], [{}])[0].get("scheduledDepart", {})
        if not dt_arrive:
            dt_arrive = safe_get(itinerary_item, ["flights", "items"], [{}])[0].get("scheduledArrive", {})

        travel_times = safe_get(itinerary_item, ["flights", "items"], []) or []
        duration = ""
        if travel_times:
            duration = safe_get(travel_times[0], ["travelTimes", "items"], [{}])[0].get("duration", "")

        rows.append(
            {
                "Ruta": route_label,
                "Origen_API": origin,
                "Destino_API": destination,
                "Ciudad_Salida": loc_depart.get("cityName", ""),
                "Ciudad_Llegada": loc_arrive.get("cityName", ""),
                "Fecha_Buscada": requested_day.isoformat(),
                "Fecha_Salida": dt_depart.get("date", requested_day.isoformat()),
                "Hora_Salida": dt_depart.get("time", ""),
                "Fecha_Llegada": dt_arrive.get("date", ""),
                "Hora_Llegada": dt_arrive.get("time", ""),
                "Precio": best.get("precio"),
                "FUEL": best.get("fuel"),
                "TotalAmount_API": best.get("total_amount"),
                "Moneda": best.get("currency"),
                "Vuelo": flight_numbers(itinerary_item),
                "Duracion": duration,
                "FareCode": best.get("fare_code"),
                "FareType": best.get("fare_type"),
                "FareProductType": best.get("fare_product_type"),
                "PromoStatus": best.get("promo_status"),
                "Estado": "OK",
                "Detalle": "",
            }
        )

    return rows


def post_airshop(
    session: requests.Session,
    cfg: Config,
    day: date,
    route_label: str,
    origin: str,
    destination: str,
    max_retries: int = 3,
) -> List[Dict[str, Any]]:
    payload = build_payload(day, origin, destination, cfg)

    for attempt in range(1, max_retries + 1):
        headers = build_headers(day, origin, destination, cfg)
        try:
            response = session.post(
                BASE_URL,
                headers=headers,
                json=payload,
                timeout=cfg.timeout,
            )

            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(2 * attempt, 8) + random.random())
                continue

            if response.status_code != 200:
                return [
                    error_row(
                        route_label,
                        origin,
                        destination,
                        day,
                        f"HTTP_{response.status_code}",
                        response.text[:500],
                    )
                ]

            try:
                data = response.json()
            except ValueError:
                return [
                    error_row(
                        route_label,
                        origin,
                        destination,
                        day,
                        "JSON_INVALIDO",
                        response.text[:500],
                    )
                ]

            return parse_airshop_response(data, route_label, origin, destination, day)

        except requests.RequestException as exc:
            if attempt == max_retries:
                return [error_row(route_label, origin, destination, day, "REQUEST_ERROR", str(exc))]
            time.sleep(min(2 * attempt, 8) + random.random())

    return [error_row(route_label, origin, destination, day, "ERROR_DESCONOCIDO", "Sin respuesta")]


def error_row(route_label: str, origin: str, destination: str, day: date, estado: str, detalle: str) -> Dict[str, Any]:
    return {
        "Ruta": route_label,
        "Origen_API": origin,
        "Destino_API": destination,
        "Fecha_Buscada": day.isoformat(),
        "Fecha_Salida": day.isoformat(),
        "Hora_Salida": "",
        "Precio": None,
        "FUEL": None,
        "TotalAmount_API": None,
        "Moneda": "",
        "Vuelo": "",
        "Estado": estado,
        "Detalle": detalle,
    }


def process_day(day: date, cfg: Config) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with requests.Session() as session:
        for route_label, origin, destination in ROUTES:
            rows.extend(post_airshop(session, cfg, day, route_label, origin, destination))
            time.sleep(random.uniform(cfg.sleep_min, cfg.sleep_max))
    return rows


def autosize_excel_columns(path: str) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(path)
    for ws in wb.worksheets:
        for column_cells in ws.columns:
            max_length = 0
            col_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = cell.value
                if value is None:
                    continue
                max_length = max(max_length, len(str(value)))
            ws.column_dimensions[col_letter].width = min(max(max_length + 2, 10), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def write_excel(rows: List[Dict[str, Any]], output: str) -> None:
    df = pd.DataFrame(rows)
    if not df.empty:
        sort_cols = [c for c in ["Ruta", "Fecha_Salida", "Hora_Salida", "Precio"] if c in df.columns]
        df = df.sort_values(sort_cols, na_position="last")

    ok = df[df["Estado"].eq("OK")].copy() if "Estado" in df.columns else df.copy()
    errores = df[~df["Estado"].eq("OK")].copy() if "Estado" in df.columns else pd.DataFrame()

    # Mínimo por ruta y fecha, manteniendo hora/vuelo de la opción más barata.
    if not ok.empty and "Precio" in ok.columns:
        idx = ok.groupby(["Ruta", "Fecha_Salida"], dropna=False)["Precio"].idxmin()
        minimos = ok.loc[idx].sort_values(["Ruta", "Fecha_Salida", "Precio"])
    else:
        minimos = pd.DataFrame()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="todos_los_vuelos", index=False)
        minimos.to_excel(writer, sheet_name="minimo_por_dia", index=False)
        errores.to_excel(writer, sheet_name="errores_sin_disp", index=False)

    autosize_excel_columns(output)


def main() -> int:
    cfg = parse_args()
    days = list(daterange(cfg.start, cfg.end))

    print(f"Fechas: {cfg.start} a {cfg.end} ({len(days)} días)")
    print(f"Rutas: {', '.join(route[0] for route in ROUTES)}")
    print(f"Hilos: {cfg.workers}")
    print(f"Salida: {cfg.output}")
    if not cfg.cookie:
        print("Aviso: no se pasaron cookies. Si devuelve 403, usar ARAJET_COOKIE con cookies vigentes del navegador.")

    all_rows: List[Dict[str, Any]] = []
    done = 0

    with ThreadPoolExecutor(max_workers=cfg.workers) as executor:
        futures = {executor.submit(process_day, day, cfg): day for day in days}
        for future in as_completed(futures):
            day = futures[future]
            try:
                rows = future.result()
            except Exception as exc:  # protección extra para no perder todo el lote
                rows = [error_row("AMBAS", "", "", day, "EXCEPTION", str(exc))]
            all_rows.extend(rows)
            done += 1
            print(f"[{done}/{len(days)}] {day} -> {len(rows)} filas")

    write_excel(all_rows, cfg.output)
    print(f"Listo. Excel generado: {cfg.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
