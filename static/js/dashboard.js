const navLinks = document.querySelectorAll('.nav-link')
const tabPanels = document.querySelectorAll('.tab-panel')
const currentTitle = document.getElementById('current-tab-title')

let dashboardSettings = null
let overviewRange = '5m'
let statisticsRange = '5m'
let powerChart = null
let gainChart = null
let deltaChart = null
let temperatureChart = null
let ftsOpticalPowerChart = null
let ftsLfNoiseChart = null
let ftsHfNoiseChart = null
let ftsJitterChart = null
let ftsLaserFrequencyChart = null
let ftsTecChart = null
let gainInputEdited = false
let currentUser = null
let overviewStart = null
let overviewEnd = null
let statisticsStart = null
let statisticsEnd = null
let latestNetwork = null
let lastOverviewChartRefresh = 0
let lastStatisticsRefresh = 0
let statisticsRequestController = null
let statisticsRequestSequence = 0
let overviewRequestController = null
let overviewRequestSequence = 0
let serviceSettingsDirty = false
let latestServiceDatabase = {}
let warningHistoryOffset = 0
let warningHistoryTotal = 0
let warningHistoryStart = null
let warningHistoryEnd = null
let lastWarningHistoryRefresh = 0
const warningHistoryLimit = 100
const chartSeriesVisibility = new Map()
const deviceProfile = document.body.dataset.deviceProfile || 'amplifier'
let latestFtsStatus = null

function historyRefreshInterval(rangeValue) {
	return {
		'5m': 3000,
		'1h': 3000,
		'24h': 10000,
		'7d': 15000,
		'30d': 30000,
		'all': 60000,
	}[rangeValue] || 3000
}

function formatDbm(value) {
	if (value === null || value === undefined) return '-- dBm'
	return Number(value).toFixed(2) + ' dBm'
}

function formatDb(value) {
	if (value === null || value === undefined) return '-- dB'
	return Number(value).toFixed(2) + ' dB'
}

function formatTemperature(value) {
	if (value === null || value === undefined) return '-- \u00B0C'
	return Number(value).toFixed(2) + ' \u00B0C'
}

function formatTime(value) {
	if (!value) return '--'
	return new Date(value).toLocaleTimeString()
}

function formatPlainNumber(value, digits = 2) {
	if (value === null || value === undefined || value === '') return '--'
	const numeric = Number(value)
	return Number.isFinite(numeric) ? numeric.toFixed(digits) : String(value)
}

function localDateTimeToIso(value) {
	if (!value) return null
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return null
	return date.toISOString()
}

function buildRangeQuery(rangeValue, startValue, endValue) {
	const params = new URLSearchParams({ range: rangeValue })

	if (startValue) {
		params.set('start', startValue)
	}

	if (endValue) {
		params.set('end', endValue)
	}

	return params.toString()
}

function buildOverviewQuery() {
	return buildRangeQuery(overviewRange, overviewStart, overviewEnd)
}

function buildStatisticsQuery() {
	return buildRangeQuery(statisticsRange, statisticsStart, statisticsEnd)
}

function escapeHtml(value) {
	return String(value)
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#039;')
}

function showNotification(message, type = 'success') {
	const container = document.getElementById('notification-container')
	if (!container) return
	const notification = document.createElement('div')
	notification.className = `notification ${type}`
	notification.setAttribute('role', type === 'error' ? 'alert' : 'status')
	notification.textContent = message
	container.appendChild(notification)
	window.setTimeout(() => notification.remove(), 5000)
}

function apiErrorMessage(detail, fallback) {
	if (typeof detail === 'string' && detail.trim()) return detail
	if (Array.isArray(detail)) {
		const messages = detail
			.map(item => {
				if (!item || typeof item !== 'object') return String(item || '')
				const location = Array.isArray(item.loc)
					? item.loc.filter(part => part !== 'body').join('.')
					: ''
				const message = typeof item.msg === 'string' ? item.msg : JSON.stringify(item)
				return location ? `${location}: ${message}` : message
			})
			.filter(Boolean)
		if (messages.length) return messages.join('; ')
	}
	if (detail && typeof detail === 'object') {
		if (typeof detail.message === 'string') return detail.message
		try {
			return JSON.stringify(detail)
		} catch {
			// Fall through to the caller-provided message.
		}
	}
	return fallback
}

function firstValue(object, keys, fallback = null) {
	for (const key of keys) {
		if (object && object[key] !== undefined && object[key] !== null && object[key] !== '') return object[key]
	}
	return fallback
}

function displayValue(value, unit = '') {
	if (value === null || value === undefined || value === '') return '--'
	if (typeof value === 'boolean') return value ? 'ON' : 'OFF'
	return `${value}${unit}`
}

function displayMeasurement(value, unit) {
	if (value === null || value === undefined || value === '') return '--'
	if (typeof value === 'boolean') return value ? 'ON' : 'OFF'
	const raw = String(value).trim()
	if (!raw || raw === '-' || raw === '--') return '--'
	const numeric = raw.match(/^[-+]?\d+(?:[.,]\d+)?/)
	if (!numeric) return raw
	return `${numeric[0].replace(',', '.')} ${unit}`
}

function ftsStateClass(value) {
	const normalized = String(value ?? 'unknown').trim().toLowerCase()
	if (['locked', 'on', 'ok', 'true', 'present', 'allowed'].includes(normalized)) return normalized === 'true' ? 'on' : normalized
	if (['unlocked', 'off', 'false', 'absent'].includes(normalized)) return normalized === 'false' ? 'off' : normalized
	if (normalized === 'shutdown') return 'shutdown'
	return 'unknown'
}

function setFtsState(id, value) {
	const element = document.getElementById(id)
	if (!element) return
	element.textContent = displayValue(value)
	element.className = `fts-state ${ftsStateClass(value)}`
}

