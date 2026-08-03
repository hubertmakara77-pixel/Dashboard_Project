// History queries, statistics and chart rendering.
function getFullTimestamps(points) {
	return points.map((point) => {
		const date = new Date(point.time)
		if (Number.isNaN(date.getTime())) return point.time || ''
		const pad = (number) => String(number).padStart(2, '0')
		return (
			`${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ` +
			`${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
		)
	})
}

function formatTimeAxisTick(value, timeBounds) {
	const date = new Date(Number(value))
	if (Number.isNaN(date.getTime())) return ''
	const pad = (number) => String(number).padStart(2, '0')
	const spanMs = Math.max(0, Number(timeBounds.max) - Number(timeBounds.min))
	const dayMs = 24 * 60 * 60 * 1000
	if (spanMs > 365 * dayMs) {
		return `${pad(date.getMonth() + 1)}.${date.getFullYear()}`
	}
	if (spanMs > dayMs) {
		return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}`
	}
	const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
	return spanMs <= 5 * 60 * 1000 ? `${time}:${pad(date.getSeconds())}` : time
}

function getTimeAxisTitle(timeBounds) {
	const spanMs = Math.max(0, Number(timeBounds.max) - Number(timeBounds.min))
	const dayMs = 24 * 60 * 60 * 1000
	if (spanMs > 365 * dayMs) return 'Month (MM.YYYY)'
	if (spanMs > dayMs) return 'Date (DD.MM)'
	return 'Time (24-hour)'
}

function getOverviewTimeBounds(points) {
	const durations = {
		'5m': 5 * 60 * 1000,
		'1h': 60 * 60 * 1000,
		'24h': 24 * 60 * 60 * 1000,
		'7d': 7 * 24 * 60 * 60 * 1000,
		'30d': 30 * 24 * 60 * 60 * 1000,
	}
	const pointTimes = points.map((point) => new Date(point.time).getTime()).filter(Number.isFinite)
	const requestedEnd = overviewEnd ? new Date(overviewEnd).getTime() : Date.now()
	const requestedStart = overviewStart
		? new Date(overviewStart).getTime()
		: requestedEnd - (durations[overviewRange] || 0)

	if (overviewRange !== 'all' || overviewStart || overviewEnd) {
		return {
			min: Number.isFinite(requestedStart) ? requestedStart : pointTimes[0],
			max: Number.isFinite(requestedEnd) ? requestedEnd : pointTimes.at(-1),
		}
	}
	if (!pointTimes.length) {
		const now = Date.now()
		return { min: now - 5 * 60 * 1000, max: now }
	}
	return { min: pointTimes[0], max: pointTimes.at(-1) }
}

function addHistoryGapMarkers(points, rangeValue) {
	if (points.length < 2) return points

	const datedPoints = points.map((point) => ({
		point,
		timestamp: new Date(point.time).getTime(),
	}))
	const intervals = []
	for (let index = 1; index < datedPoints.length; index += 1) {
		const interval = datedPoints[index].timestamp - datedPoints[index - 1].timestamp
		intervals.push(Number.isFinite(interval) && interval > 0 ? interval : null)
	}
	const validIntervals = intervals.filter((interval) => interval !== null)
	if (!validIntervals.length) return points

	const sortedIntervals = [...validIntervals].sort((left, right) => left - right)
	// A lower quartile represents the normal sampling cadence without letting
	// one or more long outages inflate the threshold used to detect a gap.
	const typicalInterval = sortedIntervals[Math.floor((sortedIntervals.length - 1) * 0.25)]
	const bucketMs =
		{
			'5m': 1000,
			'1h': 10000,
			'24h': 60000,
			'7d': 600000,
			'30d': 1800000,
			all: 3600000,
		}[rangeValue] || 1000
	const result = [datedPoints[0].point]

	for (let index = 1; index < datedPoints.length; index += 1) {
		const previous = datedPoints[index - 1]
		const current = datedPoints[index]
		const currentInterval = current.timestamp - previous.timestamp
		// Compare against cadence on both sides of this interval. This lets a
		// device change from e.g. 100 ms to 10 s without turning every new
		// sample into a false gap, while an isolated outage remains visible.
		const neighbourIntervals = [intervals[index - 2], intervals[index]].filter(
			(interval) => interval !== null && interval !== undefined,
		)
		const localCadence = Math.max(bucketMs, typicalInterval, ...neighbourIntervals)
		if (currentInterval > localCadence * 2.5) {
			result.push({
				time: new Date((previous.timestamp + current.timestamp) / 2).toISOString(),
			})
		}
		result.push(current.point)
	}

	return result
}

function getValues(points, field) {
	return points.map((point) => {
		if (point[field] === undefined || point[field] === null) return null
		return Number(point[field])
	})
}

function getStatisticsLimits(field) {
	if (!dashboardSettings) return null
	if (field === 'gain_delta') {
		const tolerance = Number(dashboardSettings.gain_tolerance)
		return Number.isFinite(tolerance)
			? { min: -Math.abs(tolerance), max: Math.abs(tolerance) }
			: null
	}
	const limits = dashboardSettings.warn_limits?.[field]
	if (!limits || (limits.min === null && limits.max === null)) return null
	return limits
}

function formatOutsideLimits(field, statistics) {
	const limits = getStatisticsLimits(field)
	if (!limits) return '--'
	const below = limits.min !== null && Number(statistics.min) < Number(limits.min)
	const above = limits.max !== null && Number(statistics.max) > Number(limits.max)
	if (!below && !above) return '<span class="status-ok">No</span>'
	const reason = below && above ? 'below MIN and above MAX' : below ? 'below MIN' : 'above MAX'
	return `<span class="status-error">Yes (${reason})</span>`
}

async function updateAmplifierStatisticsTable() {
	if (!currentUser) return

	const requestSequence = ++statisticsRequestSequence
	if (statisticsRequestController) statisticsRequestController.abort()
	statisticsRequestController = new AbortController()
	const requestController = statisticsRequestController
	const query = buildStatisticsQuery()
	const source = document.getElementById('statistics-source')
	if (source) source.textContent = 'Loading\u2026'
	// Mark the refresh as started immediately. Otherwise the timer starts
	// duplicate expensive queries while the first one is still running.
	lastStatisticsRefresh = Date.now()

	try {
		const response = await fetch('/api/statistics?' + query, {
			signal: requestController.signal,
		})
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		if (requestSequence !== statisticsRequestSequence) return
		const statistics = json.statistics || {}
		lastStatisticsRefresh = Date.now()
		const body = document.getElementById('statistics-table-body')

		if (source) {
			const rangeText = statisticsStart || statisticsEnd ? 'custom range' : json.range
			source.textContent = `${Number(json.sample_count || 0)} raw samples, ${rangeText}`
		}

		if (!body) return

		const fields = [
			['PiA', 'PiA', 'dBm'],
			['PoA', 'PoA', 'dBm'],
			['PiB', 'PiB', 'dBm'],
			['PoB', 'PoB', 'dBm'],
			['G', 'G', ''],
			['SG', 'SG', ''],
			['PP', 'PP', ''],
			['SPP', 'SPP', ''],
			['gain_set', 'Gain Setpoint', 'dB'],
			['gain_actual', 'Actual Gain', 'dB'],
			['gain_delta', 'Gain Delta', 'dB'],
			['temperature', 'Temperature', '\u00B0C'],
		]

		const rows = fields
			.map(([field, label, unit]) => {
				const stats = statistics[field]

				if (!stats) {
					return `
                    <tr>
                        <td>${label}</td>
                        <td colspan="5">No data</td>
                    </tr>
                `
				}

				return `
                <tr>
                    <td>${label}</td>
                    <td>${formatPlainNumber(stats.min)}${unit ? ' ' + unit : ''}</td>
                    <td>${formatPlainNumber(stats.max)}${unit ? ' ' + unit : ''}</td>
                    <td>${formatPlainNumber(stats.average)}${unit ? ' ' + unit : ''}</td>
					<td>${formatPlainNumber(stats.standard_deviation)}${unit ? ' ' + unit : ''}</td>
					<td>${formatOutsideLimits(field, stats)}</td>
                </tr>
            `
			})
			.join('')

		body.innerHTML = rows
	} catch (error) {
		if (error.name === 'AbortError') return
		if (requestSequence !== statisticsRequestSequence) return
		if (source) source.textContent = 'Could not load statistics'
		console.error('Error fetching statistics:', error)
	} finally {
		if (requestSequence === statisticsRequestSequence) {
			statisticsRequestController = null
		}
	}
}

function createOrUpdateChart(
	existingChart,
	canvasId,
	points,
	fullTimestamps,
	datasets,
	yLabel,
	timeBounds,
) {
	const canvas = document.getElementById(canvasId)
	if (!canvas || typeof Chart === 'undefined') return existingChart
	const timeValues = points.map((point) => new Date(point.time).getTime())
	datasets.forEach((dataset) => {
		dataset.data = dataset.data.map((value, index) => ({
			x: timeValues[index],
			y: value,
		}))
		const savedVisibility = chartSeriesVisibility.get(`${canvasId}:${dataset.label}`)
		if (savedVisibility !== undefined) dataset.hidden = !savedVisibility
	})

	if (existingChart === null) {
		const chart = new Chart(canvas, {
			type: 'line',
			data: { datasets: datasets },
			options: {
				animation: false,
				responsive: true,
				maintainAspectRatio: false,
				locale: 'pl-PL',
				plugins: {
					tooltip: {
						callbacks: {
							title: (items) => {
								if (!items.length) return ''
								return (
									items[0].chart.fullTimestamps?.[items[0].dataIndex] ||
									items[0].label
								)
							},
						},
					},
					legend: {
						labels: { usePointStyle: true },
						onClick: (_event, legendItem, legend) => {
							const index = legendItem.datasetIndex
							const dataset = legend.chart.data.datasets[index]
							const visible = !legend.chart.isDatasetVisible(index)
							chartSeriesVisibility.set(`${canvasId}:${dataset.label}`, visible)
							legend.chart.setDatasetVisibility(index, visible)
							legend.chart.update()
						},
						onHover: (event) => {
							if (event.native && event.native.target)
								event.native.target.style.cursor = 'pointer'
						},
						onLeave: (event) => {
							if (event.native && event.native.target)
								event.native.target.style.cursor = 'default'
						},
					},
				},
				scales: {
					x: {
						type: 'linear',
						min: timeBounds.min,
						max: timeBounds.max,
						title: {
							display: true,
							text: getTimeAxisTitle(timeBounds),
						},
						afterBuildTicks: (scale) => {
							const interval = (scale.max - scale.min) / 4
							scale.ticks = Array.from({ length: 5 }, (_item, index) => ({
								value: scale.min + interval * index,
							}))
						},
						ticks: {
							autoSkip: false,
							maxRotation: 0,
							minRotation: 0,
							callback: (value) => formatTimeAxisTick(value, timeBounds),
						},
					},
					y: { title: { display: true, text: yLabel } },
				},
			},
		})
		chart.fullTimestamps = fullTimestamps
		return chart
	}

	existingChart.data.datasets = datasets
	existingChart.options.scales.x.min = timeBounds.min
	existingChart.options.scales.x.max = timeBounds.max
	existingChart.options.scales.x.title.text = getTimeAxisTitle(timeBounds)
	existingChart.options.scales.x.ticks.callback = (value) => formatTimeAxisTick(value, timeBounds)
	datasets.forEach((dataset, index) => {
		const savedVisibility = chartSeriesVisibility.get(`${canvasId}:${dataset.label}`)
		if (savedVisibility !== undefined)
			existingChart.setDatasetVisibility(index, savedVisibility)
	})
	existingChart.fullTimestamps = fullTimestamps
	existingChart.update()
	return existingChart
}

function resizeChartInCard(card) {
	const canvas = card.querySelector('canvas')
	if (!canvas || typeof Chart === 'undefined' || typeof Chart.getChart !== 'function') return
	const chart = Chart.getChart(canvas)
	if (chart) {
		window.requestAnimationFrame(() => {
			window.requestAnimationFrame(() => chart.resize())
		})
		window.setTimeout(() => chart.resize(), 200)
	}
}

function getChartSizeIcon(expanded) {
	const path = expanded
		? 'M8 3v5H3 M16 3v5h5 M8 21v-5H3 M16 21v-5h5'
		: 'M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5'
	return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"></path></svg>`
}

function setChartExpanded(card, expanded) {
	card.classList.toggle('expanded', expanded)
	const button = card.querySelector('.chart-expand-button')
	const title = card.querySelector('h3')?.textContent || 'chart'
	if (button) {
		button.innerHTML = getChartSizeIcon(expanded)
		button.setAttribute('aria-label', `${expanded ? 'Reduce' : 'Expand'} ${title} chart`)
		button.title = expanded ? 'Reduce chart' : 'Expand chart'
		button.setAttribute('aria-pressed', String(expanded))
	}
	resizeChartInCard(card)
}

function setupChartExpansion() {
	document.querySelectorAll('.chart-expand-button').forEach((button) => {
		button.innerHTML = getChartSizeIcon(false)
		button.setAttribute('aria-pressed', 'false')
		button.addEventListener('click', () => {
			const card = button.closest('.chart-card')
			if (!card) return
			const shouldExpand = !card.classList.contains('expanded')
			setChartExpanded(card, shouldExpand)
		})
	})

	document.addEventListener('keydown', (event) => {
		if (event.key !== 'Escape') return
		document
			.querySelectorAll('.chart-card.expanded')
			.forEach((card) => setChartExpanded(card, false))
	})
}

async function updateAmplifierOverviewCharts() {
	if (!currentUser) return

	const requestSequence = ++overviewRequestSequence
	if (overviewRequestController) overviewRequestController.abort()
	overviewRequestController = new AbortController()
	const requestController = overviewRequestController
	const loadingStatus = document.getElementById('overview-loading-status')
	if (loadingStatus) loadingStatus.textContent = 'Loading\u2026'
	lastOverviewChartRefresh = Date.now()

	try {
		const response = await fetch('/api/history?' + buildOverviewQuery(), {
			signal: requestController.signal,
		})
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		if (requestSequence !== overviewRequestSequence) return
		const points = addHistoryGapMarkers(json.points || [], overviewRange)
		const fullTimestamps = getFullTimestamps(points)
		const timeBounds = getOverviewTimeBounds(points)

		powerChart = createOrUpdateChart(
			powerChart,
			'power-chart',
			points,
			fullTimestamps,
			[
				{ label: 'PiA', data: getValues(points, 'PiA'), spanGaps: false },
				{ label: 'PoA', data: getValues(points, 'PoA'), spanGaps: false },
				{ label: 'PiB', data: getValues(points, 'PiB'), spanGaps: false },
				{ label: 'PoB', data: getValues(points, 'PoB'), spanGaps: false },
			],
			'Power [dBm]',
			timeBounds,
		)

		gainChart = createOrUpdateChart(
			gainChart,
			'gain-chart',
			points,
			fullTimestamps,
			[
				{ label: 'Gain set', data: getValues(points, 'gain_set'), spanGaps: false },
				{ label: 'Gain actual', data: getValues(points, 'gain_actual'), spanGaps: false },
			],
			'Gain [dB]',
			timeBounds,
		)

		deltaChart = createOrUpdateChart(
			deltaChart,
			'delta-chart',
			points,
			fullTimestamps,
			[{ label: 'Gain delta', data: getValues(points, 'gain_delta'), spanGaps: false }],
			'Delta [dB]',
			timeBounds,
		)

		temperatureChart = createOrUpdateChart(
			temperatureChart,
			'temperature-chart',
			points,
			fullTimestamps,
			[{ label: 'Temperature', data: getValues(points, 'temperature'), spanGaps: false }],
			'Temperature [\u00B0C]',
			timeBounds,
		)
		lastOverviewChartRefresh = Date.now()
		if (loadingStatus) loadingStatus.textContent = ''
	} catch (error) {
		if (error.name === 'AbortError') return
		if (requestSequence !== overviewRequestSequence) return
		if (loadingStatus) loadingStatus.textContent = 'Could not load data'
		console.error('Error fetching /api/history:', error)
	} finally {
		if (requestSequence === overviewRequestSequence) {
			overviewRequestController = null
		}
	}
}

function setupRangeButtons() {
	document.querySelectorAll('.range-button[data-range]').forEach((button) => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			const isStatistics = panel?.dataset.tab === 'statistics'
			const rangeValue = button.dataset.range
			panel
				.querySelectorAll('.range-button')
				.forEach((item) => item.classList.remove('active'))
			button.classList.add('active')
			panel.querySelector('.custom-range').hidden = true
			if (isStatistics) {
				statisticsRange = rangeValue
				statisticsStart = null
				statisticsEnd = null
				updateStatisticsTable()
			} else {
				overviewRange = rangeValue
				overviewStart = null
				overviewEnd = null
				updateOverviewCharts()
			}
		})
	})

	document.querySelectorAll('.custom-range-toggle').forEach((button) => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			panel.querySelector('.custom-range').hidden = false
			panel.querySelector('.custom-start-input').focus()
		})
	})

	document.querySelectorAll('.apply-custom-range-button').forEach((button) => {
		button.addEventListener('click', () => {
			const container = button.closest('.monitors-header')
			const panel = button.closest('.tab-panel')
			const startValue = localDateTimeToIso(
				container.querySelector('.custom-start-input').value,
			)
			const endValue = localDateTimeToIso(container.querySelector('.custom-end-input').value)
			if (!startValue || !endValue) {
				showNotification('Select both From and To for a custom range.', 'error')
				return
			}
			if (new Date(startValue).getTime() >= new Date(endValue).getTime()) {
				showNotification('From must be earlier than To.', 'error')
				return
			}
			panel
				.querySelectorAll('.range-button')
				.forEach((item) => item.classList.remove('active'))
			panel.querySelector('.custom-range-toggle').classList.add('active')
			if (panel.dataset.tab === 'statistics') {
				statisticsStart = startValue
				statisticsEnd = endValue
				updateStatisticsTable()
			} else {
				overviewStart = startValue
				overviewEnd = endValue
				updateOverviewCharts()
			}
		})
	})

	document.querySelectorAll('.export-csv-button').forEach((button) => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			const query =
				panel.dataset.tab === 'statistics' ? buildStatisticsQuery() : buildOverviewQuery()
			const endpoint =
				deviceProfile === 'fts-ls'
					? '/api/fts-ls/history/export.csv?'
					: '/api/history/export.csv?'
			window.location.href = endpoint + query
		})
	})
}

const SNMP_FIELD_LABELS = {
	status: 'Connection status',
	PiA: 'PiA',
	PoA: 'PoA',
	PiB: 'PiB',
	PoB: 'PoB',
	gain_set: 'Gain set',
	gain_actual: 'Gain actual',
	gain_delta: 'Gain delta',
	temperature: 'Temperature',
	seq_nr: 'Sequence nr',
}
