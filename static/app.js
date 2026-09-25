// =====================================================
// NAVISPHERE AI FRONTEND
// =====================================================


// =====================================================
// MAP + LOCATION
// =====================================================

let map;
let markers = [];
let currentLocation = null;
let userMarker = null;
let accuracyCircle = null;
let satelliteLayer = null;
let streetLayer = null;
let satelliteEnabled = false;

function initializeMap() {

    map = L.map("map").setView([20.5937, 78.9629], 5);

    streetLayer = L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors"
        }
    ).addTo(map);

    // Esri World Imagery provides a satellite basemap.
    satelliteLayer = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        {
            maxZoom: 19,
            attribution: "Tiles &copy; Esri"
        }
    );
}

function toggleSatellite() {
    if (!map || !satelliteLayer) return;

    satelliteEnabled = !satelliteEnabled;

    if (satelliteEnabled) {
        map.removeLayer(streetLayer);
        satelliteLayer.addTo(map);
    } else {
        map.removeLayer(satelliteLayer);
        streetLayer.addTo(map);
    }

    const button = document.getElementById("satelliteToggle");
    if (button) {
        button.innerText = satelliteEnabled ? "🗺️ Street Map" : "🛰️ Satellite";
        button.classList.toggle("active", satelliteEnabled);
    }
}

function clearMarkers() {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];
}

function addMarker(latitude, longitude, title) {

    if (latitude == null || longitude == null) return;

    const streetViewUrl = makeStreetViewUrl(latitude, longitude);

    const popup = `
        <strong>${escapeHtml(title || "Place")}</strong>
        <br><br>
        <a href="${safeUrl(streetViewUrl)}" target="_blank" rel="noopener">
            📍 Open Street View
        </a>
    `;

    const marker = L.marker([latitude, longitude])
        .addTo(map)
        .bindPopup(popup);

    markers.push(marker);
}

