import os
import math
import requests

from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# =========================================================
# API KEY
# =========================================================

SERPAPI_KEY = os.getenv("SERPAPI_KEY")


# =========================================================
# TRANSPORT SETTINGS
# These are estimates, not live fares.
# =========================================================

TRANSPORTS = {
    "walking": {
        "label": "Walking",
        "icon": "🚶",
        "speed": 5,
        "base_cost": 0,
        "cost_per_km": 0
    },

    "bicycle": {
        "label": "Bicycle",
        "icon": "🚲",
        "speed": 15,
        "base_cost": 0,
        "cost_per_km": 0
    },

    "bike": {
        "label": "Bike",
        "icon": "🏍️",
        "speed": 35,
        "base_cost": 10,
        "cost_per_km": 3
    },

    "auto": {
        "label": "Auto",
        "icon": "🛺",
        "speed": 25,
        "base_cost": 30,
        "cost_per_km": 12
    },

    "taxi": {
        "label": "Taxi / Cab",
        "icon": "🚕",
        "speed": 30,
        "base_cost": 50,
        "cost_per_km": 18
    },

    "car": {
        "label": "Car",
        "icon": "🚗",
        "speed": 30,
        "base_cost": 0,
        "cost_per_km": 8
    },

    "bus": {
        "label": "Bus",
        "icon": "🚌",
        "speed": 22,
        "base_cost": 10,
        "cost_per_km": 2
    },

    "metro": {
        "label": "Train / Metro",
        "icon": "🚆",
        "speed": 35,
        "base_cost": 10,
        "cost_per_km": 2
    },

    "van": {
        "label": "Van",
        "icon": "🚐",
        "speed": 28,
        "base_cost": 40,
        "cost_per_km": 12
    }
}


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/api/health")
def health():

    return jsonify({
        "success": True,
        "message": "NaviSphere AI backend is running",
        "serpapi_configured": bool(SERPAPI_KEY),
        "openai": "disabled_optional"
    })


# =========================================================
# GEOCODING
# OpenStreetMap Nominatim
# =========================================================

def geocode_location(location):

    if not location:
        return None

    try:

        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": location,
                "format": "json",
                "limit": 1
            },
            headers={
                "User-Agent": "NaviSphereAI/1.0"
            },
            timeout=10
        )

        response.raise_for_status()

        results = response.json()

        if not results:
            return None

        return {
            "lat": float(results[0]["lat"]),
            "lng": float(results[0]["lon"]),
            "display_name": results[0].get(
                "display_name",
                location
            )
        }

    except Exception:

        return None


# =========================================================
# HAVERSINE DISTANCE
# =========================================================

def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2
):

    earth_radius = 6371

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)

    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        +
        math.cos(lat1)
        *
        math.cos(lat2)
        *
        math.sin(dlon / 2) ** 2
    )

    return (
        earth_radius
        *
        2
        *
        math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )


# =========================================================
# REAL ROAD ROUTE
# OSRM
# =========================================================

