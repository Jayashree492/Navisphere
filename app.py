import os
import requests
from urllib.parse import quote_plus

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE, override=False)

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
SERPAPI_URL = "https://serpapi.com/search.json"

openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        openai_client = None


def get_serpapi_key():
    """Read the key at request time so .env/environment changes are respected."""
    load_dotenv(ENV_FILE, override=False)
    return os.getenv("SERPAPI_KEY", "").strip()


def serpapi_search(params):
    """Call SerpApi. Returns a dict and never crashes the Flask route."""
    serpapi_key = get_serpapi_key()
    if not serpapi_key:
        return {"error": "SERPAPI_KEY_NOT_CONFIGURED"}

    request_params = dict(params)
    request_params["api_key"] = serpapi_key
    request_params["output"] = "json"

    try:
        response = requests.get(SERPAPI_URL, params=request_params, timeout=25)
        try:
            data = response.json()
        except ValueError:
            return {"error": f"SerpApi returned HTTP {response.status_code} instead of JSON."}

        if response.status_code >= 400:
            return {"error": data.get("error") or f"SerpApi HTTP {response.status_code}."}
        if data.get("error"):
            return {"error": data["error"]}
        return data
    except requests.RequestException as exc:
        return {"error": f"SerpApi connection failed: {exc}"}


