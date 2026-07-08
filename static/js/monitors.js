let selectedRange = "5m";

let powerChart = null;
let gainChart = null;
let deltaChart = null;
let temperatureChart = null;

function getLabels(points) {
    return points.map(point => {
        const date = new Date(point.time);
        return date.toLocaleTimeString();
    });
}

function getValues(points, field) {
    return points.map(point => {
        if (point[field] === undefined || point[field] === null) {
            return null;
        }

        return Number(point[field]);
    });
}

function createOrUpdateChart(existingChart, canvasId, labels, datasets, yLabel) {
    const canvas = document.getElementById(canvasId);

    if (existingChart === null) {
        return new Chart(canvas, {
            type: "line",
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        title: {
                            display: true,
                            text: yLabel
                        }
                    }
                }
            }
        });
    }

    existingChart.data.labels = labels;
    existingChart.data.datasets = datasets;
    existingChart.update();

    return existingChart;
}

async function updateMonitors() {
    try {
        const response = await fetch("/api/history?range=" + selectedRange);
        const json = await response.json();

        const points = json.points || [];
        const labels = getLabels(points);

        powerChart = createOrUpdateChart(
            powerChart,
            "power-chart",
            labels,
            [
                {
                    label: "Port A IN",
                    data: getValues(points, "p_a_in")
                },
                {
                    label: "Port A OUT",
                    data: getValues(points, "p_a_out")
                },
                {
                    label: "Port B IN",
                    data: getValues(points, "p_b_in")
                },
                {
                    label: "Port B OUT",
                    data: getValues(points, "p_b_out")
                }
            ],
            "Power [dBm]"
        );

        gainChart = createOrUpdateChart(
            gainChart,
            "gain-chart",
            labels,
            [
                {
                    label: "Gain set",
                    data: getValues(points, "gain_set")
                },
                {
                    label: "Gain actual",
                    data: getValues(points, "gain_actual")
                }
            ],
            "Gain [dB]"
        );

        deltaChart = createOrUpdateChart(
            deltaChart,
            "delta-chart",
            labels,
            [
                {
                    label: "Gain delta",
                    data: getValues(points, "gain_delta")
                }
            ],
            "Delta [dB]"
        );

        temperatureChart = createOrUpdateChart(
            temperatureChart,
            "temperature-chart",
            labels,
            [
                {
                    label: "Temperature",
                    data: getValues(points, "temperature")
                }
            ],
            "Temperature [°C]"
        );
    } catch (error) {
        console.error("Błąd pobierania /api/history:", error);
    }
}

function setupRangeButtons() {
    const buttons = document.querySelectorAll(".range-button");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            selectedRange = button.dataset.range;

            buttons.forEach(b => b.classList.remove("active"));
            button.classList.add("active");

            updateMonitors();
        });
    });
}

setupRangeButtons();

setInterval(() => {
    const monitorsTab = document.getElementById("monitors");

    if (monitorsTab.classList.contains("active")) {
        updateMonitors();
    }
}, 3000);