function ftsMetric(label, value, unit = '') {
	return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(displayValue(value, unit))}</dd></div>`
}

function ftsModuleTarget(module, index, uplink = false) {
	if (uplink) return 'ul'
	const nameMatch = String(module?.name || '').match(/(?:port|p)\s*([0-9]+)/i)
	return `port${nameMatch ? nameMatch[1] : index + 1}`
}

function ftsModuleIsEquipped(module) {
	const type = String(firstValue(module, ['type'], 'Unknown')).toLowerCase()
	const stateValue = String(firstValue(module, ['state'], 'UNKNOWN')).toLowerCase()
	return !type.includes('unequipped') && stateValue !== 'unequipped'
}

function ftsConnectorLabel(connector) {
	const labels = {
		O: 'Optical',
		BN: 'Beat note',
		BNA: 'Amplified beat note',
		BN_A: 'Amplified beat note',
		TR: 'Tracking oscillator output',
	}
	return labels[connector] || connector
}

function ftsConnectorCode(connector) {
	return connector === 'BN_A' ? 'BNA' : connector
}

function renderFtsModule(module, index, uplink = false) {
	const stateValue = firstValue(module, ['state'], 'UNKNOWN')
	const stateClass = ftsStateClass(stateValue)
	const type = firstValue(module, ['type'], 'Unknown')
	const unequipped = !ftsModuleIsEquipped(module)
	const target = ftsModuleTarget(module, index, uplink)
	const slotLabel = uplink ? 'UPLINK' : `SLOT ${index + 1}`
	const metrics = []
	if (!unequipped) {
		metrics.push(ftsMetric('Optical input', displayMeasurement(firstValue(module, ['optical_power_display', 'optical_power']), 'dBm')))
		metrics.push(ftsMetric('LF / HF noise', `${displayValue(firstValue(module, ['noise_lf']))} / ${displayValue(firstValue(module, ['noise_hf']))}`))
		if (firstValue(module, ['jitter']) !== null) metrics.push(ftsMetric('Jitter', displayMeasurement(firstValue(module, ['jitter']), '%')))
		if (firstValue(module, ['distance_km', 'equivalent_distance']) !== null) metrics.push(ftsMetric('Equivalent distance', displayMeasurement(firstValue(module, ['distance_km', 'equivalent_distance']), 'km')))
	}
	const connectors = (module.connectors || []).map(connector => `
		<span class="fts-connector" title="${escapeHtml(ftsConnectorLabel(connector))}">
			<span class="fts-connector-socket" aria-hidden="true"></span>
			<span>${escapeHtml(ftsConnectorCode(connector))}</span>
		</span>`).join('')
	return `
		<article class="fts-module fts-pluggable-module ${stateClass} ${unequipped ? 'unequipped' : ''}" data-fts-module-target="${escapeHtml(target)}"${unequipped ? '' : ' tabindex="0"'}>
			<div class="fts-slot-label">${escapeHtml(slotLabel)}</div>
			<div class="fts-module-title"><span class="fts-led ${stateClass}"></span><strong>${escapeHtml(module.name || slotLabel)}</strong><small>${escapeHtml(type)}</small></div>
			<dl class="fts-metrics">
				${ftsMetric('State', stateValue)}
				${metrics.join('')}
				${ftsMetric('Description', firstValue(module, ['description']))}
			</dl>
			<div class="fts-port-connectors">${connectors || '<span class="fts-no-connectors">No physical ports</span>'}</div>
		</article>`
}

function syncFtsModuleTargets(modules) {
	const select = document.getElementById('fts-target')
	if (!select) return
	const selected = select.value
	select.replaceChildren(...modules.map(({ module, index, uplink }) => {
		const option = document.createElement('option')
		option.value = ftsModuleTarget(module, index, uplink)
		option.textContent = `${module.name || (uplink ? 'UL' : `P${index + 1}`)} · ${firstValue(module, ['type'], 'Unknown')}`
		option.disabled = !ftsModuleIsEquipped(module)
		return option
	}))
	if ([...select.options].some(option => option.value === selected && !option.disabled)) select.value = selected
	else select.value = [...select.options].find(option => !option.disabled)?.value || ''
}

function highlightSelectedFtsModule() {
	const selected = document.getElementById('fts-target')?.value
	document.querySelectorAll('[data-fts-module-target]').forEach(module => {
		module.classList.toggle('selected', Boolean(selected) && module.dataset.ftsModuleTarget === selected)
	})
}

function renderFtsStatus(status) {
	if (!status) return
	latestFtsStatus = status
	const laser = status.laser || {}
	const synth = status.synth || {}
	const tec = status.tec || {}
	const laserState = firstValue(laser, ['state', 'status'], '--')
	setTextIfExists('fts-laser-state', displayValue(laserState))
	setTextIfExists('fts-laser-frequency', displayMeasurement(firstValue(laser, ['optical_frequency', 'frequency', 'current_frequency']), 'GHz'))
	setTextIfExists('fts-laser-wavelength', displayMeasurement(firstValue(laser, ['optical_wavelength', 'wavelength']), 'nm'))
	setTextIfExists('fts-laser-centre', displayMeasurement(firstValue(laser, ['central_frequency_set', 'central_frequency']), 'GHz'))
	setTextIfExists('fts-laser-span', displayMeasurement(firstValue(laser, ['scanning_frequency_span_set', 'frequency_span']), 'MHz'))
	const laserLed = document.getElementById('fts-laser-led')
	if (laserLed) laserLed.className = `fts-led ${ftsStateClass(laserState)}`

	const synthState = firstValue(synth, ['status', 'state'], '--')
	setTextIfExists('fts-synth-state', displayValue(synthState))
	setTextIfExists('fts-synth-reference', displayValue(firstValue(synth, ['10_mhz_reference_source', 'reference_source', 'reference'])))
	setTextIfExists('fts-synth-external', displayValue(firstValue(synth, ['external_10_mhz', 'external_frequency'])))
	const synthLed = document.getElementById('fts-synth-led')
	if (synthLed) synthLed.className = `fts-led ${ftsStateClass(synthState)}`

	const tecState = firstValue(tec, ['status', 'state'], '--')
	setTextIfExists('fts-tec-state', displayValue(tecState))
	setTextIfExists('fts-tec-temperature', `${displayMeasurement(firstValue(tec, ['temperature_set_c', 'temperature_set']), '°C')} / ${displayMeasurement(firstValue(tec, ['temperature_read_c', 'temperature_read']), '°C')}`)
	setTextIfExists('fts-tec-power', displayMeasurement(firstValue(tec, ['power_usage_percent', 'power_usage']), '%'))
	const tecLed = document.getElementById('fts-tec-led')
	if (tecLed) tecLed.className = `fts-led ${ftsStateClass(tecState)}`

	const power = status.power || {}
	setFtsState('fts-power-a', firstValue(power, ['a', 'power_a'], '--'))
	setFtsState('fts-power-b', firstValue(power, ['b', 'power_b'], '--'))
	const inventory = [
		...(status.uplink ? [{ module: status.uplink, index: 0, uplink: true }] : []),
		...(status.ports || []).map((module, index) => ({ module, index, uplink: false })),
	]
	const portPositions = inventory.filter(item => !item.uplink)
	const equippedPorts = portPositions.filter(item => ftsModuleIsEquipped(item.module))
	const uplinkEquipped = inventory.some(item => item.uplink && ftsModuleIsEquipped(item.module))
	const slotCount = portPositions.length
	const modules = document.getElementById('fts-modules')
	if (modules) {
		modules.innerHTML = inventory.length
			? inventory.map(item => renderFtsModule(item.module, item.index, item.uplink)).join('')
			: '<p class="fts-empty-rack">No optical modules were reported by the station.</p>'
	}
	setTextIfExists('fts-equipped-count', `${equippedPorts.length} / ${slotCount} positions equipped`)
	setTextIfExists('fts-rack-summary', `${equippedPorts.length} of ${slotCount} configurable port positions equipped; uplink ${uplinkEquipped ? 'present' : 'unavailable'}.`)
	setTextIfExists('fts-module-inventory', inventory.length ? `UL + ${equippedPorts.length} of ${slotCount} modular ports equipped` : 'No module inventory received')
	syncFtsModuleTargets(inventory)
	highlightSelectedFtsModule()
	updateFtsSettingsForms()
}

function formatDateTime(value) {
	if (!value) return '--'
	const date = new Date(value)
	return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function formatDuration(seconds) {
	if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '--'
	const total = Math.max(0, Math.round(Number(seconds)))
	const hours = Math.floor(total / 3600)
	const minutes = Math.floor((total % 3600) / 60)
	const remainingSeconds = total % 60
	if (hours) return `${hours} h ${minutes} min`
	if (minutes) return `${minutes} min ${remainingSeconds} s`
	return `${remainingSeconds} s`
}

async function responseError(response, fallback) {
	try {
		const body = await response.json()
		return new Error(apiErrorMessage(body.detail, fallback))
	} catch {
		return new Error(fallback)
	}
}

function valueOrNull(input) {
	if (!input || input.value === '') return null
	return Number(input.value)
}

function setInputValue(selector, value) {
	const input = document.querySelector(selector)
	if (!input) return
	input.value = value === null || value === undefined ? '' : value
}

function setTextIfExists(id, value) {
	const element = document.getElementById(id)
	if (element) element.textContent = value
}

function handleAuthResponse(response) {
	if (response.status === 401) {
		currentUser = null
		showLogin()
		throw new Error('Not authenticated')
	}

	if (response.status === 403) {
		throw new Error('Not allowed')
	}
}

function isAdministrator() {
	return currentUser && currentUser.role === 'Administrator'
}

function canOperate() {
	return currentUser && (currentUser.role === 'Administrator' || currentUser.role === 'Operator')
}

function setActiveTab(tabName) {
	const targetLink = document.querySelector(`.nav-link[data-tab="${tabName}"]`)
	if (
		!targetLink ||
		(targetLink.hasAttribute('data-admin-only') && !isAdministrator()) ||
		(targetLink.hasAttribute('data-operator-only') && !canOperate())
	) {
		return false
	}

	navLinks.forEach(item => item.classList.remove('active'))
	targetLink.classList.add('active')

	tabPanels.forEach(panel => {
		panel.classList.toggle('active', panel.dataset.tab === tabName)
	})

	currentTitle.textContent = targetLink.dataset.title

	if (tabName === 'overview') updateOverviewCharts()
	if (tabName === 'statistics') updateStatisticsTable()
	if (tabName === 'warnings') updateWarningsTable(true)
	if (tabName === 'access-control') loadAccessUsers()
	if (tabName === 'snmp-settings') loadSnmpSettings()
	if (tabName === 'network-settings') loadNetworkSettings()
	if (tabName === 'ntp-settings') loadNtpStatus()
	if (tabName === 'service-diagnostics') loadServiceDiagnostics()
	return true
}

function restoreTabFromUrl() {
	const requestedTab = decodeURIComponent(window.location.hash.slice(1))
	const tabName = requestedTab || 'standard-view'

	if (!setActiveTab(tabName)) {
		setActiveTab('standard-view')
		history.replaceState(null, '', `${window.location.pathname}${window.location.search}#standard-view`)
	}
}

function applyRoleUi() {
	document.querySelectorAll('[data-admin-only]').forEach(element => {
		element.hidden = !isAdministrator()
	})

	document.querySelectorAll('[data-operator-control]').forEach(element => {
		element.disabled = !canOperate()
	})

	document.querySelectorAll('[data-operator-only]').forEach(element => {
		element.hidden = !canOperate()
	})

	if (currentUser) {
		setTextIfExists('current-user-label', `${currentUser.username} (${currentUser.role})`)
	}

	const activeTab = document.querySelector('.tab-panel.active')
	if (
		activeTab &&
		((activeTab.hasAttribute('data-admin-only') && !isAdministrator()) ||
			(activeTab.hasAttribute('data-operator-only') && !canOperate()))
	) {
		setActiveTab('standard-view')
	}
}

function showLogin() {
	document.getElementById('login-screen').classList.remove('app-hidden')
	document.getElementById('app-layout').classList.add('app-hidden')
}

function showApp() {
	document.getElementById('login-screen').classList.add('app-hidden')
	document.getElementById('app-layout').classList.remove('app-hidden')
}

navLinks.forEach(link => {
	link.addEventListener('click', () => {
		const targetTab = link.dataset.tab
		if (!setActiveTab(targetTab)) return
		history.pushState(null, '', `${window.location.pathname}${window.location.search}#${encodeURIComponent(targetTab)}`)
	})
})

window.addEventListener('popstate', () => {
	if (currentUser) restoreTabFromUrl()
})

function selectedNetworkInterface() {
	const name = document.getElementById('network-interface')?.value
	return latestNetwork?.interfaces?.find(item => item.name === name) || null
}

function showNetworkMessage(message, isError = false) {
	const element = document.getElementById('network-message')
	if (!element) return
	element.textContent = message
	element.classList.toggle('error', isError)
}

function networkMdnsUrl(network = latestNetwork) {
	const hostname = network?.mdns_hostname
	if (!hostname) return ''
	const port = window.location.port ? `:${window.location.port}` : ''
	return `${window.location.protocol}//${hostname}${port}`
}

function networkOriginUsesHostname() {
	const hostname = window.location.hostname.toLowerCase().replace(/\.$/, '')
	if (
		hostname === 'localhost' ||
		hostname === '127.0.0.1' ||
		hostname === '::1' ||
		hostname === '[::1]'
	)
		return true
	const isIpv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname)
	const isIpv6 = hostname.includes(':')
	return !isIpv4 && !isIpv6
}

function wait(milliseconds) {
	return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

async function confirmNetworkChangeWithRetry(token, rollbackSeconds) {
	const retryWindowSeconds = Math.max(5, Number(rollbackSeconds || 60) - 10)
	const deadline = Date.now() + retryWindowSeconds * 1000
	let lastError = new Error('The new network address did not become reachable.')

	while (Date.now() < deadline) {
		const controller = new AbortController()
		const timeout = window.setTimeout(() => controller.abort(), 4000)
		try {
			const response = await fetch('/api/network/confirm', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ token }),
				cache: 'no-store',
				signal: controller.signal,
			})
			handleAuthResponse(response)
			const data = await response.json()
			if (response.ok) return data
			if ([400, 401, 403].includes(response.status)) {
				const rejection = new Error(
					apiErrorMessage(data.detail, 'Network confirmation was rejected.'),
				)
				rejection.retryable = false
				throw rejection
			}
			lastError = new Error(
				apiErrorMessage(
					data.detail,
					`Network confirmation failed with HTTP ${response.status}.`,
				),
			)
		} catch (error) {
			lastError = error
			if (error.retryable === false || ['Not authenticated', 'Not allowed'].includes(error.message)) throw error
		} finally {
			window.clearTimeout(timeout)
		}
		await wait(1500)
	}

	throw new Error(
		`${lastError.message || 'The new address is unreachable.'} The previous network settings will be restored automatically.`,
	)
}

function updateNetworkStaticFields() {
	const form = document.getElementById('network-form')
	const container = document.getElementById('network-static-fields')
	if (!form || !container) return
	const isStatic = form.elements.mode.value === 'static'
	container.classList.toggle('is-expanded', isStatic)
	container.setAttribute('aria-hidden', String(!isStatic))
	container.querySelectorAll('input').forEach(input => {
		input.disabled = !isStatic
		input.required = isStatic && input.name !== 'dns'
	})
}