function makeStreetViewUrl(latitude, longitude) {
    return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${encodeURIComponent(`${latitude},${longitude}`)}`;
}

function useCurrentLocation(autoSearch = false) {

    if (!navigator.geolocation) {
        showLocationMessage("Your browser does not support location services.");
        return;
    }

    const button = document.getElementById("locationButton");
    if (button) {
        button.disabled = true;
        button.innerText = "📍 Finding you...";
    }

    navigator.geolocation.getCurrentPosition(
        position => {
            const { latitude, longitude, accuracy } = position.coords;

            currentLocation = {
                latitude,
                longitude,
                accuracy
            };

            if (map) {
                map.setView([latitude, longitude], 17);

                if (userMarker) map.removeLayer(userMarker);
                if (accuracyCircle) map.removeLayer(accuracyCircle);

                userMarker = L.marker([latitude, longitude])
                    .addTo(map)
                    .bindPopup("📍 You are here")
                    .openPopup();

                accuracyCircle = L.circle([latitude, longitude], {
                    radius: accuracy,
                    weight: 1
                }).addTo(map);
            }

            const locationInput = document.getElementById("mainLocation");
            if (locationInput) {
                locationInput.value = "Current location";
            }

            const status = document.getElementById("locationStatus");
            if (status) {
                status.innerText = `Location ready • ±${Math.round(accuracy)} m accuracy`;
                status.classList.add("location-ready");
            }

            const streetButton = document.getElementById("currentStreetView");
            if (streetButton) {
                streetButton.classList.add("ready");
                streetButton.title = "Open the real Street View panorama closest to you";
            }

            if (button) {
                button.disabled = false;
                button.innerText = "📍 Use my current location";
            }

            if (autoSearch) {
                performSearch();
            }
        },
        error => {
            if (button) {
                button.disabled = false;
                button.innerText = "📍 Use my current location";
            }

            let message = "Could not get your location.";
            if (error.code === error.PERMISSION_DENIED) {
                message = "Location permission was denied. Allow location access in Chrome and try again.";
            } else if (error.code === error.POSITION_UNAVAILABLE) {
                message = "Your location is currently unavailable.";
            } else if (error.code === error.TIMEOUT) {
                message = "Location request timed out. Please try again.";
            }

            showLocationMessage(message);
        },
        {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 60000
        }
    );
}

function showLocationMessage(message) {
    const status = document.getElementById("locationStatus");
    if (status) status.innerText = message;
}

function openCurrentStreetView() {
    if (!currentLocation) {
        useCurrentLocation(false);
        showLocationMessage("Get your location first, then click Street View again.");
        return false;
    }

    const url = makeStreetViewUrl(currentLocation.latitude, currentLocation.longitude);
    window.open(url, "_blank", "noopener");
    return false;
}

function clearLocation() {
    currentLocation = null;
    if (userMarker && map) map.removeLayer(userMarker);
    if (accuracyCircle && map) map.removeLayer(accuracyCircle);
    userMarker = null;
    accuracyCircle = null;
}

// =====================================================
// SEARCH
// =====================================================

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";
    const raw = await response.text();

    let data;
    if (contentType.includes("application/json")) {
        try {
            data = JSON.parse(raw);
        } catch {
            throw new Error("The server returned invalid JSON.");
        }
    } else {
        const preview = raw.replace(/\s+/g, " ").slice(0, 160);
        throw new Error(
            response.ok
                ? `The server returned HTML instead of JSON: ${preview}`
                : `Server error ${response.status}: ${preview}`
        );
    }

    if (!response.ok) {
        throw new Error(data.error || `Request failed (${response.status}).`);
    }

    return data;
}

async function performSearch() {
    const queryEl = document.getElementById("mainQuery");
    const locationEl = document.getElementById("mainLocation");
    const resultsBox = document.getElementById("results");
    const count = document.getElementById("resultCount");

    // If the user clicks Explore without typing anything, search nearby places.
    const query = (queryEl?.value || "").trim() || "restaurants";
    const location = (locationEl?.value || "").trim();

    // Always move the user to the results area so the button has visible feedback.
    document.getElementById("explore")?.scrollIntoView({ behavior: "smooth", block: "start" });

    if (resultsBox) {
        resultsBox.innerHTML = `
            <div class="empty-state loading-state">
                <div class="loading-orb">⌖</div>
                <h3>Searching nearby places...</h3>
                <p>Getting live location and place data.</p>
            </div>`;
    }
    if (count) count.innerText = "Searching...";

    // No typed location? Ask for GPS and continue automatically.
    if (!currentLocation && !location) {
        showLocationMessage("Allow location access to find places near you...");
        useCurrentLocation(true);
        return;
    }

    const params = new URLSearchParams({ q: query });

    if (currentLocation) {
        params.set("lat", String(currentLocation.latitude));
        params.set("lng", String(currentLocation.longitude));
    } else {
        params.set("location", location);
    }

    const isFoodQuery = /food|restaurant|restaurants|cafe|café|vegan|vegetarian|halal|pizza|burger|breakfast|lunch|dinner/i.test(query);
    const foodBudget = document.getElementById("foodBudget");
    if (isFoodQuery && foodBudget && foodBudget.value.trim()) {
        params.set("budget", foodBudget.value.trim());
    }

    const openNow = document.getElementById("foodOpenNow");
    if (isFoodQuery && openNow && openNow.checked) {
        params.set("open_now", "1");
    }

    try {
        const data = await fetchJson(`/api/search?${params.toString()}`);
        displayResults(data.results || [], data.coordinates);
        showLocationMessage(currentLocation ? "Live location search complete." : `Showing results for ${location}.`);
    } catch (error) {
        console.error("NaviSphere search error:", error);
        if (resultsBox) {
            resultsBox.innerHTML = `
                <div class="empty-state error-state">
                    <div>⚠️</div>
                    <h3>Search could not be completed</h3>
                    <p>${escapeHtml(error.message)}</p>
                    <p class="small-help">If you added a SerpApi key, save .env and restart Flask. NaviSphere also has a free OpenStreetMap fallback.</p>
                </div>`;
        }
        if (count) count.innerText = "Error";
    }
}

// =====================================================
// QUICK SEARCH
// =====================================================

function quickSearch(query) {
    document.getElementById("mainQuery").value = query;
    document.getElementById("explore").scrollIntoView({ behavior: "smooth", block: "start" });

    setTimeout(() => {
        if (currentLocation) {
            performSearch();
        } else if (document.getElementById("mainLocation").value.trim()) {
            performSearch();
        } else {
            useCurrentLocation(true);
        }
    }, 350);
}

function searchFoodNearMe() {
    document.getElementById("mainQuery").value = "restaurants";
    document.getElementById("explore").scrollIntoView({ behavior: "smooth", block: "start" });

    setTimeout(() => {
        if (currentLocation) {
            performSearch();
        } else {
            useCurrentLocation(true);
        }
    }, 350);
}

// =====================================================
// DISPLAY RESULTS
// =====================================================

function displayResults(places, coordinates = null) {

    const resultsBox = document.getElementById("results");
    const count = document.getElementById("resultCount");

    clearMarkers();

    if (!places || places.length === 0) {
        resultsBox.innerHTML = `
            <div class="empty-state">
                <div>🧭</div>
                <h3>No places found</h3>
                <p>Try a broader search or increase your search area.</p>
            </div>`;
        count.innerText = "0 results";
        return;
    }

    count.innerText = `${places.length} places`;
    resultsBox.innerHTML = places.map(placeCard).join("");

    places.forEach(place => {
        addMarker(place.latitude, place.longitude, place.title || "Place");
    });

    if (map && coordinates && coordinates.latitude != null && coordinates.longitude != null) {
        map.setView([coordinates.latitude, coordinates.longitude], 15);
    } else {
        const firstPlace = places.find(place => place.latitude != null && place.longitude != null);
        if (map && firstPlace) map.setView([firstPlace.latitude, firstPlace.longitude], 14);
    }
}

function placeCard(place) {

    const image = place.thumbnail || "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80";
    const rating = place.rating ? `⭐ ${place.rating}` : "Rating unavailable";
    const reviews = place.reviews ? `${place.reviews} reviews` : "";
    const open = place.open_state || "";
    const price = place.price ? ` · ${place.price}` : "";

    const website = place.website
        ? `<a href="${safeUrl(place.website)}" target="_blank" rel="noopener">Website</a>`
        : "";

    const directions = place.directions
        ? `<a href="${safeUrl(place.directions)}" target="_blank" rel="noopener">Directions</a>`
        : "";

    const streetView = place.street_view_url
        ? `<a class="action-primary" href="${safeUrl(place.street_view_url)}" target="_blank" rel="noopener">📷 360° Street View</a>`
        : "";

    const satellite = place.satellite_url
        ? `<a href="${safeUrl(place.satellite_url)}" target="_blank" rel="noopener">🛰️ Satellite</a>`
        : "";

    const reviewButton = place.data_id
        ? `<button onclick="loadReviews('${escapeJs(place.data_id)}')">Reviews</button>`
        : "";

    const isOpen = open.toLowerCase().includes("open");
    const statusClass = isOpen ? "open-status" : "";

    return `
        <article class="place-card">
            <img src="${safeUrl(image)}" alt="${escapeHtml(place.title || "Place")}" loading="lazy">

            <div class="place-title-row">
                <h3>${escapeHtml(place.title || "Unknown place")}</h3>
                ${open ? `<span class="place-open ${statusClass}">${escapeHtml(open)}</span>` : ""}
            </div>

            <div class="place-meta">
                ${escapeHtml(rating)} · ${escapeHtml(reviews)}${escapeHtml(price)}
            </div>

            <div class="place-meta">${escapeHtml(place.type || "")}</div>
            <div class="place-meta">${escapeHtml(place.address || "Address unavailable")}</div>

            <div class="place-actions">
                ${directions}
                ${streetView}
                ${satellite}
                ${website}
                ${reviewButton}
            </div>
        </article>
    `;
}

// =====================================================
// REVIEWS
// =====================================================

async function loadReviews(
    dataId
) {

    try {

        const data = await fetchJson(
            `/api/reviews?data_id=${encodeURIComponent(dataId)}`
        );

        if (
            !data.reviews ||
            data.reviews.length === 0
        ) {

            alert(
                "No reviews were returned for this place."
            );

            return;
        }

        const text =
            data.reviews
                .map(
                    review =>
                        `⭐ ${review.rating || "-"} — ${review.snippet || "No review text"}`
                )
                .join("\n\n");

        alert(
            "Review Intelligence\n\n" +
            text
        );

    } catch (error) {

        alert(
            error.message
        );
    }
}


// =====================================================
// FOOD
// =====================================================

function searchFood() {
    const preference = document.getElementById("foodPreference").value.trim();
    const budget = document.getElementById("foodBudget").value.trim();

    if (budget && (!/^\d+(\.\d+)?$/.test(budget) || Number(budget) <= 0)) {
        alert("Please enter a valid positive budget, for example 300 or 500.");
        document.getElementById("foodBudget").focus();
        return;
    }

    // Do NOT append the budget to the query here. performSearch sends the
    // numeric budget separately, which prevents duplicate "under Rs ..." text.
    document.getElementById("mainQuery").value = preference || "restaurants";
    document.getElementById("explore").scrollIntoView({ behavior: "smooth", block: "start" });

    setTimeout(() => {
        if (currentLocation) {
            performSearch();
        } else {
            useCurrentLocation(true);
        }
    }, 350);
}

// =====================================================
// ROUTES
// =====================================================

async function getDirections() {

    const start =
        document.getElementById(
            "routeStart"
        ).value.trim();

    const end =
        document.getElementById(
            "routeEnd"
        ).value.trim();

    if (!start || !end) {

        alert(
            "Please enter both locations."
        );

        return;
    }

    const output =
        document.getElementById(
            "routeResults"
        );

    output.innerHTML =
        `<div class="empty-state">
            <div>🗺️</div>
            <h3>Calculating routes...</h3>
        </div>`;

    try {

        const data = await fetchJson(
            `/api/directions?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
        );

        if (
            !data.routes ||
            data.routes.length === 0
        ) {

            output.innerHTML =
                `<div class="empty-state">
                    <h3>No route data returned</h3>
                </div>`;

            return;
        }

        output.innerHTML =
            data.routes.map(
                route => `
                    <div class="route-card">

                        <strong>
                            ${escapeHtml(
                                route.title ||
                                "Route"
                            )}
                        </strong>

                        <span>
                            📍
                            ${escapeHtml(
                                route.formatted_distance ||
                                route.distance ||
                                "N/A"
                            )}
                        </span>

                        <span>
                            ⏱️
                            ${escapeHtml(
                                route.formatted_duration ||
                                route.duration ||
                                "N/A"
                            )}
                        </span>

                        <span>
                            💰
                            ${escapeHtml(
                                String(
                                    route.price ||
                                    "N/A"
                                )
                            )}
                        </span>

                    </div>
                `
            ).join("");

    } catch (error) {

        output.innerHTML =
            `<div class="empty-state">
                <h3>⚠️ ${escapeHtml(error.message)}</h3>
            </div>`;
    }
}


