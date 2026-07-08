function formatDbm(value) {
    if (value === null || value === undefined) {
        return "-- dBm";
    }

    return Number(value).toFixed(2) + " dBm";
}

function formatDb(value) {
    if (value === null || value === undefined) {
        return "-- dB";
    }

    return Number(value).toFixed(2) + " dB";
}

function formatTemperature(value) {
    if (value === null || value === undefined) {
        return "-- °C";
    }

    return Number(value).toFixed(2) + " °C";
}

function formatTime(value) {
    if (!value) {
        return "--";
    }

    const date = new Date(value);
    return date.toLocaleTimeString();
}

async function updateDashboard() {
    try {
        const response = await fetch("/api/latest");
        const json = await response.json();

        const data = json.data || {};

        document.getElementById("p-a-in").textContent = formatDbm(data.p_a_in);
        document.getElementById("p-a-out").textContent = formatDbm(data.p_a_out);
        document.getElementById("p-b-in").textContent = formatDbm(data.p_b_in);
        document.getElementById("p-b-out").textContent = formatDbm(data.p_b_out);

        document.getElementById("gain-actual").textContent = formatDb(data.gain_actual);
        document.getElementById("gain-set").textContent = formatDb(data.gain_set);
        document.getElementById("gain-delta").textContent = formatDb(data.gain_delta);
        document.getElementById("temperature").textContent = formatTemperature(data.temperature);
        document.getElementById("last-update").textContent = formatTime(json.last_update);

        const status = document.getElementById("connection-status");

        if (json.connected) {
            status.textContent = "CONNECTED";
            status.className = "status status-ok";
        } else {
            status.textContent = "DISCONNECTED";
            status.className = "status status-error";
        }
    } catch (error) {
        const status = document.getElementById("connection-status");

        status.textContent = "API ERROR";
        status.className = "status status-error";

        console.error("Błąd pobierania /api/latest:", error);
    }
}

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const contents = document.querySelectorAll(".tab-content");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const selectedTab = button.dataset.tab;

            buttons.forEach(b => b.classList.remove("active"));
            contents.forEach(c => c.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(selectedTab).classList.add("active");

            if (selectedTab === "monitors") {
                updateMonitors();
            }
        });
    });
}

function setupGainButton() {
    const button = document.getElementById("set-gain-button");

    button.addEventListener("click", async () => {
        const input = document.getElementById("gain-set-input");
        const value = Number(input.value);

        try {
            const response = await fetch("/api/set_gain", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    gain_set: value
                })
            });

            if (!response.ok) {
                throw new Error("HTTP error " + response.status);
            }

            console.log("Ustawiono gain_set:", value);
        } catch (error) {
            alert("Nie udało się ustawić gain_set. Sprawdź port szeregowy.");
            console.error("Błąd /api/set_gain:", error);
        }
    });
}

setupTabs();
setupGainButton();
updateDashboard();

setInterval(updateDashboard, 1000);