function fillNetworkForm(item) {
	const form = document.getElementById('network-form')
	if (!form) return
	form.elements.mode.value = item?.mode === 'static' ? 'static' : 'dhcp'
	form.elements.ip_address.value = item?.ip_address || ''
	form.elements.netmask.value = item?.netmask || ''
	form.elements.gateway.value = item?.gateway || ''
	form.elements.dns.value = item?.dns?.join(', ') || ''
	setTextIfExists('network-link-state', item?.state || '--')
	setTextIfExists('network-current-ip', item?.ip_address || 'None')
	setTextIfExists('network-current-subnet', item?.netmask ? `${item.netmask} (/${item.prefix})` : 'None')
	setTextIfExists('network-current-gateway', item?.gateway || 'None')
	setTextIfExists('network-current-mode', item?.mode || 'Unknown')
	setTextIfExists('network-current-dns', item?.dns?.join(', ') || 'None')
	updateNetworkStaticFields()
}

async function loadNetworkSettings() {
	showNetworkMessage('Loading network settings...')
	try {
		const response = await fetch('/api/network')
		handleAuthResponse(response)
		const data = await response.json()
		if (!response.ok) {
			throw new Error(apiErrorMessage(data.detail, 'Could not read network settings'))
		}
		latestNetwork = data
		const select = document.getElementById('network-interface')
		const accessInterfaceAvailable =
			data.access_interface &&
			data.interfaces.some(item => item.name === data.access_interface)
		select.innerHTML = data.interfaces
			.map(
				item =>
					`<option value="${escapeHtml(item.name)}"${accessInterfaceAvailable && item.name !== data.access_interface ? ' disabled' : ''}>${escapeHtml(item.name)} (${escapeHtml(item.mac || 'no MAC')})</option>`,
			)
			.join('')
		select.value = data.selected_interface || data.interfaces[0]?.name || ''
		if (accessInterfaceAvailable) {
			select.value = data.access_interface
		}
		fillNetworkForm(selectedNetworkInterface())
		const mdnsUrl = networkMdnsUrl(data)
		const mdnsLink = document.getElementById('network-mdns-url')
		if (mdnsLink) {
			mdnsLink.textContent = mdnsUrl || '--'
			mdnsLink.href = mdnsUrl || '#'
		}
		document.getElementById('save-network-button').disabled = !data.supported || !isAdministrator()
		const originHint = networkOriginUsesHostname()
			? ''
			: ` Open ${mdnsUrl} before changing the network address.`
		showNetworkMessage(
			(data.message || `Host: ${data.hostname}; backend: ${data.backend}.`) + originHint,
		)
	} catch (error) {
		showNetworkMessage(error.message, true)
	}
}

document
	.getElementById('network-interface')
	?.addEventListener('change', () => fillNetworkForm(selectedNetworkInterface()))
document.getElementById('network-mode')?.addEventListener('change', updateNetworkStaticFields)
document.getElementById('refresh-network-button')?.addEventListener('click', loadNetworkSettings)
document.getElementById('network-form')?.addEventListener('submit', async event => {
	event.preventDefault()
	if (!isAdministrator()) return
	const form = event.currentTarget
	const payload = Object.fromEntries(new FormData(form).entries())
	const currentInterface = selectedNetworkInterface()
	const addressMayChange =
		payload.mode === 'dhcp' ||
		String(payload.ip_address || '').trim() !== String(currentInterface?.ip_address || '').trim()
	if (!networkOriginUsesHostname() && addressMayChange) {
		const mdnsUrl = networkMdnsUrl()
		const message = `For a safe IP change, reopen Amp Panel at ${mdnsUrl || 'its .local address'} and sign in there first.`
		showNetworkMessage(message, true)
		showNotification(message, 'error')
		return
	}
	if (!confirm('Apply the new network settings? The connection may be interrupted.')) return
	let rollbackSeconds = null
	showNetworkMessage('Applying settings...')
	try {
		const response = await fetch('/api/network', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		})
		handleAuthResponse(response)
		const data = await response.json()
		if (!response.ok) {
			throw new Error(apiErrorMessage(data.detail, 'Could not apply network settings'))
		}
		const confirmation = data.confirmation
		if (!confirmation?.token) {
			throw new Error('The host did not return a network rollback confirmation token.')
		}
		rollbackSeconds = confirmation.expires_in_seconds
		showNetworkMessage(
			`Connection still works. Confirming the change before the ${rollbackSeconds}-second rollback timeout...`,
		)
		const confirmedData = await confirmNetworkChangeWithRetry(
			confirmation.token,
			confirmation.expires_in_seconds,
		)
		latestNetwork = confirmedData
		rollbackSeconds = null
		fillNetworkForm(selectedNetworkInterface())
		showNetworkMessage('Network settings applied and confirmed.')
		showNotification('Network settings applied and confirmed.')
	} catch (error) {
		const message = rollbackSeconds
			? `${error.message || 'Confirmation failed.'} NetworkManager will automatically restore the previous settings within ${rollbackSeconds} seconds.`
			: error instanceof TypeError
				? 'The connection was interrupted. If the host received the change, NetworkManager will automatically restore the previous settings within 60 seconds.'
				: error.message || 'Could not apply network settings.'
		showNetworkMessage(message, true)
		showNotification(message, 'error')
	}
})

function showNtpMessage(message, isError = false) {
	const element = document.getElementById('ntp-message')
	if (!element) return
	element.textContent = message
	element.classList.toggle('error', isError)
}

async function loadNtpStatus(force = false) {
	if (!document.getElementById('ntp-server')) return
	showNtpMessage(force ? 'Querying NTP server...' : 'Loading NTP status...')
	try {
		const response = await fetch(`/api/ntp/status${force ? '?force=true' : ''}`)
		handleAuthResponse(response)
		const data = await response.json()
		if (!response.ok) throw new Error(data.detail || 'Could not read NTP status')

		setTextIfExists('ntp-server', `${data.server}${data.port ? ':' + data.port : ''}`)
		setTextIfExists('ntp-reachable', data.reachable ? 'Yes' : 'No')
		setTextIfExists(
			'ntp-stratum',
			data.stratum !== undefined ? `${data.stratum} (${data.stratum_label || '--'})` : '--',
		)
		setTextIfExists('ntp-reference-id', data.reference_id || '--')
		setTextIfExists('ntp-leap-indicator', data.leap_indicator_label || '--')
		setTextIfExists(
			'ntp-reference-time',
			data.reference_time_utc ? new Date(data.reference_time_utc).toLocaleString() : '--',
		)
		setTextIfExists(
			'ntp-offset',
			data.offset_ms !== undefined && data.offset_ms !== null ? `${data.offset_ms} ms` : '--',
		)
		setTextIfExists(
			'ntp-round-trip',
			data.round_trip_ms !== undefined && data.round_trip_ms !== null ? `${data.round_trip_ms} ms` : '--',
		)
		setTextIfExists(
			'ntp-root-delay',
			data.root_delay_ms !== undefined && data.root_delay_ms !== null
				? `${data.root_delay_ms} ms / ${data.root_dispersion_ms} ms`
				: '--',
		)
		setTextIfExists('ntp-poll-interval', data.poll_interval_seconds ? `${data.poll_interval_seconds} s` : '--')
		setTextIfExists('ntp-checked-at', data.checked_at ? new Date(data.checked_at).toLocaleString() : '--')

		if (data.reachable) {
			showNtpMessage(`Synchronized with ${data.server}.`)
		} else {
			showNtpMessage(data.error || 'NTP server unreachable.', true)
		}
	} catch (error) {
		showNtpMessage(error.message, true)
	}
}

document.getElementById('refresh-ntp-button')?.addEventListener('click', () => loadNtpStatus(true))

function updateDatabaseStatus(database = {}) {
	setTextIfExists('status-database-records', String(database.records ?? 0))
}