// =====================================================
// TRIPTWIN
// =====================================================

async function runTripTwin() {
    const budgetEl = document.getElementById("twinBudget");
    const spendingEl = document.getElementById("twinSpending");
    const travelEl = document.getElementById("twinTravel");
    const bufferEl = document.getElementById("twinBuffer");
    const result = document.getElementById("twinResult");
    const button = document.querySelector('#twinResult')?.parentElement?.querySelector('button');

    const budget = Number(budgetEl?.value || 0);
    const spending = Number(spendingEl?.value || 0);
    const travelTime = Number(travelEl?.value || 0);
    const buffer = Number(bufferEl?.value || 0);

    // Always clear the previous result so a second test visibly starts a new run.
    result.innerHTML = '<p>Testing your updated trip...</p>';
    if (button) button.disabled = true;

    try {
        const response = await fetch("/api/triptwin", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" },
            cache: "no-store",
            body: JSON.stringify({
                budget,
                spending,
                travel_time: travelTime,
                schedule_gap: buffer
            })
        });

        const text = await response.text();
        let data;
        try { data = JSON.parse(text); }
        catch { throw new Error("The server returned an invalid response. Please restart Flask and try again."); }

        if (!response.ok) throw new Error(data.error || "TripTwin request failed.");

        result.innerHTML = `
            <h3>${escapeHtml(data.status || "Trip checked")}</h3>
            ${Object.entries(data.checks || {}).map(([name, value]) => `
                <div class="check ${value ? "good" : "bad"}">
                    <span>${escapeHtml(name)}</span>
                    <strong>${value ? "✓ Fits" : "⚠ Adjust"}</strong>
                </div>
            `).join("")}
        `;
    } catch (error) {
        result.innerHTML = `<p>⚠️ ${escapeHtml(error.message)}</p>`;
    } finally {
        if (button) button.disabled = false;
    }
}