def get_driving_route(start, end):

    url = (
        "https://router.project-osrm.org/"
        "route/v1/driving/"
        f"{start['lng']},{start['lat']};"
        f"{end['lng']},{end['lat']}"
    )

    try:

        response = requests.get(
            url,
            params={
                "alternatives": "true",
                "steps": "false",
                "overview": "false"
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        if data.get("code") != "Ok":
            return []

        return data.get("routes", [])

    except Exception:

        return []


# =========================================================
# TRANSPORT CALCULATION
# =========================================================

def calculate_transport(
    distance_km,
    mode,
    driving_minutes=None
):

    transport = TRANSPORTS.get(mode)

    if not transport:

        mode = "taxi"

        transport = TRANSPORTS[mode]

    road_modes = {
        "bike",
        "auto",
        "taxi",
        "car",
        "bus",
        "van"
    }

    if (
        mode in road_modes
        and driving_minutes is not None
    ):

        duration_minutes = max(
            1,
            round(driving_minutes)
        )

    else:

        duration_minutes = max(
            1,
            round(
                (distance_km / transport["speed"])
                * 60
            )
        )

    cost = (
        transport["base_cost"]
        +
        distance_km
        *
        transport["cost_per_km"]
    )

    return {

        "mode": mode,

        "label": transport["label"],

        "icon": transport["icon"],

        "distance_km": round(
            distance_km,
            2
        ),

        "duration_minutes":
            duration_minutes,

        "estimated_cost":
            round(cost)
    }


# =========================================================
# SMART JOURNEY PLANNER
# =========================================================

@app.route(
    "/api/journey-plan",
    methods=["POST"]
)
def journey_plan():

    data = request.get_json(
        silent=True
    ) or {}

    from_location = str(
        data.get("from", "")
    ).strip()

    to_location = str(
        data.get("to", "")
    ).strip()

    mode = str(
        data.get("mode", "walking")
    ).strip().lower()

    reach_by = data.get("reach_by")

    try:

        budget = float(
            data.get("budget", 0)
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "success": False,
            "error": "Please enter a valid budget."
        }), 400


    # -----------------------------
    # VALIDATION
    # -----------------------------

    if not from_location:

        return jsonify({
            "success": False,
            "error": "Please enter your starting location."
        }), 400


    if not to_location:

        return jsonify({
            "success": False,
            "error": "Please enter your destination."
        }), 400


    if (
        not math.isfinite(budget)
        or budget < 0
    ):

        return jsonify({
            "success": False,
            "error": "Please enter a valid budget."
        }), 400


    if mode not in TRANSPORTS:

        return jsonify({
            "success": False,
            "error": "Invalid transport mode."
        }), 400


    # -----------------------------
    # GEOCODE START
    # -----------------------------

    start = geocode_location(
        from_location
    )

    if not start:

        return jsonify({
            "success": False,
            "error":
                f"Could not find '{from_location}'."
        }), 400


    # -----------------------------
    # GEOCODE DESTINATION
    # -----------------------------

    destination = geocode_location(
        to_location
    )

    if not destination:

        return jsonify({
            "success": False,
            "error":
                f"Could not find '{to_location}'."
        }), 400


    # -----------------------------
    # ROAD ROUTE
    # -----------------------------

    routes = get_driving_route(
        start,
        destination
    )


    if routes:

        road_distance_km = (
            routes[0]["distance"]
            / 1000
        )

        road_duration_minutes = (
            routes[0]["duration"]
            / 60
        )

    else:

        straight_distance = (
            haversine_distance(
                start["lat"],
                start["lng"],
                destination["lat"],
                destination["lng"]
            )
        )

        road_distance_km = max(
            0.1,
            straight_distance * 1.25
        )

        road_duration_minutes = None


    # -----------------------------
    # SELECTED TRANSPORT
    # -----------------------------

    selected = calculate_transport(
        road_distance_km,
        mode,
        road_duration_minutes
    )


    # -----------------------------
    # BUDGET
    # -----------------------------

    remaining = round(
        budget
        -
        selected["estimated_cost"]
    )

    within_budget = (
        remaining >= 0
    )


    if within_budget:

        budget_message = (
            "Your journey fits within "
            "your budget. "
            f"You have ₹{remaining:,} "
            "remaining."
        )

    else:

        budget_message = (
            f"This journey is "
            f"₹{abs(remaining):,} "
            "over your budget. "
            "Try a lower-cost transport "
            "option below."
        )


    # -----------------------------
    # COMPARE TRANSPORT
    # -----------------------------

    comparison = []

    for transport_mode in TRANSPORTS:

        item = calculate_transport(
            road_distance_km,
            transport_mode,
            road_duration_minutes
        )

        item["within_budget"] = (
            item["estimated_cost"]
            <= budget
        )

        comparison.append(item)


    # -----------------------------
    # ALTERNATIVES
    # -----------------------------

    alternatives = [

        item

        for item in comparison

        if (
            item["mode"] != mode
            and
            item["within_budget"]
        )

    ]

    alternatives.sort(
        key=lambda x:
            x["estimated_cost"]
    )


    # -----------------------------
    # RESPONSE
    # -----------------------------

    return jsonify({

        "success": True,

        "from": from_location,

        "to": to_location,

        "mode":
            selected["mode"],

        "mode_label":
            selected["label"],

        "distance_km":
            selected["distance_km"],

        "duration_minutes":
            selected["duration_minutes"],

        "estimated_cost":
            selected["estimated_cost"],

        "budget":
            round(budget),

        "remaining":
            remaining,

        "within_budget":
            within_budget,

        "budget_message":
            budget_message,

        "comparison":
            comparison,

        "alternatives":
            alternatives,

        "reach_by":
            reach_by,

        "note":
            "Distance and travel time use "
            "a real road route when available. "
            "Transport costs are estimates and "
            "actual fares may vary."
    })


# =========================================================
# COMPARE YOUR JOURNEY
# =========================================================

@app.route(
    "/api/directions",
    methods=["GET"]
)
def directions():

    start_text = request.args.get(
        "start",
        ""
    ).strip()

    end_text = request.args.get(
        "end",
        ""
    ).strip()


    if not start_text or not end_text:

        return jsonify({
            "success": False,
            "error":
                "Please enter both starting "
                "point and destination."
        }), 400


    start = geocode_location(
        start_text
    )

    end = geocode_location(
        end_text
    )


    if not start:

        return jsonify({
            "success": False,
            "error":
                f"Could not find '{start_text}'."
        }), 400


    if not end:

        return jsonify({
            "success": False,
            "error":
                f"Could not find '{end_text}'."
        }), 400


    routes = get_driving_route(
        start,
        end
    )


    if not routes:

        return jsonify({
            "success": False,
            "error":
                "No road route could be "
                "found for these locations."
        }), 404


    results = []


    for index, route in enumerate(
        routes[:3],
        start=1
    ):

        distance_km = (
            route["distance"]
            / 1000
        )

        duration_minutes = round(
            route["duration"]
            / 60
        )

        hours = (
            duration_minutes
            // 60
        )

        minutes = (
            duration_minutes
            % 60
        )


        if hours:

            formatted_duration = (
                f"{hours} hr "
                f"{minutes} min"
            )

        else:

            formatted_duration = (
                f"{minutes} min"
            )


        estimated_drive_cost = round(
            distance_km * 8
        )


        results.append({

            "title":
                (
                    "Recommended Route"
                    if index == 1
                    else
                    f"Alternative Route "
                    f"{index - 1}"
                ),

            "distance":
                f"{distance_km:.2f} km",

            "formatted_distance":
                f"{distance_km:.2f} km",

            "duration":
                formatted_duration,

            "formatted_duration":
                formatted_duration,

            "price":
                (
                    "Est. driving cost "
                    f"₹{estimated_drive_cost:,}"
                ),

            "estimated_cost":
                estimated_drive_cost
        })


    return jsonify({
        "success": True,
        "routes": results
    })


# =========================================================
# SERPAPI LOCAL SEARCH
# =========================================================

@app.route(
    "/api/search",
    methods=["GET"]
)
def search_places():

    query = request.args.get(
        "q",
        ""
    ).strip()

    location = request.args.get(
        "location",
        ""
    ).strip()

    lat = request.args.get(
        "lat"
    )

    lng = request.args.get(
        "lng"
    )

    open_now = request.args.get(
        "open_now",
        "false"
    )


    if not query:

        query = "places near me"


    lower_query = query.lower()


    # Taxi / Cab
    is_taxi_search = (
        "taxi" in lower_query
        or
        "cab" in lower_query
    )


    if is_taxi_search:

        query = "taxi near me"


    if not SERPAPI_KEY:

        return jsonify({
            "success": False,
            "error":
                "SerpApi key is not configured."
        }), 500


    params = {

        "engine":
            "google_maps",

        "type":
            "search",

        "q":
            query,

        "api_key":
            SERPAPI_KEY
    }


    # -----------------------------
    # CURRENT LOCATION
    # -----------------------------

    if lat and lng:

        try:

            lat_value = float(lat)

            lng_value = float(lng)


            params["ll"] = (
                f"@{lat_value},"
                f"{lng_value},15z"
            )


            # Important for nearby taxi
            if is_taxi_search:

                params["nearby"] = "true"


        except ValueError:

            return jsonify({
                "success": False,
                "error":
                    "Invalid location coordinates."
            }), 400


    elif location:

        params["q"] = (
            f"{query} near {location}"
        )


    # -----------------------------
    # OPEN NOW
    # -----------------------------

    if str(
        open_now
    ).lower() in (
        "true",
        "1"
    ):

        params["open_state"] = "open"


    try:

        response = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()


        results = []


        for place in data.get(
            "local_results",
            []
        ):

            gps = (
                place.get(
                    "gps_coordinates"
                )
                or {}
            )


            latitude = gps.get(
                "latitude"
            )

            longitude = gps.get(
                "longitude"
            )


            results.append({

                "title":
                    place.get(
                        "title",
                        ""
                    ),

                "rating":
                    place.get(
                        "rating"
                    ),

                "reviews":
                    place.get(
                        "reviews"
                    ),

                "price":
                    place.get(
                        "price"
                    ),

                "type":
                    place.get(
                        "type"
                    ),

                "address":
                    place.get(
                        "address"
                    ),

                "phone":
                    place.get(
                        "phone"
                    ),

                "open_state":
                    place.get(
                        "open_state"
                    ),

                "hours":
                    place.get(
                        "hours"
                    ),

                "thumbnail":
                    place.get(
                        "thumbnail"
                    ),

                "data_id":
                    place.get(
                        "data_id"
                    ),

                "latitude":
                    latitude,

                "longitude":
                    longitude,

                "website":
                    place.get(
                        "website"
                    ),

                "directions":
                    place.get(
                        "directions"
                    ),

                "street_view_url":

                    (
                        "https://www.google.com/maps/"
                        "@?api=1&map_action=pano"
                        f"&viewpoint="
                        f"{latitude},{longitude}"
                    )

                    if (
                        latitude is not None
                        and
                        longitude is not None
                    )

                    else None,

                "satellite_url":

                    (
                        "https://www.google.com/maps/"
                        "@?api=1&map_action=map"
                        f"&center="
                        f"{latitude},{longitude}"
                        "&zoom=18"
                        "&basemap=satellite"
                    )

                    if (
                        latitude is not None
                        and
                        longitude is not None
                    )

                    else None
            })


        coordinates = None


        if lat and lng:

            try:

                coordinates = {

                    "latitude":
                        float(lat),

                    "longitude":
                        float(lng)
                }

            except ValueError:

                pass


        return jsonify({

            "success": True,

            "query":
                query,

            "results":
                results,

            "coordinates":
                coordinates
        })


    except requests.RequestException as error:

        return jsonify({

            "success": False,

            "error":
                "Unable to connect to SerpApi.",

            "details":
                str(error)

        }), 502


# =========================================================
# REVIEWS
# =========================================================

@app.route(
    "/api/reviews",
    methods=["GET"]
)
def reviews():

    data_id = request.args.get(
        "data_id",
        ""
    ).strip()


    if not data_id:

        return jsonify({
            "success": False,
            "error":
                "Missing place ID."
        }), 400


    if not SERPAPI_KEY:

        return jsonify({
            "success": False,
            "error":
                "SerpApi key is not configured."
        }), 500


    try:

        response = requests.get(

            "https://serpapi.com/search.json",

            params={

                "engine":
                    "google_maps_reviews",

                "data_id":
                    data_id,

                "api_key":
                    SERPAPI_KEY
            },

            timeout=20
        )


        response.raise_for_status()


        data = response.json()


        return jsonify({

            "success":
                True,

            "reviews":
                data.get(
                    "reviews",
                    []
                )
        })


    except Exception as error:

        return jsonify({

            "success":
                False,

            "error":
                str(error)

        }), 502


# =========================================================
# LOCAL AI GUIDE
# NO OPENAI CREDITS REQUIRED
# =========================================================

def local_ai_guide(message):

    text = message.lower()


    if (
        "taxi" in text
        or
        "cab" in text
        or
        "uber" in text
        or
        "ola" in text
    ):

        return (
            "I can help you find nearby taxis. "
            "Use Explore with 'taxi near me' "
            "and allow your current location. "
            "NaviSphere searches nearby "
            "taxi/cab listings through SerpApi."
        )


    if (
        "food" in text
        or
        "restaurant" in text
        or
        "eat" in text
        or
        "cafe" in text
    ):

        return (
            "Use the Food section to search "
            "nearby restaurants and cafes. "
            "You can also enter a budget."
        )


    if (
        "route" in text
        or
        "direction" in text
        or
        "distance" in text
        or
        "travel" in text
    ):

        return (
            "Use Compare Your Journey to enter "
            "your starting point and destination. "
            "NaviSphere calculates road routes, "
            "distance and estimated travel time."
        )


    if (
        "hospital" in text
        or
        "medical" in text
    ):

        return (
            "Use the Hospitals quick-search "
            "option with location enabled "
            "to find nearby hospitals."
        )


    if (
        "pharmacy" in text
        or
        "medicine" in text
    ):

        return (
            "Use the Pharmacy quick-search "
            "option to find nearby pharmacies."
        )


    return (
        "I can help you find nearby services, "
        "compare routes, estimate travel costs "
        "and plan a journey based on your budget."
    )


# =========================================================
# AI GUIDE
# =========================================================

@app.route(
    "/api/ai-guide",
    methods=["POST"]
)
def ai_guide():

    data = request.get_json(
        silent=True
    ) or {}


    message = str(
        data.get(
            "message",
            ""
        )
    ).strip()


    if not message:

        return jsonify({
            "success": False,
            "error":
                "Please tell NaviSphere what you need."
        }), 400


    # Local fallback.
    # OpenAI is intentionally not required.

    answer = local_ai_guide(
        message
    )


    return jsonify({

        "success":
            True,

        "available":
            True,

        "reply":
            answer,

        "answer":
            answer,

        "source":
            "NaviSphere local guide"
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )


    app.run(

        host="0.0.0.0",

        port=port,

        debug=True
    ) 