function formatBytes(bytes) {
	const value = Number(bytes)
	if (!Number.isFinite(value)) return '--'
	if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
	if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MiB`
	return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

function formatDuration(seconds) {
	const value = Number(seconds)
	if (!Number.isFinite(value) || value < 0) return '--'
	if (value < 60) return `${Math.max(0, Math.round(value))} seconds`
	if (value < 3600) return `${(value / 60).toFixed(1)} minutes`
	if (value < 86400) return `${(value / 3600).toFixed(1)} hours`
	if (value < 365 * 86400) return `${(value / 86400).toFixed(1)} days`
	return `${(value / (365 * 86400)).toFixed(1)} years`
}

function formatSampleRate(rate) {
	const value = Number(rate)
	if (!Number.isFinite(value) || value <= 0) return 'Waiting for samples'
	if (value >= 1) return `${value.toFixed(2)} records/s`
	return `1 record / ${(1 / value).toFixed(1)} s`
}

function updateServiceSettingsVisibility() {
	const unlimited = document.getElementById('service-unlimited-history-input')?.checked
	const heartbeatEnabled = document.getElementById('service-heartbeat-enabled-input')?.checked
	const limitField = document.getElementById('service-database-limit-field')
	const heartbeatField = document.getElementById('service-heartbeat-field')
	if (limitField) limitField.hidden = unlimited
	if (heartbeatField) heartbeatField.hidden = !heartbeatEnabled
	updateDatabaseLimitPreview()
}

function updateDatabaseLimitPreview() {
	const preview = document.getElementById('service-database-limit-preview')
	if (!preview) return
	if (document.getElementById('service-unlimited-history-input')?.checked) {
		preview.textContent = 'No records will be removed automatically. Available disk space is the only limit.'
		return
	}
	const limit = Number(document.getElementById('service-database-limit-input')?.value)
	const rate = Number(latestServiceDatabase.sample_rate_per_second)
	const records = Number(latestServiceDatabase.records || 0)
	if (!Number.isFinite(limit) || limit < 1) {
		preview.textContent = 'Enter a limit between 1 and 10,000,000 records.'
		return
	}
	if (!Number.isFinite(rate) || rate <= 0) {
		preview.textContent = 'The time estimate will appear after at least two samples are stored.'
		return
	}
	const capacity = formatDuration(limit / rate)
	const remaining = formatDuration(Math.max(0, limit - records) / rate)
	preview.textContent = `About ${capacity} of history; oldest records start being removed in ${remaining}.`
}

async function loadServiceDiagnostics() {
	if (!isAdministrator() || !document.getElementById('service-database-state')) return
	try {
		const response = await fetch('/api/service-diagnostics')
		handleAuthResponse(response)
		const data = await response.json()
		if (!response.ok) throw new Error(data.detail || 'Could not read service diagnostics')
		const serial = data.serial || {}
		const database = data.database || {}
		const syslog = data.syslog || {}
		latestServiceDatabase = database
		setTextIfExists('service-serial-state', serial.connected ? 'CONNECTED' : 'DISCONNECTED')
		setTextIfExists('service-serial-port', serial.port || '--')
		setTextIfExists('service-serial-baudrate', String(serial.baudrate ?? '--'))
		setTextIfExists('service-serial-error', serial.error || 'None')
		const serialPortInput = document.getElementById('service-serial-port-input')
		if (serialPortInput && !serviceSettingsDirty) {
			const ports = Array.from(new Set([serial.port, ...(serial.available_ports || [])].filter(Boolean)))
			serialPortInput.replaceChildren(...ports.map(port => {
				const option = document.createElement('option')
				option.value = port
				option.textContent = port
				return option
			}))
			serialPortInput.value = serial.port || ports[0] || ''
		}
		setTextIfExists('service-database-state', String(database.state || '--').toUpperCase())
		setTextIfExists('service-database-records', String(database.records ?? 0))
		setTextIfExists(
			'service-database-limit',
			database.record_limit === 0 ? 'UNLIMITED' : `${database.record_limit ?? '--'} records`,
		)
		setTextIfExists('service-database-write-rate', formatSampleRate(database.sample_rate_per_second))
		setTextIfExists(
			'service-database-retention',
			database.record_limit === 0
				? 'Unlimited (disk space applies)'
				: formatDuration(database.estimated_retention_seconds),
		)
		setTextIfExists(
			'service-database-time-to-limit',
			database.record_limit === 0
				? 'Not applicable'
				: formatDuration(database.estimated_seconds_to_limit),
		)
		setTextIfExists(
			'service-database-disk-time',
			formatDuration(database.estimated_seconds_until_disk_full),
		)
		setTextIfExists('service-database-file', database.file || '--')
		setTextIfExists('service-database-size', formatBytes(database.size_bytes))
		setTextIfExists('service-database-free', formatBytes(database.filesystem_free_bytes))
		setTextIfExists('service-database-discarded', String(database.discarded_records_since_start ?? 0))
		setTextIfExists('service-database-error', database.error || 'None')
		setTextIfExists('service-syslog-local', syslog.local_enabled ? 'ENABLED' : 'DISABLED')
		setTextIfExists('service-syslog-destination', syslog.local_destination || '--')
		setTextIfExists('service-syslog-file', syslog.local_file || '--')
		setTextIfExists('service-syslog-remote', syslog.remote_enabled ? 'ENABLED' : 'DISABLED')
		setTextIfExists('service-syslog-host', syslog.remote_enabled ? `${syslog.remote_host}:${syslog.remote_port}` : 'Not configured')
		setTextIfExists('service-syslog-protocol', syslog.remote_enabled ? String(syslog.remote_protocol).toUpperCase() : '--')
		setTextIfExists('service-syslog-heartbeat', syslog.heartbeat_seconds > 0 ? `${syslog.heartbeat_seconds} s` : 'DISABLED')
		const heartbeatInput = document.getElementById('service-heartbeat-input')
		const databaseLimitInput = document.getElementById('service-database-limit-input')
		if (!serviceSettingsDirty) {
			const heartbeatEnabledInput = document.getElementById('service-heartbeat-enabled-input')
			const unlimitedHistoryInput = document.getElementById('service-unlimited-history-input')
			if (heartbeatEnabledInput) heartbeatEnabledInput.checked = syslog.heartbeat_seconds > 0
			if (unlimitedHistoryInput) unlimitedHistoryInput.checked = database.record_limit === 0
			if (heartbeatInput) heartbeatInput.value = syslog.heartbeat_seconds > 0 ? syslog.heartbeat_seconds : 300
			if (databaseLimitInput) {
				databaseLimitInput.value = database.record_limit > 0 ? database.record_limit : 250000
			}
			updateServiceSettingsVisibility()
		} else {
			updateDatabaseLimitPreview()
		}
	} catch (error) {
		setTextIfExists('service-database-state', 'API ERROR')
		console.error('Error loading service diagnostics:', error)
	}
}

document.getElementById('refresh-services-button')?.addEventListener('click', loadServiceDiagnostics)

const serviceSettingsForm = document.getElementById('service-settings-form')
serviceSettingsForm?.addEventListener('input', () => {
	serviceSettingsDirty = true
	updateServiceSettingsVisibility()
})

serviceSettingsForm?.addEventListener('submit', async event => {
	event.preventDefault()
	try {
		const heartbeatEnabled = document.getElementById('service-heartbeat-enabled-input').checked
		const unlimitedHistory = document.getElementById('service-unlimited-history-input').checked
		const response = await fetch('/api/service-diagnostics/settings', {
			method: 'PUT',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({
				serial_port: document.getElementById('service-serial-port-input').value,
				syslog_heartbeat_seconds: heartbeatEnabled
					? Number(document.getElementById('service-heartbeat-input').value)
					: 0,
				database_max_records: unlimitedHistory
					? 0
					: Number(document.getElementById('service-database-limit-input').value),
			}),
		})
		handleAuthResponse(response)
		const result = await response.json()
		if (!response.ok) throw new Error(result.detail || 'Could not save service settings')
		const suffix = result.pruned_records ? ` ${result.pruned_records} oldest database records were removed.` : ''
		showNotification(`Service settings saved.${suffix}`)
		serviceSettingsDirty = false
		await loadServiceDiagnostics()
	} catch (error) {
		showNotification(error.message || 'Could not save service settings.', 'error')
	}
})

async function loadSettings() {
	if (!currentUser) return

	const response = await fetch('/api/settings')
	handleAuthResponse(response)
	dashboardSettings = await response.json()
	updateSettingsForm()
}

async function checkAuth() {
	const response = await fetch('/api/auth/me')

	if (!response.ok) {
		currentUser = null
		showLogin()
		return false
	}

	const json = await response.json()
	currentUser = json.user
	applyRoleUi()
	showApp()
	restoreTabFromUrl()
	return true
}

async function login(username, password) {
	const response = await fetch('/api/auth/login', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ username, password }),
	})

	if (!response.ok) {
		let message = 'Invalid username or password'
		try {
			const body = await response.json()
			if (body.detail) message = body.detail
		} catch {}
		throw new Error(message)
	}

	const json = await response.json()
	currentUser = json.user
	applyRoleUi()
	showApp()
	restoreTabFromUrl()
}

async function logout() {
	await fetch('/api/auth/logout', { method: 'POST' })
	currentUser = null
	showLogin()
}

function updateSettingsForm() {
	if (!dashboardSettings) return

	const gainToleranceInput = document.getElementById('gain-tolerance-input')

	if (gainToleranceInput) {
		gainToleranceInput.value = dashboardSettings.gain_tolerance
	}
	const gainSetInput = document.getElementById('gain-set-input')
	if (gainSetInput && dashboardSettings.gain_set_limits) {
		gainSetInput.min = dashboardSettings.gain_set_limits.min
		gainSetInput.max = dashboardSettings.gain_set_limits.max
	}

	Object.entries(dashboardSettings.warn_limits || {}).forEach(([field, limits]) => {
		setInputValue(`[data-limit-field="${field}"][data-limit-side="min"]`, limits.min)
		setInputValue(`[data-limit-field="${field}"][data-limit-side="max"]`, limits.max)
	})
}

async function saveSettings() {
	if (!canOperate()) return

	const warnLimits = {}
	const gainInput = document.getElementById('gain-set-input')
	const gainValueText = gainInput.value.trim()

	document.querySelectorAll('[data-limit-field]').forEach(input => {
		const field = input.dataset.limitField
		const side = input.dataset.limitSide

		if (!warnLimits[field]) {
			warnLimits[field] = { min: null, max: null }
		}

		warnLimits[field][side] = valueOrNull(input)
	})
	Object.entries(warnLimits).forEach(([field, limits]) => {
		if (limits.min !== null && limits.max !== null && limits.min >= limits.max) {
			throw new Error(`${field}: MIN threshold must be lower than MAX threshold.`)
		}
	})

	const response = await fetch('/api/settings', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			gain_tolerance: Number(document.getElementById('gain-tolerance-input').value || 0),
			warn_limits: warnLimits,
		}),
	})
	handleAuthResponse(response)
	if (!response.ok) throw await responseError(response, 'Could not save thresholds')

	dashboardSettings = await response.json()
	updateSettingsForm()

	let gainError = null
	if (gainInputEdited && gainValueText !== '') {
		const gainResponse = await fetch('/api/set_gain', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ gain_set: Number(gainValueText) }),
		})
		handleAuthResponse(gainResponse)

		if (gainResponse.ok) {
			gainInputEdited = false
			gainInput.value = Number(gainValueText)
		} else {
			gainError = await responseError(gainResponse, 'Could not send gain setpoint to the device')
		}
	}

	return { gainError }
}

async function updateDashboard() {
	if (!currentUser) return

	try {
		const response = await fetch('/api/latest')
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		const data = json.data || {}
		if (deviceProfile === 'fts-ls') renderFtsStatus(json.fts_ls || data.fts_ls)

		setTextIfExists('PiA', formatDbm(data.PiA))
		setTextIfExists('PoA', formatDbm(data.PoA))
		setTextIfExists('PiB', formatDbm(data.PiB))
		setTextIfExists('PoB', formatDbm(data.PoB))
		setTextIfExists('gain-actual', formatDb(data.gain_actual))
		setTextIfExists('gain-delta', formatDb(data.gain_delta))
		setTextIfExists('temperature', formatTemperature(data.temperature))

		const gainSetValue = data.gain_set !== undefined ? data.gain_set : json.last_known_gain_set
		const gainInput = document.getElementById('gain-set-input')
		if (gainInput && document.activeElement !== gainInput && !gainInputEdited) {
			gainInput.value = gainSetValue === null || gainSetValue === undefined ? '' : Number(gainSetValue).toFixed(2)
		}

		setTextIfExists('status-last-update', formatTime(json.last_update))
		setTextIfExists('status-system-time', new Date().toLocaleTimeString())
		updateDatabaseStatus(json.database)

		const statusEl = document.getElementById('status-connection')

		if (json.connected) {
			statusEl.textContent = 'CONNECTED'
			statusEl.className = 'status-ok'
		} else {
			statusEl.textContent = 'DISCONNECTED'
			statusEl.className = 'status-error'
		}
	} catch (error) {
		const statusEl = document.getElementById('status-connection')
		statusEl.textContent = 'API ERROR'
		statusEl.className = 'status-error'
		updateDatabaseStatus({ state: 'error', ready: false, records: '--' })
		console.error('Error fetching /api/latest:', error)
	}
}

function renderActiveWarnings(warnings) {
	const body = document.getElementById('active-warnings-table-body')
	setTextIfExists('warning-count', String(warnings.length))
	setTextIfExists('fts-warning-count', String(warnings.length))
	if (!body) return
	if (!warnings.length) {
		body.innerHTML = '<tr><td colspan="7">No active warnings</td></tr>'
		return
	}
	body.innerHTML = warnings
		.map(warning => {
			const stateLabel = warning.acknowledged ? 'Acknowledged' : 'Open'
			const stateClass = warning.acknowledged
				? 'warning-state-acknowledged'
				: 'warning-state-open'
			return `
				<tr>
					<td>${escapeHtml(formatDateTime(warning.opened_at || warning.event_time))}</td>
					<td>${escapeHtml(warning.label || warning.field || '--')}</td>
					<td>${escapeHtml(formatPlainNumber(warning.value))}</td>
					<td>${escapeHtml(formatPlainNumber(warning.target))}</td>
					<td>${escapeHtml(formatPlainNumber(warning.delta))}</td>
					<td><span class="warning-state ${stateClass}">${stateLabel}</span></td>
					<td>${escapeHtml(warning.message || '--')}</td>
				</tr>
			`
		})
		.join('')
}

function warningHistoryQuery() {
	const range = document.getElementById('warning-range-filter')?.value || '24h'
	const field = document.getElementById('warning-field-filter')?.value || ''
	const status = document.getElementById('warning-status-filter')?.value || ''
	const params = new URLSearchParams({
		range,
		limit: String(warningHistoryLimit),
		offset: String(warningHistoryOffset),
	})
	if (field) params.set('field', field)
	if (status) params.set('status', status)
	if (range === 'custom') {
		if (warningHistoryStart) params.set('start', warningHistoryStart)
		if (warningHistoryEnd) params.set('end', warningHistoryEnd)
	}
	return params.toString()
}

function renderWarningHistory(data) {
	const events = data.history || []
	const body = document.getElementById('warning-history-table-body')
	warningHistoryTotal = Number(data.total || 0)
	if (body) {
		if (!data.source_available) {
			body.innerHTML = '<tr><td colspan="8">System warning log is not available</td></tr>'
		} else {
			const unreadableRow = Number(data.unreadable_files || 0) > 0
				? '<tr><td colspan="8">One or more rotated warning logs could not be read</td></tr>'
				: ''
			const eventRows = events
				.map(event => {
					const eventName = String(event.event || '').toUpperCase()
					const isCleared = eventName === 'CLEARED'
					return `
						<tr>
							<td>${escapeHtml(formatDateTime(event.event_time))}</td>
							<td><span class="warning-state ${isCleared ? 'warning-state-cleared' : 'warning-state-open'}">${isCleared ? 'Cleared' : 'Opened'}</span></td>
							<td>${escapeHtml(event.label || event.field || '--')}</td>
							<td>${escapeHtml(formatPlainNumber(event.value))}</td>
							<td>${escapeHtml(formatPlainNumber(event.target))}</td>
							<td>${escapeHtml(formatPlainNumber(event.delta))}</td>
							<td>${escapeHtml(formatDuration(event.duration_seconds))}</td>
							<td>${escapeHtml(event.message || '--')}</td>
						</tr>
					`
				})
				.join('')
			body.innerHTML = unreadableRow + (
				eventRows || '<tr><td colspan="8">No warning events in this range</td></tr>'
			)
		}
	}

	const first = warningHistoryTotal ? warningHistoryOffset + 1 : 0
	const last = Math.min(warningHistoryOffset + events.length, warningHistoryTotal)
	setTextIfExists('warning-history-count', `${warningHistoryTotal} events`)
	setTextIfExists('warning-page-status', `${first}–${last} of ${warningHistoryTotal}`)
	const previous = document.getElementById('warning-previous-page')
	const next = document.getElementById('warning-next-page')
	if (previous) previous.disabled = warningHistoryOffset === 0
	if (next) next.disabled = warningHistoryOffset + events.length >= warningHistoryTotal
}

async function updateWarningsTable(forceHistory = false) {
	if (!currentUser) return

	try {
		const response = await fetch('/api/errors')
		handleAuthResponse(response)
		if (!response.ok) throw await responseError(response, 'Could not read active warnings')
		const json = await response.json()
		renderActiveWarnings(json.errors || [])

		const warningsPanel = document.querySelector('.tab-panel[data-tab="warnings"]')
		const now = Date.now()
		if (
			!warningsPanel?.classList.contains('active') ||
			(!forceHistory && now - lastWarningHistoryRefresh < 15000)
		) {
			return
		}
		const historyResponse = await fetch(`/api/warnings?${warningHistoryQuery()}`)
		handleAuthResponse(historyResponse)
		if (!historyResponse.ok) {
			throw await responseError(historyResponse, 'Could not read warning history')
		}
		renderWarningHistory(await historyResponse.json())
		lastWarningHistoryRefresh = now
	} catch (error) {
		console.error('Error fetching warnings:', error)
		lastWarningHistoryRefresh = Date.now()
		const warningsPanel = document.querySelector('.tab-panel[data-tab="warnings"]')
		if (warningsPanel?.classList.contains('active')) {
			showNotification(error.message || 'Could not read warnings.', 'error')
		}
	}
}

function setupSettingsButtons() {
	const saveButton = document.getElementById('save-settings-button')
	const acknowledgeButton = document.getElementById('acknowledge-warnings-button')

	if (saveButton) {
		saveButton.addEventListener('click', async () => {
			try {
				const result = await saveSettings()
				if (result.gainError) {
					showNotification(`Thresholds saved, but gain setpoint was not sent: ${result.gainError.message}`, 'warning')
				} else {
					showNotification('Setpoints and thresholds saved.')
				}
			} catch (error) {
				showNotification(error.message || 'Could not save setpoints and thresholds.', 'error')
				console.error('Error saving setpoints and thresholds:', error)
			}
		})
	}

	if (acknowledgeButton) {
		acknowledgeButton.addEventListener('click', async () => {
			if (!canOperate()) return
			try {
				const response = await fetch('/api/warnings/acknowledge', { method: 'POST' })
				handleAuthResponse(response)
				if (!response.ok) throw await responseError(response, 'Could not acknowledge warnings')
				const data = await response.json()
				await updateWarningsTable(true)
				showNotification(`${data.acknowledged || 0} active warnings acknowledged.`)
			} catch (error) {
				showNotification(error.message, 'error')
			}
		})
	}
}

function setupWarningFilters() {
	const rangeFilter = document.getElementById('warning-range-filter')
	const customRange = document.getElementById('warning-custom-range')
	const refresh = () => {
		if (rangeFilter?.value === 'custom' && !warningHistoryStart) {
			showNotification('Select and apply a custom start time.', 'error')
			return
		}
		warningHistoryOffset = 0
		lastWarningHistoryRefresh = 0
		updateWarningsTable(true)
	}

	rangeFilter?.addEventListener('change', () => {
		if (customRange) customRange.hidden = rangeFilter.value !== 'custom'
		if (rangeFilter.value !== 'custom') refresh()
	})
	document.getElementById('warning-field-filter')?.addEventListener('change', refresh)
	document.getElementById('warning-status-filter')?.addEventListener('change', refresh)
	document.getElementById('refresh-warning-history-button')?.addEventListener('click', refresh)
	document.getElementById('apply-warning-range-button')?.addEventListener('click', () => {
		warningHistoryStart = localDateTimeToIso(
			document.getElementById('warning-start-input')?.value,
		)
		warningHistoryEnd = localDateTimeToIso(
			document.getElementById('warning-end-input')?.value,
		)
		if (!warningHistoryStart) {
			showNotification('Select a valid start time.', 'error')
			return
		}
		refresh()
	})
	document.getElementById('warning-previous-page')?.addEventListener('click', () => {
		warningHistoryOffset = Math.max(0, warningHistoryOffset - warningHistoryLimit)
		lastWarningHistoryRefresh = 0
		updateWarningsTable(true)
	})
	document.getElementById('warning-next-page')?.addEventListener('click', () => {
		if (warningHistoryOffset + warningHistoryLimit >= warningHistoryTotal) return
		warningHistoryOffset += warningHistoryLimit
		lastWarningHistoryRefresh = 0
		updateWarningsTable(true)
	})
}

async function loadAccessUsers() {
	if (!isAdministrator()) return

	try {
		const response = await fetch('/api/access/users')
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		const users = json.users || []
		const body = document.getElementById('access-users-table-body')

		setTextIfExists('access-users-count', `${users.length} users`)

		if (!body) return

		if (!users.length) {
			body.innerHTML = '<tr><td colspan="4">No users</td></tr>'
			return
		}

		body.innerHTML = users
			.map(user => {
				const username = escapeHtml(user.username)
				const role = escapeHtml(user.role)
				const activeChecked = user.active ? 'checked' : ''

				return `
                <tr data-username="${username}">
                    <td>${username}</td>
                    <td>
                        <select data-access-role>
                            <option value="Administrator" ${role === 'Administrator' ? 'selected' : ''}>Administrator</option>
                            <option value="Operator" ${role === 'Operator' ? 'selected' : ''}>Operator</option>
                            <option value="Viewer" ${role === 'Viewer' ? 'selected' : ''}>Viewer</option>
                        </select>
                    </td>
                    <td>
                        <label class="table-toggle">
                            <input data-access-active type="checkbox" ${activeChecked}>
                            Active
                        </label>
                    </td>
                    <td>
                        <div class="action-buttons">
                            <button data-access-save type="button">Save</button>
                            <button data-access-delete type="button">Delete</button>
                        </div>
                    </td>
                </tr>
            `
			})
			.join('')
	} catch (error) {
		console.error('Error loading access users:', error)
	}
}

function getAccessRowPayload(row) {
	return {
		role: row.querySelector('[data-access-role]').value,
		active: row.querySelector('[data-access-active]').checked,
	}
}

function setupAccessControl() {
	const form = document.getElementById('access-user-form')
	const tableBody = document.getElementById('access-users-table-body')

	if (form) {
		form.addEventListener('submit', async event => {
			event.preventDefault()
			if (!isAdministrator()) return

			const usernameInput = document.getElementById('access-username-input')
			const roleInput = document.getElementById('access-role-input')
			const activeInput = document.getElementById('access-active-input')

			const username = usernameInput.value.trim()
			try {
				const response = await fetch('/api/access/users', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						username,
						role: roleInput.value,
						active: activeInput.checked,
					}),
				})
				handleAuthResponse(response)

				if (!response.ok) throw await responseError(response, 'Could not add user')

				form.reset()
				activeInput.checked = true
				await loadAccessUsers()
				showNotification(`User "${username}" added.`)
			} catch (error) {
				showNotification(error.message, 'error')
				console.error('Error adding access user:', error)
			}
		})
	}

	if (tableBody) {
		tableBody.addEventListener('click', async event => {
			const row = event.target.closest('tr[data-username]')
			if (!row) return

			const username = row.dataset.username

			if (event.target.matches('[data-access-save]')) {
				if (!isAdministrator()) return

				try {
					const response = await fetch(`/api/access/users/${encodeURIComponent(username)}`, {
						method: 'PUT',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify(getAccessRowPayload(row)),
					})
					handleAuthResponse(response)

					if (!response.ok) throw await responseError(response, 'Could not update user')

					await loadAccessUsers()
					showNotification(`User "${username}" saved.`)
				} catch (error) {
					showNotification(error.message, 'error')
					console.error('Error saving access user:', error)
				}
			}

			if (event.target.matches('[data-access-delete]')) {
				if (!isAdministrator()) return

				if (!confirm(`Delete user "${username}"?`)) return

				try {
					const response = await fetch(`/api/access/users/${encodeURIComponent(username)}`, {
						method: 'DELETE',
					})
					handleAuthResponse(response)

					if (!response.ok) throw await responseError(response, 'Could not delete user')

					await loadAccessUsers()
					showNotification(`User "${username}" deleted.`)
				} catch (error) {
					showNotification(error.message, 'error')
					console.error('Error deleting access user:', error)
				}
			}
		})
	}
}

function getFullTimestamps(points) {
	return points.map(point => {
		const date = new Date(point.time)
		if (Number.isNaN(date.getTime())) return point.time || ''
		const pad = number => String(number).padStart(2, '0')
		return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} `
			+ `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
	})
}

function formatTimeAxisTick(value, timeBounds) {
	const date = new Date(Number(value))
	if (Number.isNaN(date.getTime())) return ''
	const pad = number => String(number).padStart(2, '0')
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
	const pointTimes = points
		.map(point => new Date(point.time).getTime())
		.filter(Number.isFinite)
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

	const datedPoints = points.map(point => ({ point, timestamp: new Date(point.time).getTime() }))
	const intervals = []
	for (let index = 1; index < datedPoints.length; index += 1) {
		const interval = datedPoints[index].timestamp - datedPoints[index - 1].timestamp
		intervals.push(Number.isFinite(interval) && interval > 0 ? interval : null)
	}
	const validIntervals = intervals.filter(interval => interval !== null)
	if (!validIntervals.length) return points

	const sortedIntervals = [...validIntervals].sort((left, right) => left - right)
	// A lower quartile represents the normal sampling cadence without letting
	// one or more long outages inflate the threshold used to detect a gap.
	const typicalInterval = sortedIntervals[Math.floor((sortedIntervals.length - 1) * 0.25)]
	const bucketMs = {
		'5m': 1000,
		'1h': 10000,
		'24h': 60000,
		'7d': 600000,
		'30d': 1800000,
		'all': 3600000,
	}[rangeValue] || 1000
	const result = [datedPoints[0].point]

	for (let index = 1; index < datedPoints.length; index += 1) {
		const previous = datedPoints[index - 1]
		const current = datedPoints[index]
		const currentInterval = current.timestamp - previous.timestamp
		// Compare against cadence on both sides of this interval. This lets a
		// device change from e.g. 100 ms to 10 s without turning every new
		// sample into a false gap, while an isolated outage remains visible.
		const neighbourIntervals = [
			intervals[index - 2],
			intervals[index],
		].filter(interval => interval !== null && interval !== undefined)
		const localCadence = Math.max(bucketMs, typicalInterval, ...neighbourIntervals)
		if (currentInterval > localCadence * 2.5) {
			result.push({ time: new Date((previous.timestamp + current.timestamp) / 2).toISOString() })
		}
		result.push(current.point)
	}

	return result
}

function getValues(points, field) {
	return points.map(point => {
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
	const timeValues = points.map(point => new Date(point.time).getTime())
	datasets.forEach(dataset => {
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
							title: items => {
								if (!items.length) return ''
								return items[0].chart.fullTimestamps?.[items[0].dataIndex]
									|| items[0].label
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
						onHover: event => {
							if (event.native && event.native.target) event.native.target.style.cursor = 'pointer'
						},
						onLeave: event => {
							if (event.native && event.native.target) event.native.target.style.cursor = 'default'
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
						afterBuildTicks: scale => {
							const interval = (scale.max - scale.min) / 4
							scale.ticks = Array.from(
								{ length: 5 },
								(_item, index) => ({ value: scale.min + interval * index }),
							)
						},
						ticks: {
							autoSkip: false,
							maxRotation: 0,
							minRotation: 0,
							callback: value => formatTimeAxisTick(value, timeBounds),
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
	existingChart.options.scales.x.ticks.callback = value => formatTimeAxisTick(value, timeBounds)
	datasets.forEach((dataset, index) => {
		const savedVisibility = chartSeriesVisibility.get(`${canvasId}:${dataset.label}`)
		if (savedVisibility !== undefined) existingChart.setDatasetVisibility(index, savedVisibility)
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
	document.querySelectorAll('.chart-expand-button').forEach(button => {
		button.innerHTML = getChartSizeIcon(false)
		button.setAttribute('aria-pressed', 'false')
		button.addEventListener('click', () => {
			const card = button.closest('.chart-card')
			if (!card) return
			const shouldExpand = !card.classList.contains('expanded')
			setChartExpanded(card, shouldExpand)
		})
	})

	document.addEventListener('keydown', event => {
		if (event.key !== 'Escape') return
		document.querySelectorAll('.chart-card.expanded').forEach(card => setChartExpanded(card, false))
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
	document.querySelectorAll('.range-button[data-range]').forEach(button => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			const isStatistics = panel?.dataset.tab === 'statistics'
			const rangeValue = button.dataset.range
			panel.querySelectorAll('.range-button').forEach(item => item.classList.remove('active'))
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

	document.querySelectorAll('.custom-range-toggle').forEach(button => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			panel.querySelector('.custom-range').hidden = false
			panel.querySelector('.custom-start-input').focus()
		})
	})

	document.querySelectorAll('.apply-custom-range-button').forEach(button => {
		button.addEventListener('click', () => {
			const container = button.closest('.monitors-header')
			const panel = button.closest('.tab-panel')
			const startValue = localDateTimeToIso(container.querySelector('.custom-start-input').value)
			const endValue = localDateTimeToIso(container.querySelector('.custom-end-input').value)
			if (!startValue || !endValue) {
				showNotification('Select both From and To for a custom range.', 'error')
				return
			}
			if (new Date(startValue).getTime() >= new Date(endValue).getTime()) {
				showNotification('From must be earlier than To.', 'error')
				return
			}
			panel.querySelectorAll('.range-button').forEach(item => item.classList.remove('active'))
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

	document.querySelectorAll('.export-csv-button').forEach(button => {
		button.addEventListener('click', () => {
			const panel = button.closest('.tab-panel')
			const query = panel.dataset.tab === 'statistics'
				? buildStatisticsQuery()
				: buildOverviewQuery()
			const endpoint = deviceProfile === 'fts-ls'
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

async function updateSnmpLiveValues() {
	const container = document.getElementById('snmp-live-values')
	if (!container || !currentUser) return
	try {
		const response = await fetch('/api/snmp/live_data')
		handleAuthResponse(response)
		if (!response.ok) throw new Error(`HTTP ${response.status}`)
		const data = await response.json()
		const rows = Object.entries(SNMP_FIELD_LABELS)
			.filter(([field]) => field in data)
			.map(
				([field, label]) =>
					`<div class="limit-row"><span>${escapeHtml(label)}</span><span>${escapeHtml(data[field])}</span></div>`,
			)
			.join('')
		container.innerHTML = rows ? `<div class="limit-list">${rows}</div>` : '<p>Waiting for SNMP data...</p>'
	} catch (error) {
		container.innerHTML = '<p>Could not load SNMP data.</p>'
		console.error(error)
	}
}

async function loadSnmpSettings() {
	if (!currentUser) return
	const response = await fetch('/api/snmp/settings')
	handleAuthResponse(response)
	if (!response.ok) return
	const settings = await response.json()
	document.getElementById('snmp-enabled-input').checked = settings.enabled
	document.getElementById('snmp-port-input').value = settings.port
	document.getElementById('snmp-community-input').value = settings.community
	document.getElementById('snmp-trap-host-input').value = settings.trap_host
	document.getElementById('snmp-trap-port-input').value = settings.trap_port
	updateSnmpLiveValues()
}

const snmpForm = document.getElementById('snmp-settings-form')
if (snmpForm) {
	snmpForm.addEventListener('submit', async event => {
		event.preventDefault()
		const payload = {
			enabled: document.getElementById('snmp-enabled-input').checked,
			port: Number(document.getElementById('snmp-port-input').value),
			community: document.getElementById('snmp-community-input').value.trim(),
			trap_host: document.getElementById('snmp-trap-host-input').value.trim(),
			trap_port: Number(document.getElementById('snmp-trap-port-input').value),
		}
		try {
			const response = await fetch('/api/snmp/settings', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			})
			handleAuthResponse(response)
			if (!response.ok) throw await responseError(response, 'Could not save SNMP settings')
			await loadSnmpSettings()
			showNotification('SNMP settings saved.')
		} catch (error) {
			showNotification(error.message, 'error')
			console.error('Error saving SNMP settings:', error)
		}
	})
}
const gainSetInput = document.getElementById('gain-set-input')
if (gainSetInput) {
	gainSetInput.addEventListener('input', () => {
		gainInputEdited = true
	})
}

function setupAuth() {
	const loginForm = document.getElementById('login-form')
	const logoutButton = document.getElementById('logout-button')
	const syslogButton = document.getElementById('download-syslog-button')

	if (loginForm) {
		loginForm.addEventListener('submit', async event => {
			event.preventDefault()

			const error = document.getElementById('login-error')
			const username = document.getElementById('login-username').value.trim()
			const password = document.getElementById('login-password').value

			error.textContent = ''

			try {
				await login(username, password)
				loginForm.reset()
				await startDataRefresh()
			} catch (loginError) {
				error.textContent = loginError.message || 'Invalid username or password'
			}
		})
	}

	if (logoutButton) {
		logoutButton.addEventListener('click', async () => {
			await logout()
		})
	}

	if (syslogButton) {
		syslogButton.addEventListener('click', () => {
			if (!isAdministrator()) return
			window.location.href = '/api/syslog/export.log'
		})
	}
}

let ftsFormTarget = null
const ftsDirtyInputs = new Set()
const ftsInputBaselines = new Map()

function selectedFtsModule() {
	const target = document.getElementById('fts-target')?.value || 'ul'
	if (!latestFtsStatus) return null
	if (target === 'ul') return latestFtsStatus.uplink || null
	const match = target.match(/^port([1-7])$/)
	return match ? (latestFtsStatus.ports || [])[Number(match[1]) - 1] : null
}

function setFtsInputValue(id, value, force = false) {
	const input = document.getElementById(id)
	if (!input || (!force && ftsDirtyInputs.has(id)) || document.activeElement === input) return
	if (input.type === 'number') input.value = ftsNumeric(value) ?? ''
	else if (value === true) input.value = 'true'
	else if (value === false) input.value = 'false'
	else input.value = value ?? ''
	ftsInputBaselines.set(id, input.value)
	if (force) ftsDirtyInputs.delete(id)
}

function updateFtsFormState(form) {
	if (!form) return
	const dirty = [...form.querySelectorAll('[data-fts-setting-action]')]
		.some(input => ftsDirtyInputs.has(input.id))
	form.classList.toggle('dirty', dirty)
	const save = form.querySelector('.fts-save-settings')
	if (save) save.disabled = !dirty || !canOperate()
}

function clearFtsFormChanges(form) {
	form?.querySelectorAll('[data-fts-setting-action]').forEach(input => {
		ftsDirtyInputs.delete(input.id)
	})
	updateFtsFormState(form)
}

function updateFtsTargetForm(force = false) {
	if (deviceProfile !== 'fts-ls') return
	const target = document.getElementById('fts-target')?.value || 'ul'
	if (!force && ftsFormTarget === target && !latestFtsStatus) return
	const module = selectedFtsModule()
	if (!module) return
	ftsFormTarget = target
	const assignments = {
		'fts-description-input': firstValue(module, ['description'], ''),
		'fts-optical-power-input': String(firstValue(module, ['state'], '')).toUpperCase() !== 'SHUTDOWN',
		'fts-distance-input': firstValue(module, ['distance_km', 'equivalent_distance'], ''),
		'fts-gain-input': firstValue(module, ['additional_gain_db', 'additional_gain_set'], 0),
		'fts-pol-power-input': firstValue(module, ['polarization_control'], true),
		'fts-pol-speed-input': String(firstValue(module, ['polarization_controller_speed'], 'fast')).toLowerCase(),
		'fts-pol-mode-input': String(firstValue(module, ['polarization_controller_mode'], 'continuous')).toLowerCase(),
	}
	Object.entries(assignments).forEach(([id, value]) => {
		setFtsInputValue(id, value, force)
	})

	const type = String(firstValue(module, ['type'], target === 'ul' ? 'Uplink' : 'Unknown')).toLowerCase()
	const isDownlink = type.includes('downlink')
	const hasPolarization = target === 'ul' || type.includes('feedback')
	document.querySelectorAll('[data-fts-downlink-only]').forEach(field => {
		field.hidden = !isDownlink
		field.querySelectorAll('input, select').forEach(input => { input.disabled = !isDownlink })
	})
	document.querySelectorAll('[data-fts-polarization-only]').forEach(field => {
		field.hidden = !hasPolarization
		field.querySelectorAll('input, select').forEach(input => { input.disabled = !hasPolarization })
	})
	setTextIfExists('fts-port-settings-hint', `${target === 'ul' ? 'UL' : target.toUpperCase()} · ${firstValue(module, ['type'], 'Unknown')}`)
	updateFtsFormState(document.getElementById('fts-port-settings-form'))
}

function updateFtsSettingsForms(force = false) {
	if (!latestFtsStatus) return
	const laser = latestFtsStatus.laser || {}
	const tec = latestFtsStatus.tec || {}
	const synth = latestFtsStatus.synth || {}
	const laserState = String(firstValue(laser, ['state', 'status'], 'ON')).toUpperCase()
	setFtsInputValue('fts-laser-power', !['OFF', 'SHUTDOWN', 'FALSE'].includes(laserState), force)
	setFtsInputValue('fts-laser-mode', String(firstValue(laser, ['mode'], 'normal')).toLowerCase().replaceAll('_', '-'), force)
	setFtsInputValue('fts-laser-frequency-input', firstValue(laser, ['central_frequency_set', 'central_frequency'], ''), force)
	setFtsInputValue('fts-laser-span-input', firstValue(laser, ['scanning_frequency_span_set', 'frequency_span'], ''), force)
	const tecState = String(firstValue(tec, ['state', 'status'], 'ON')).toUpperCase()
	setFtsInputValue('fts-tec-power-input', !['OFF', 'FALSE'].includes(tecState), force)
	setFtsInputValue('fts-tec-temperature-input', firstValue(tec, ['temperature_set_c', 'temperature_set'], ''), force)
	setFtsInputValue('fts-reference-input', firstValue(synth, ['external_frequency_allowed', 'external_10_mhz_allowed'], true), force)
	updateFtsTargetForm(force)
	document.querySelectorAll('.fts-settings-form').forEach(updateFtsFormState)
}

const ftsTransferActions = new Set([
	'power_reset', 'factory_default', 'laser_power', 'laser_central_frequency',
	'laser_mode', 'laser_force_relock', 'optical_power',
])

async function postFtsAction(action, parameters, confirmed = false) {
	const response = await fetch('/api/fts-ls/command', {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({ action, parameters, confirmed }),
	})
	handleAuthResponse(response)
	if (!response.ok) throw await responseError(response, 'FTS-LS command failed')
	return response.json()
}

async function sendFtsAction(button) {
	const action = button.dataset.ftsAction
	const parameters = {}
	if (button.hasAttribute('data-fts-target')) parameters.target = document.getElementById('fts-target')?.value
	if (button.dataset.ftsValueFrom) parameters.value = document.getElementById(button.dataset.ftsValueFrom)?.value
	if (button.dataset.ftsEnabledFrom) parameters.enabled = document.getElementById(button.dataset.ftsEnabledFrom)?.value === 'true'
	let confirmed = false
	if (ftsTransferActions.has(action) || ['reboot'].includes(action)) {
		confirmed = window.confirm('This operation may interrupt frequency transfer or restart the station. Continue?')
		if (!confirmed) return
	}
	button.disabled = true
	try {
		await postFtsAction(action, parameters, confirmed)
		showNotification('FTS-LS command accepted.')
		ftsFormTarget = null
		window.setTimeout(updateDashboard, 500)
	} catch (error) {
		showNotification(error.message || 'FTS-LS command failed.', 'error')
	} finally {
		button.disabled = false
	}
}

async function saveFtsSettings(form) {
	const inputs = [...form.querySelectorAll('[data-fts-setting-action]')]
		.filter(input => ftsDirtyInputs.has(input.id) && !input.disabled)
	if (!inputs.length) return
	const transferAffecting = inputs.some(input => ftsTransferActions.has(input.dataset.ftsSettingAction))
	if (transferAffecting && !window.confirm('These changes may interrupt frequency transfer for several minutes. Continue?')) return
	const save = form.querySelector('.fts-save-settings')
	if (save) save.disabled = true
	let completed = 0
	try {
		for (const input of inputs) {
			const parameters = {}
			if (input.hasAttribute('data-fts-target')) parameters.target = document.getElementById('fts-target')?.value
			if (input.dataset.ftsValueKind === 'enabled') parameters.enabled = input.value === 'true'
			else parameters.value = input.value
			await postFtsAction(input.dataset.ftsSettingAction, parameters, transferAffecting)
			ftsInputBaselines.set(input.id, input.value)
			ftsDirtyInputs.delete(input.id)
			completed += 1
		}
		showNotification(`${completed} setting${completed === 1 ? '' : 's'} saved.`)
		ftsFormTarget = null
		window.setTimeout(updateDashboard, 500)
	} catch (error) {
		showNotification(`${completed} of ${inputs.length} settings saved. ${error.message || 'The next command failed.'}`, 'error')
	} finally {
		updateFtsFormState(form)
	}
}

function setupFtsControls() {
	if (deviceProfile !== 'fts-ls') return
	document.querySelectorAll('.fts-settings-form').forEach(form => {
		updateFtsFormState(form)
		form.querySelectorAll('[data-fts-setting-action]').forEach(input => {
			const markDirty = () => {
				if (input.value === ftsInputBaselines.get(input.id)) ftsDirtyInputs.delete(input.id)
				else ftsDirtyInputs.add(input.id)
				updateFtsFormState(form)
			}
			ftsInputBaselines.set(input.id, input.value)
			input.addEventListener('input', markDirty)
			input.addEventListener('change', markDirty)
		})
		form.addEventListener('submit', event => {
			event.preventDefault()
			saveFtsSettings(form)
		})
		form.querySelector('.fts-cancel-settings')?.addEventListener('click', () => {
			clearFtsFormChanges(form)
			updateFtsSettingsForms()
		})
	})
	document.getElementById('fts-target')?.addEventListener('change', event => {
		const form = document.getElementById('fts-port-settings-form')
		const hasChanges = [...form.querySelectorAll('[data-fts-setting-action]')]
			.some(input => ftsDirtyInputs.has(input.id))
		if (hasChanges && !window.confirm('Discard unsaved changes for the selected module?')) {
			event.target.value = ftsFormTarget || 'ul'
			return
		}
		clearFtsFormChanges(form)
		ftsFormTarget = null
		updateFtsTargetForm(true)
		highlightSelectedFtsModule()
	})
	const moduleRack = document.getElementById('fts-modules')
	const selectModule = event => {
		if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return
		const module = event.target.closest('[data-fts-module-target]:not(.unequipped)')
		if (!module || !moduleRack?.contains(module)) return
		if (event.type === 'keydown') event.preventDefault()
		const select = document.getElementById('fts-target')
		if (!select) return
		select.value = module.dataset.ftsModuleTarget
		select.dispatchEvent(new Event('change', { bubbles: true }))
		highlightSelectedFtsModule()
	}
	moduleRack?.addEventListener('click', selectModule)
	moduleRack?.addEventListener('keydown', selectModule)
	document.querySelectorAll('[data-fts-action]').forEach(button => {
		button.addEventListener('click', () => sendFtsAction(button))
	})
}

function ftsNumeric(value) {
	if (value === null || value === undefined || value === '') return null
	const numeric = Number(value)
	if (Number.isFinite(numeric)) return numeric
	const match = String(value).match(/[-+]?\d+(?:[.,]\d+)?/)
	return match ? Number(match[0].replace(',', '.')) : null
}

function flattenFtsHistoryPoint(point) {
	const snapshot = point.snapshot || {}
	const flattened = { time: point.time }
	const laser = snapshot.laser || {}
	const tec = snapshot.tec || {}
	flattened.laser_frequency = ftsNumeric(firstValue(laser, ['optical_frequency', 'frequency', 'current_frequency']))
	flattened.tec_set = ftsNumeric(firstValue(tec, ['temperature_set_c', 'temperature_set']))
	flattened.tec_read = ftsNumeric(firstValue(tec, ['temperature_read_c', 'temperature_read']))
	for (const module of [snapshot.uplink || {}, ...(snapshot.ports || [])]) {
		const name = String(module.name || '').toUpperCase()
		if (!['UL', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'].includes(name)) continue
		flattened[`${name}_power`] = ftsNumeric(module.optical_power)
		flattened[`${name}_noise_lf`] = ftsNumeric(module.noise_lf)
		flattened[`${name}_noise_hf`] = ftsNumeric(module.noise_hf)
		flattened[`${name}_jitter`] = ftsNumeric(module.jitter)
	}
	return flattened
}

function ftsTimeBounds(points, range) {
	const durations = {
		'5m': 5 * 60 * 1000,
		'1h': 60 * 60 * 1000,
		'24h': 24 * 60 * 60 * 1000,
		'7d': 7 * 24 * 60 * 60 * 1000,
		'30d': 30 * 24 * 60 * 60 * 1000,
	}
	const times = points.map(point => new Date(point.time).getTime()).filter(Number.isFinite)
	if (range !== 'all') {
		const max = Date.now()
		return { min: max - durations[range], max }
	}
	if (times.length) return { min: times[0], max: times.at(-1) }
	const max = Date.now()
	return { min: max - 60 * 60 * 1000, max }
}

function ftsModuleDatasets(points, suffix, names) {
	return names.map(name => ({
		label: name,
		data: getValues(points, `${name}_${suffix}`),
		spanGaps: false,
	}))
}

function updateFtsHistoryCharts(points, range) {
	const chartPoints = addHistoryGapMarkers(points.map(flattenFtsHistoryPoint), range)
	const timestamps = getFullTimestamps(chartPoints)
	const bounds = ftsTimeBounds(chartPoints, range)
	const modules = ['UL', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7']
	const ports = modules.slice(1)
	ftsOpticalPowerChart = createOrUpdateChart(ftsOpticalPowerChart, 'fts-optical-power-chart', chartPoints, timestamps, ftsModuleDatasets(chartPoints, 'power', modules), 'Power [dBm]', bounds)
	ftsLfNoiseChart = createOrUpdateChart(ftsLfNoiseChart, 'fts-lf-noise-chart', chartPoints, timestamps, ftsModuleDatasets(chartPoints, 'noise_lf', modules), 'LF noise [a.u.]', bounds)
	ftsHfNoiseChart = createOrUpdateChart(ftsHfNoiseChart, 'fts-hf-noise-chart', chartPoints, timestamps, ftsModuleDatasets(chartPoints, 'noise_hf', modules), 'HF noise [a.u.]', bounds)
	ftsJitterChart = createOrUpdateChart(ftsJitterChart, 'fts-jitter-chart', chartPoints, timestamps, ftsModuleDatasets(chartPoints, 'jitter', ports), 'Jitter [%]', bounds)
	ftsLaserFrequencyChart = createOrUpdateChart(ftsLaserFrequencyChart, 'fts-laser-frequency-chart', chartPoints, timestamps, [{label: 'Laser', data: getValues(chartPoints, 'laser_frequency'), spanGaps: false}], 'Frequency [GHz]', bounds)
	ftsTecChart = createOrUpdateChart(ftsTecChart, 'fts-tec-chart', chartPoints, timestamps, [
		{label: 'Setpoint', data: getValues(chartPoints, 'tec_set'), spanGaps: false},
		{label: 'Measured', data: getValues(chartPoints, 'tec_read'), spanGaps: false},
	], 'Temperature [°C]', bounds)
}

async function loadFtsOverview() {
	if (deviceProfile !== 'fts-ls' || !currentUser) return
	const requestSequence = ++overviewRequestSequence
	if (overviewRequestController) overviewRequestController.abort()
	overviewRequestController = new AbortController()
	const requestController = overviewRequestController
	lastOverviewChartRefresh = Date.now()
	setTextIfExists('fts-overview-loading', 'Loading…')
	try {
		const response = await fetch(`/api/fts-ls/history?${buildOverviewQuery()}&limit=10000`, {
			signal: requestController.signal,
		})
		handleAuthResponse(response)
		if (!response.ok) throw await responseError(response, 'Could not load FTS-LS history')
		const result = await response.json()
		if (requestSequence !== overviewRequestSequence) return
		updateFtsHistoryCharts(result.points || [], overviewRange)
		setTextIfExists('fts-overview-loading', '')
		lastOverviewChartRefresh = Date.now()
	} catch (error) {
		if (error.name === 'AbortError' || requestSequence !== overviewRequestSequence) return
		setTextIfExists('fts-overview-loading', 'Could not load data')
		console.error('Error fetching FTS-LS history:', error)
	} finally {
		if (requestSequence === overviewRequestSequence) overviewRequestController = null
	}
}

function ftsStatisticsFields() {
	const modules = ['UL', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7']
	const fields = []
	modules.forEach(name => {
		fields.push({key: `${name}_power`, label: `${name} Optical Power`, unit: 'dBm', min: -65, max: -33})
		fields.push({key: `${name}_noise_lf`, label: `${name} Low-frequency Noise`, unit: '', max: 100})
		fields.push({key: `${name}_noise_hf`, label: `${name} High-frequency Noise`, unit: ''})
		if (name !== 'UL') fields.push({key: `${name}_jitter`, label: `${name} Jitter`, unit: '%', max: 50})
	})
	fields.push({key: 'laser_frequency', label: 'Laser Frequency', unit: 'GHz'})
	fields.push({key: 'tec_set', label: 'TEC Setpoint', unit: '°C'})
	fields.push({key: 'tec_read', label: 'TEC Temperature', unit: '°C'})
	return fields
}

function ftsFieldStatistics(points, field) {
	const values = points.map(point => point[field.key]).filter(Number.isFinite)
	if (!values.length) return null
	const sum = values.reduce((total, value) => total + value, 0)
	const average = sum / values.length
	const variance = values.reduce((total, value) => total + ((value - average) ** 2), 0) / values.length
	return {
		count: values.length,
		min: Math.min(...values),
		max: Math.max(...values),
		average,
		stddev: Math.sqrt(Math.max(0, variance)),
		outside: values.filter(value =>
			(field.min !== undefined && value < field.min) ||
			(field.max !== undefined && value > field.max)
		).length,
	}
}

async function loadFtsStatistics() {
	if (deviceProfile !== 'fts-ls' || !currentUser) return
	const requestSequence = ++statisticsRequestSequence
	if (statisticsRequestController) statisticsRequestController.abort()
	statisticsRequestController = new AbortController()
	const requestController = statisticsRequestController
	lastStatisticsRefresh = Date.now()
	setTextIfExists('fts-statistics-source', 'Loading…')
	try {
		const response = await fetch(`/api/fts-ls/history?${buildStatisticsQuery()}&limit=10000`, {
			signal: requestController.signal,
		})
		handleAuthResponse(response)
		if (!response.ok) throw await responseError(response, 'Could not load FTS-LS statistics')
		const result = await response.json()
		if (requestSequence !== statisticsRequestSequence) return
		const rawPoints = result.points || []
		const points = rawPoints.map(flattenFtsHistoryPoint)
		const rows = ftsStatisticsFields().map(field => [field, ftsFieldStatistics(points, field)])
			.filter(([, statistics]) => statistics)
		const body = document.getElementById('fts-statistics-body')
		if (body) {
			body.innerHTML = rows.length ? rows.map(([field, statistics]) => {
				const unit = field.unit ? ` ${field.unit}` : ''
				const outside = field.min === undefined && field.max === undefined
					? '--'
					: statistics.outside
						? `<span class="status-error">${statistics.outside}</span>`
						: '<span class="status-ok">0</span>'
				return `<tr><td>${escapeHtml(field.label)}</td><td>${statistics.count}</td>` +
					`<td>${formatPlainNumber(statistics.min, 3)}${unit}</td>` +
					`<td>${formatPlainNumber(statistics.max, 3)}${unit}</td>` +
					`<td>${formatPlainNumber(statistics.average, 3)}${unit}</td>` +
					`<td>${formatPlainNumber(statistics.stddev, 3)}${unit}</td><td>${outside}</td></tr>`
			}).join('') : '<tr><td colspan="7">No numeric data in this range</td></tr>'
		}
		const rangeText = statisticsStart || statisticsEnd ? 'custom range' : statisticsRange
		setTextIfExists('fts-statistics-source', `${rawPoints.length} snapshots, ${rangeText}`)
		lastStatisticsRefresh = Date.now()
	} catch (error) {
		if (error.name === 'AbortError' || requestSequence !== statisticsRequestSequence) return
		setTextIfExists('fts-statistics-source', 'Could not load data')
		const body = document.getElementById('fts-statistics-body')
		if (body) body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message || 'Statistics unavailable')}</td></tr>`
	} finally {
		if (requestSequence === statisticsRequestSequence) statisticsRequestController = null
	}
}