// =====================================================
// WHAT-IF
// =====================================================

async function runSimulation() {

    const scenario =
        document.getElementById(
            "scenario"
        ).value;

    const budget =
        Number(
            document.getElementById(
                "simulationBudget"
            ).value
        );

    const output =
        document.getElementById(
            "simulationResult"
        );

    try {

        const response =
            await fetch(
                "/api/simulate",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            scenario,
                            budget
                        })
                }
            );

        const data =
            await response.json();

        output.innerHTML = `

            <div class="simulation-card">

                <h3>
                    ${escapeHtml(
                        data.scenario
                    )}
                </h3>

                <p>
                    Original budget:
                    <strong>
                        ${escapeHtml(
                            String(
                                data.original
                            )
                        )}
                    </strong>
                </p>

                <p>
                    Simulated budget:
                    <strong>
                        ${escapeHtml(
                            String(
                                data.simulated
                            )
                        )}
                    </strong>
                </p>

                <p>
                    Estimated walking:
                    <strong>
                        ${escapeHtml(
                            data.walking
                        )}
                    </strong>
                </p>

                <p>
                    Places:
                    <strong>
                        ${escapeHtml(
                            String(
                                data.places
                            )
                        )}
                    </strong>
                </p>

                <ul class="change-list">

                    ${data.changes
                        .map(
                            item =>
                                `<li>
                                    ${escapeHtml(item)}
                                </li>`
                        )
                        .join("")}

                </ul>

            </div>
        `;

    } catch (error) {

        output.innerHTML =
            `<div class="simulation-card">
                ⚠️ ${escapeHtml(error.message)}
            </div>`;
    }
}