def geocode_location(location):
    """Geocode a typed city/address using OpenStreetMap Nominatim."""
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "NaviSphereAI/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            return None
        return float(items[0]["lat"]), float(items[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def osm_search(query, lat=None, lng=None, location=None, limit=20):
    """Fallback search using OpenStreetMap Overpass when SerpApi is unavailable.

    This keeps Explore usable without exposing or requiring a secret API key.
    """
    if lat is None or lng is None:
        if not location:
            return {"error": "LOCATION_REQUIRED"}
        coords = geocode_location(location)
        if not coords:
            return {"error": "Could not find that location."}
        lat, lng = coords

    q = (query or "restaurants").lower()
    if any(x in q for x in ["hospital", "hospitals"]):
        tags = [('amenity', 'hospital')]
    elif any(x in q for x in ["pharmacy", "pharmacies", "chemist"]):
        tags = [('amenity', 'pharmacy')]
    elif "atm" in q or "cash" in q:
        tags = [('amenity', 'atm')]
    elif any(x in q for x in ["grocery", "groceries", "supermarket"]):
        tags = [('shop', 'supermarket'), ('shop', 'convenience')]
    elif any(x in q for x in ["hotel", "hotels"]):
        tags = [('tourism', 'hotel')]
    else:
        # Food and general nearby searches.
        tags = [('amenity', 'restaurant'), ('amenity', 'cafe'), ('amenity', 'fast_food')]

    clauses = []
    for key, value in tags:
        clauses.append(f'nwr["{key}"="{value}"](around:6000,{lat},{lng});')
    overpass_query = "[out:json][timeout:20];(" + "".join(clauses) + ");out center tags;"

    try:
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=overpass_query,
            headers={"User-Agent": "NaviSphereAI/1.0"},
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json().get("elements", [])
    except (requests.RequestException, ValueError):
        return {"error": "Live place search is temporarily unavailable. Please try again."}

    results = []
    seen = set()
    for element in raw:
        tags_data = element.get("tags") or {}
        title = tags_data.get("name")
        if not title:
            continue
        key = (title.lower(), tags_data.get("addr:street", "").lower())
        if key in seen:
            continue
        seen.add(key)

        if "lat" in element and "lon" in element:
            place_lat, place_lng = element["lat"], element["lon"]
        else:
            center = element.get("center") or {}
            place_lat, place_lng = center.get("lat"), center.get("lon")
        if place_lat is None or place_lng is None:
            continue

        address_parts = [
            tags_data.get("addr:housenumber"),
            tags_data.get("addr:street"),
            tags_data.get("addr:city"),
        ]
        address = ", ".join(x for x in address_parts if x)
        website = tags_data.get("website") or tags_data.get("contact:website")
        phone = tags_data.get("phone") or tags_data.get("contact:phone")
        opening = tags_data.get("opening_hours")

        results.append({
            "title": title,
            "rating": None,
            "reviews": None,
            "price": None,
            "type": tags_data.get("amenity") or tags_data.get("shop") or tags_data.get("tourism") or "Nearby place",
            "address": address or "Address not listed",
            "phone": phone,
            "open_state": f"Hours: {opening}" if opening else "Opening hours unavailable",
            "hours": opening,
            "description": None,
            "thumbnail": None,
            "data_id": None,
            "latitude": place_lat,
            "longitude": place_lng,
            "website": website,
            "directions": f"https://www.google.com/maps/dir/?api=1&destination={place_lat},{place_lng}",
            "street_view_url": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={place_lat}%2C{place_lng}",
            "satellite_url": f"https://www.google.com/maps/@?api=1&map_action=map&center={place_lat}%2C{place_lng}&zoom=18&basemap=satellite",
        })
        if len(results) >= limit:
            break

    return {
        "local_results": results,
        "coordinates": {"latitude": lat, "longitude": lng},
        "fallback": True,
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "app": "NaviSphere AI",
        "backend": True,
        "serpapi_configured": bool(get_serpapi_key()),
        "osm_fallback": True,
    })


@app.route("/api/search")
def search_places():
    query = request.args.get("q", "restaurants").strip() or "restaurants"
    location = request.args.get("location", "").strip()
    lat_raw = request.args.get("lat", "").strip()
    lng_raw = request.args.get("lng", "").strip()
    budget_raw = request.args.get("budget", "").strip()
    open_now = request.args.get("open_now", "0") == "1"

    lat = lng = None
    has_coordinates = bool(lat_raw and lng_raw)
    if has_coordinates:
        try:
            lat, lng = float(lat_raw), float(lng_raw)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid current-location coordinates."}), 400

    if not has_coordinates and not location:
        return jsonify({"error": "Please enter a city/location or allow current-location access."}), 400

    budget = None
    if budget_raw:
        try:
            budget = float(budget_raw)
            if budget <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Budget must be a positive number, for example 300 or 500."}), 400

    q_lower = query.lower()
    category_map = {
        "hospital": "hospitals", "pharmacy": "pharmacies", "chemist": "pharmacies",
        "atm": "ATMs", "grocery": "grocery stores", "supermarket": "supermarkets", "hotel": "hotels",
    }
    search_query = query
    for key, value in category_map.items():
        if key in q_lower:
            search_query = value
            break

    is_food = any(word in q_lower for word in [
        "food", "restaurant", "restaurants", "cafe", "café", "vegan", "vegetarian", "halal",
        "pizza", "burger", "breakfast", "lunch", "dinner"
    ])
    if is_food and budget is not None:
        search_query += f" under Rs {int(budget) if budget.is_integer() else budget:g} per person"

    params = {
        "engine": "google_maps", "type": "search", "q": search_query, "hl": "en", "gl": "in"
    }
    if open_now:
        params["open_state"] = "now"
    if has_coordinates:
        params["ll"] = f"@{lat:.7f},{lng:.7f},16z"
    else:
        params["location"] = location
        params["z"] = "14"

    data = serpapi_search(params)
    used_fallback = False
    if data.get("error"):
        # SerpApi is optional for the local demo. Fall back to free OSM data.
        data = osm_search(search_query, lat=lat, lng=lng, location=location)
        used_fallback = True
        if data.get("error"):
            original_error = data.get("error")
            return jsonify({
                "error": original_error,
                "serpapi_used": bool(get_serpapi_key()),
                "fallback": True,
            }), 502

    places = []
    for item in (data.get("local_results") or [])[:20]:
        coordinates = item.get("gps_coordinates") or {}
        links = item.get("links") or {}
        place_lat = coordinates.get("latitude", item.get("latitude"))
        place_lng = coordinates.get("longitude", item.get("longitude"))

        street_view_url = item.get("street_view_url")
        satellite_url = item.get("satellite_url")
        if place_lat is not None and place_lng is not None:
            street_view_url = street_view_url or f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={place_lat}%2C{place_lng}&heading=0&pitch=0&fov=85"
            satellite_url = satellite_url or f"https://www.google.com/maps/@?api=1&map_action=map&center={place_lat}%2C{place_lng}&zoom=18&basemap=satellite"

        places.append({
            "title": item.get("title"), "rating": item.get("rating"), "reviews": item.get("reviews"),
            "price": item.get("price"), "type": item.get("type"), "address": item.get("address"),
            "phone": item.get("phone"), "open_state": item.get("open_state"), "hours": item.get("hours"),
            "description": item.get("description"), "thumbnail": item.get("thumbnail"),
            "data_id": item.get("data_id"), "latitude": place_lat, "longitude": place_lng,
            "website": links.get("website") or item.get("website"),
            "directions": links.get("directions") or item.get("directions") or (f"https://www.google.com/maps/dir/?api=1&destination={place_lat},{place_lng}" if place_lat is not None else None),
            "street_view_url": street_view_url, "satellite_url": satellite_url,
        })

    coords = data.get("coordinates")
    if not coords and has_coordinates:
        coords = {"latitude": lat, "longitude": lng}

    return jsonify({
        "query": query, "search_query": search_query, "location": location,
        "coordinates": coords, "budget": budget, "open_now": open_now,
        "is_food": is_food, "results": places, "fallback": used_fallback,
        "maps_url": (data.get("search_metadata") or {}).get("google_maps_url"),
    })


@app.route("/api/reviews")
def reviews():
    data_id = request.args.get("data_id", "").strip()
    if not data_id:
        return jsonify({"error": "Reviews are available for SerpApi results only."}), 400
    data = serpapi_search({"engine": "google_maps_reviews", "data_id": data_id, "hl": "en", "num": 8})
    if data.get("error"):
        return jsonify({"error": "Live reviews require a valid SerpApi key."}), 502
    return jsonify({"reviews": [{"rating": r.get("rating"), "date": r.get("date"), "snippet": r.get("snippet")} for r in data.get("reviews", [])]})


@app.route("/api/directions")
def directions():
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    if not start or not end:
        return jsonify({"error": "Start and destination are required."}), 400

    data = serpapi_search({"engine": "google_maps_directions", "start_addr": start, "end_addr": end, "hl": "en", "gl": "in"})
    if not data.get("error"):
        routes = []
        for route in data.get("directions", []):
            routes.append({
                "title": route.get("title"), "distance": route.get("distance"), "duration": route.get("duration"),
                "price": route.get("price"), "formatted_distance": route.get("formatted_distance"),
                "formatted_duration": route.get("formatted_duration"),
            })
        return jsonify({"routes": routes})

    # Free fallback: geocode both ends and use OSRM public routing.
    start_coords = geocode_location(start)
    end_coords = geocode_location(end)
    if not start_coords or not end_coords:
        return jsonify({"error": "Could not locate one of the route points."}), 502
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        r = requests.get(url, params={"overview": "false"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        route = (data.get("routes") or [None])[0]
        if not route:
            return jsonify({"routes": []})
        km = route["distance"] / 1000
        mins = route["duration"] / 60
        return jsonify({"routes": [{
            "title": "Driving route", "distance": f"{km:.1f} km", "duration": f"{mins:.0f} min",
            "price": "", "formatted_distance": f"{km:.1f} km", "formatted_duration": f"{mins:.0f} min"
        }]})
    except requests.RequestException:
        return jsonify({"error": "Route service is temporarily unavailable."}), 502


@app.route("/api/triptwin", methods=["POST"])
def triptwin():
    data = request.get_json(silent=True) or {}
    try:
        budget = float(data.get("budget", 2000)); spending = float(data.get("spending", 1400))
        travel_time = float(data.get("travel_time", 42)); schedule_gap = float(data.get("schedule_gap", 15))
    except (TypeError, ValueError):
        return jsonify({"error": "Trip values must be numbers."}), 400
    checks = {"Budget": spending <= budget, "Travel Time": travel_time <= 90, "Schedule Buffer": schedule_gap >= 10}
    return jsonify({"checks": checks, "status": "Plan is ready to test" if all(checks.values()) else "Plan needs adjustment"})


@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json(silent=True) or {}
    scenario = data.get("scenario", "Reduce Budget")
    try:
        budget = float(data.get("budget", 15000))
    except (TypeError, ValueError):
        return jsonify({"error": "Budget must be a number."}), 400
    result = {"scenario": scenario, "original": budget, "simulated": budget, "walking": "6.4 km", "places": 7, "changes": []}
    if scenario == "Reduce Budget":
        result.update(simulated=budget-3000, walking="3.8 km", places=6, changes=["Replace two private cab journeys with public transport.", "Choose a nearby lower-cost attraction.", "Move the food stop closer to the route."])
    elif scenario == "Remove Taxi":
        result.update(simulated=budget-1800, walking="5.1 km", changes=["Replace taxi journeys with public transport.", "Move one stop closer to a metro corridor."])
    elif scenario == "Less Walking":
        result.update(simulated=budget+500, walking="2.0 km", changes=["Prioritize places close to stations.", "Use one short paid transfer."])
    elif scenario == "Restaurant Closed":
        result["changes"] = ["Find another matching restaurant.", "Recalculate the evening route."]
    return jsonify(result)


@app.route("/api/ai-guide", methods=["POST"])
def ai_guide():
    if not openai_client:
        return jsonify({"error": "OPENAI_API_KEY is not configured. Add it to .env to enable NaviSphere AI chat."}), 503
    data = request.get_json(silent=True) or {}
    user_message = str(data.get("message", "")).strip()
    if not user_message:
        return jsonify({"error": "Please enter a message."}), 400
    system_prompt = """You are NaviSphere AI, a practical local-discovery assistant. Be concise. Never invent businesses, addresses, prices, routes, opening hours, ratings, or reviews. Help users understand options."""
    try:
        response = openai_client.responses.create(model="gpt-5.6-luna", instructions=system_prompt, input=user_message)
        return jsonify({"success": True, "reply": response.output_text})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 502


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