function updateOverviewCharts() {
	return deviceProfile === 'fts-ls' ? loadFtsOverview() : updateAmplifierOverviewCharts()
}

function updateStatisticsTable() {
	return deviceProfile === 'fts-ls' ? loadFtsStatistics() : updateAmplifierStatisticsTable()
}

async function startDataRefresh() {
	await loadSettings()
	await updateDashboard()
	await updateWarningsTable()
	await updateStatisticsTable()

	if (isAdministrator()) {
		await loadAccessUsers()
	}
}

setupSettingsButtons()
setupWarningFilters()
setupRangeButtons()
setupAccessControl()
setupAuth()
setupChartExpansion()
setupFtsControls()

checkAuth().then(isAuthenticated => {
	if (isAuthenticated) {
		startDataRefresh()
	}
})

setInterval(updateDashboard, 1000)
setInterval(updateWarningsTable, 3000)
setInterval(() => {
	if (!currentUser) return

	const overviewTab = document.querySelector('.tab-panel[data-tab="overview"]')
	if (overviewTab
		&& overviewTab.classList.contains('active')
		&& !overviewRequestController
		&& Date.now() - lastOverviewChartRefresh >= historyRefreshInterval(overviewRange)) {
		updateOverviewCharts()
	}
	const snmpTab = document.querySelector('.tab-panel[data-tab="snmp-settings"]')
	if (snmpTab && snmpTab.classList.contains('active')) updateSnmpLiveValues()

	const ntpTab = document.querySelector('.tab-panel[data-tab="ntp-settings"]')
	if (ntpTab && ntpTab.classList.contains('active')) loadNtpStatus()
	const servicesTab = document.querySelector('.tab-panel[data-tab="service-diagnostics"]')
	if (servicesTab && servicesTab.classList.contains('active')) loadServiceDiagnostics()

	const statisticsTab = document.querySelector('.tab-panel[data-tab="statistics"]')
	if (statisticsTab
		&& statisticsTab.classList.contains('active')
		&& !statisticsRequestController
		&& Date.now() - lastStatisticsRefresh >= historyRefreshInterval(statisticsRange)) {
		updateStatisticsTable()
	}
}, 3000)