// =====================================================
// DARK / LIGHT MODE
// =====================================================

const themeToggle =
    document.getElementById(
        "themeToggle"
    );


function updateThemeButton() {

    themeToggle.innerText =
        document.body.classList.contains(
            "dark"
        )
        ? "☀️"
        : "🌙";
}


const savedTheme =
    localStorage.getItem(
        "navisphere-theme"
    );


if (savedTheme === "dark") {

    document.body.classList.add(
        "dark"
    );
}


updateThemeButton();


themeToggle.addEventListener(
    "click",
    () => {

        document.body.classList.toggle(
            "dark"
        );

        const dark =
            document.body.classList.contains(
                "dark"
            );

        localStorage.setItem(
            "navisphere-theme",
            dark
            ? "dark"
            : "light"
        );

        updateThemeButton();

    }
);


// =====================================================
// SECURITY HELPERS
// =====================================================

function escapeHtml(
    value
) {

    return String(
        value ?? ""
    )
    .replaceAll(
        "&",
        "&amp;"
    )
    .replaceAll(
        "<",
        "&lt;"
    )
    .replaceAll(
        ">",
        "&gt;"
    )
    .replaceAll(
        '"',
        "&quot;"
    )
    .replaceAll(
        "'",
        "&#039;"
    );
}


function escapeJs(
    value
) {

    return String(
        value ?? ""
    )
    .replaceAll(
        "\\",
        "\\\\"
    )
    .replaceAll(
        "'",
        "\\'"
    );
}


function safeUrl(
    value
) {

    const url =
        String(
            value ?? ""
        );

    if (
        url.startsWith(
            "https://"
        ) ||
        url.startsWith(
            "http://"
        )
    ) {

        return url;
    }

    return "#";
}


// =====================================================
// START
// =====================================================

document.addEventListener("DOMContentLoaded", () => {
    initializeMap();

    // Make Explore work even if inline onclick is blocked or changed.
    const exploreButton = document.querySelector('.hero-search button');
    if (exploreButton) {
        exploreButton.addEventListener("click", (event) => {
            event.preventDefault();
            performSearch();
        });
    }

    const queryInput = document.getElementById("mainQuery");
    const locationInput = document.getElementById("mainLocation");
    [queryInput, locationInput].forEach(input => {
        if (input) {
            input.addEventListener("keydown", event => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    performSearch();
                }
            });
        }
    });
}); 
const askAIButton = document.getElementById("askAIButton");
const aiMessage = document.getElementById("aiMessage");
const aiResponse = document.getElementById("aiResponse");
const aiLoading = document.getElementById("aiLoading");

if (askAIButton) {

    askAIButton.addEventListener("click", async () => {

        const message = aiMessage.value.trim();

        if (!message) {
            aiResponse.innerHTML =
                "<p>Please tell NaviSphere what you need.</p>";
            return;
        }

        aiLoading.style.display = "block";
        aiResponse.innerHTML = "";

        try {

            const response = await fetch("/api/ai-guide", {

                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    message: message
                })

            });

            const contentType = response.headers.get("content-type") || "";
            const data = contentType.includes("application/json")
                ? await response.json()
                : { error: `Server returned ${response.status} instead of JSON.` };

            if (!response.ok || data.error) {

                aiResponse.innerHTML = `
                    <p>
                        ⚠️ ${data.error || "Something went wrong."}
                    </p>
                `;

                return;
            }

            aiResponse.innerHTML = `
                <div class="ai-result">
                    <div class="ai-result-title">
                        ✦ NaviSphere AI
                    </div>

                    <p>${formatAIResponse(data.reply)}</p>
                </div>
            `;

        } catch (error) {

            aiResponse.innerHTML = `
                <p>
                    ⚠️ Could not connect to NaviSphere AI.
                    Please make sure the Flask server is running.
                </p>
            `;

        } finally {

            aiLoading.style.display = "none";

        }

    });

}


function formatAIResponse(text) {

    return text
        .replace(/\n/g, "<br>")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

} 
