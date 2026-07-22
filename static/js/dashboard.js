const navLinks = document.querySelectorAll('.nav-link')
const tabPanels = document.querySelectorAll('.tab-panel')
const currentTitle = document.getElementById('current-tab-title')

let dashboardSettings = null
let selectedRange = '5m'
let powerChart = null
let gainChart = null
let deltaChart = null
let temperatureChart = null
let gainInputEdited = false
let currentUser = null
let selectedStart = null
let selectedEnd = null
let latestNetwork = null

function formatDbm(value) {
	if (value === null || value === undefined) return '-- dBm'
	return Number(value).toFixed(2) + ' dBm'
}

function formatDb(value) {
	if (value === null || value === undefined) return '-- dB'
	return Number(value).toFixed(2) + ' dB'
}

function formatTemperature(value) {
	if (value === null || value === undefined) return '-- C'
	return Number(value).toFixed(2) + ' C'
}

function formatTime(value) {
	if (!value) return '--'
	return new Date(value).toLocaleTimeString()
}

function formatPlainNumber(value, digits = 2) {
	if (value === null || value === undefined || value === '') return '--'
	return Number(value).toFixed(digits)
}

function localDateTimeToIso(value) {
	if (!value) return null
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return null
	return date.toISOString()
}

function buildHistoryQuery() {
	const params = new URLSearchParams({ range: selectedRange })

	if (selectedStart) {
		params.set('start', selectedStart)
	}

	if (selectedEnd) {
		params.set('end', selectedEnd)
	}

	return params.toString()
}

function syncCustomRangeInputs(sourceContainer) {
	const startValue = sourceContainer.querySelector('.custom-start-input')?.value || ''
	const endValue = sourceContainer.querySelector('.custom-end-input')?.value || ''

	document.querySelectorAll('.custom-start-input').forEach(input => {
		input.value = startValue
	})
	document.querySelectorAll('.custom-end-input').forEach(input => {
		input.value = endValue
	})
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

async function responseError(response, fallback) {
	try {
		const body = await response.json()
		return new Error(body.detail || fallback)
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
	if (tabName === 'warnings') updateWarningsTable()
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
		if (!response.ok) throw new Error(data.detail || 'Could not read network settings')
		latestNetwork = data
		const select = document.getElementById('network-interface')
		select.innerHTML = data.interfaces
			.map(
				item =>
					`<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} (${escapeHtml(item.mac || 'no MAC')})</option>`,
			)
			.join('')
		select.value = data.selected_interface || data.interfaces[0]?.name || ''
		fillNetworkForm(selectedNetworkInterface())
		document.getElementById('save-network-button').disabled = !data.supported || !isAdministrator()
		showNetworkMessage(data.message || `Host: ${data.hostname}; backend: ${data.backend}`)
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
	if (!confirm('Apply the new network settings? The connection may be interrupted.')) return
	const payload = Object.fromEntries(new FormData(form).entries())
	showNetworkMessage('Applying settings...')
	try {
		const response = await fetch('/api/network', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		})
		handleAuthResponse(response)
		const data = await response.json()
		if (!response.ok) throw new Error(data.detail || 'Could not apply network settings')
		latestNetwork = data
		fillNetworkForm(selectedNetworkInterface())
		showNetworkMessage('Network settings applied.')
		showNotification('Network settings applied.')
	} catch (error) {
		showNetworkMessage(error.message, true)
		showNotification(error.message, 'error')
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
	const state = String(database.state || 'error').toUpperCase()
	const statusElement = document.getElementById('status-database')
	if (statusElement) {
		statusElement.textContent = state
		statusElement.className = database.ready ? 'status-ok' : 'status-error'
	}
	setTextIfExists('status-database-records', String(database.records ?? 0))
}

function formatBytes(bytes) {
	const value = Number(bytes)
	if (!Number.isFinite(value)) return '--'
	if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
	if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MiB`
	return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`
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
		setTextIfExists('service-serial-state', serial.connected ? 'CONNECTED' : 'DISCONNECTED')
		setTextIfExists('service-serial-port', serial.port || '--')
		setTextIfExists('service-serial-baudrate', String(serial.baudrate ?? '--'))
		setTextIfExists('service-serial-error', serial.error || 'None')
		const serialPortInput = document.getElementById('service-serial-port-input')
		if (serialPortInput) {
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
		setTextIfExists('service-database-limit', String(database.record_limit ?? '--'))
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
		if (heartbeatInput) heartbeatInput.value = syslog.heartbeat_seconds ?? 300
		if (databaseLimitInput) databaseLimitInput.value = database.record_limit ?? 250000
	} catch (error) {
		setTextIfExists('service-database-state', 'API ERROR')
		console.error('Error loading service diagnostics:', error)
	}
}

document.getElementById('refresh-services-button')?.addEventListener('click', loadServiceDiagnostics)

document.getElementById('service-settings-form')?.addEventListener('submit', async event => {
	event.preventDefault()
	try {
		const response = await fetch('/api/service-diagnostics/settings', {
			method: 'PUT',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({
				serial_port: document.getElementById('service-serial-port-input').value,
				syslog_heartbeat_seconds: Number(document.getElementById('service-heartbeat-input').value),
				database_max_records: Number(document.getElementById('service-database-limit-input').value),
			}),
		})
		handleAuthResponse(response)
		const result = await response.json()
		if (!response.ok) throw new Error(result.detail || 'Could not save service settings')
		const suffix = result.pruned_records ? ` ${result.pruned_records} oldest database records were removed.` : ''
		showNotification(`Service settings saved.${suffix}`)
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

async function updateWarningsTable() {
	if (!currentUser) return

	try {
		const response = await fetch('/api/errors')
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		const warnings = json.errors || []
		const body = document.getElementById('warnings-table-body')

		setTextIfExists('warning-count', String(warnings.length))

		if (!body) return

		if (!warnings.length) {
			body.innerHTML = '<tr><td colspan="6">No warnings</td></tr>'
			return
		}

		const rows = warnings
			.map(
				warning => `
            <tr>
                <td>${formatTime(warning.time)}</td>
                <td>${warning.label || warning.field}</td>
                <td>${formatPlainNumber(warning.value)}</td>
                <td>${formatPlainNumber(warning.target)}</td>
                <td>${formatPlainNumber(warning.delta)}</td>
                <td>${warning.message}</td>
            </tr>
        `,
			)
			.join('')

		body.innerHTML = rows
	} catch (error) {
		console.error('Error fetching /api/errors:', error)
	}
}

function setupSettingsButtons() {
	const saveButton = document.getElementById('save-settings-button')
	const clearButton = document.getElementById('clear-errors-button')

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

	if (clearButton) {
		clearButton.addEventListener('click', async () => {
			if (!canOperate()) return
			try {
				const response = await fetch('/api/errors/clear', { method: 'POST' })
				handleAuthResponse(response)
				if (!response.ok) throw await responseError(response, 'Could not clear warnings')
				await updateWarningsTable()
				showNotification('Warnings cleared.')
			} catch (error) {
				showNotification(error.message, 'error')
			}
		})
	}
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

function getLabels(points) {
	return points.map(point => new Date(point.time).toLocaleTimeString())
}

function getValues(points, field) {
	return points.map(point => {
		if (point[field] === undefined || point[field] === null) return null
		return Number(point[field])
	})
}

function calculateStats(points, field) {
	const values = getValues(points, field).filter(value => value !== null && Number.isFinite(value))

	if (!values.length) {
		return null
	}

	const min = Math.min(...values)
	const max = Math.max(...values)
	const average = values.reduce((sum, value) => sum + value, 0) / values.length
	let maxDelta = 0

	for (let index = 1; index < values.length; index += 1) {
		maxDelta = Math.max(maxDelta, Math.abs(values[index] - values[index - 1]))
	}

	return { min, max, average, maxDelta }
}

async function updateStatisticsTable() {
	if (!currentUser) return

	try {
		const response = await fetch('/api/history?' + buildHistoryQuery())
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		const points = json.points || []
		const body = document.getElementById('statistics-table-body')
		const source = document.getElementById('statistics-source')

		if (source) {
			const rangeText = selectedStart || selectedEnd ? 'custom range' : json.range
			source.textContent = `${points.length} samples, ${rangeText}`
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
			['temperature', 'Temperature', 'C'],
		]

		const rows = fields
			.map(([field, label, unit]) => {
				const stats = calculateStats(points, field)

				if (!stats) {
					return `
                    <tr>
                        <td>${label}</td>
                        <td colspan="4">No data</td>
                    </tr>
                `
				}

				return `
                <tr>
                    <td>${label}</td>
                    <td>${formatPlainNumber(stats.min)}${unit ? ' ' + unit : ''}</td>
                    <td>${formatPlainNumber(stats.max)}${unit ? ' ' + unit : ''}</td>
                    <td>${formatPlainNumber(stats.average)}${unit ? ' ' + unit : ''}</td>
                    <td>${formatPlainNumber(stats.maxDelta)}${unit ? ' ' + unit : ''}</td>
                </tr>
            `
			})
			.join('')

		body.innerHTML = rows
	} catch (error) {
		console.error('Error fetching statistics:', error)
	}
}

function createOrUpdateChart(existingChart, canvasId, labels, datasets, yLabel) {
	const canvas = document.getElementById(canvasId)
	if (!canvas || typeof Chart === 'undefined') return existingChart

	if (existingChart === null) {
		return new Chart(canvas, {
			type: 'line',
			data: { labels: labels, datasets: datasets },
			options: {
				animation: false,
				responsive: true,
				maintainAspectRatio: false,
				scales: {
					y: { title: { display: true, text: yLabel } },
				},
			},
		})
	}

	existingChart.data.labels = labels
	existingChart.data.datasets = datasets
	existingChart.update()
	return existingChart
}

async function updateOverviewCharts() {
	if (!currentUser) return

	try {
		const response = await fetch('/api/history?' + buildHistoryQuery())
		handleAuthResponse(response)
		if (!response.ok) throw new Error('HTTP error ' + response.status)
		const json = await response.json()
		const points = json.points || []
		const labels = getLabels(points)

		powerChart = createOrUpdateChart(
			powerChart,
			'power-chart',
			labels,
			[
				{ label: 'PiA', data: getValues(points, 'PiA') },
				{ label: 'PoA', data: getValues(points, 'PoA') },
				{ label: 'PiB', data: getValues(points, 'PiB') },
				{ label: 'PoB', data: getValues(points, 'PoB') },
			],
			'Power [dBm]',
		)

		gainChart = createOrUpdateChart(
			gainChart,
			'gain-chart',
			labels,
			[
				{ label: 'Gain set', data: getValues(points, 'gain_set') },
				{ label: 'Gain actual', data: getValues(points, 'gain_actual') },
			],
			'Gain [dB]',
		)

		deltaChart = createOrUpdateChart(
			deltaChart,
			'delta-chart',
			labels,
			[{ label: 'Gain delta', data: getValues(points, 'gain_delta') }],
			'Delta [dB]',
		)

		temperatureChart = createOrUpdateChart(
			temperatureChart,
			'temperature-chart',
			labels,
			[{ label: 'Temperature', data: getValues(points, 'temperature') }],
			'Temperature [C]',
		)
	} catch (error) {
		console.error('Error fetching /api/history:', error)
	}
}

function setupRangeButtons() {
	document.querySelectorAll('.range-button').forEach(button => {
		button.addEventListener('click', () => {
			selectedRange = button.dataset.range
			selectedStart = null
			selectedEnd = null
			document.querySelectorAll('.range-button').forEach(item => item.classList.remove('active'))
			document
				.querySelectorAll(`.range-button[data-range="${selectedRange}"]`)
				.forEach(item => item.classList.add('active'))
			updateOverviewCharts()
			updateStatisticsTable()
		})
	})

	document.querySelectorAll('.apply-custom-range-button').forEach(button => {
		button.addEventListener('click', () => {
			const container = button.closest('.monitors-header')
			selectedStart = localDateTimeToIso(container.querySelector('.custom-start-input').value)
			selectedEnd = localDateTimeToIso(container.querySelector('.custom-end-input').value)
			syncCustomRangeInputs(container)
			document.querySelectorAll('.range-button').forEach(item => item.classList.remove('active'))
			updateOverviewCharts()
			updateStatisticsTable()
		})
	})

	document.querySelectorAll('.export-csv-button').forEach(button => {
		button.addEventListener('click', () => {
			const container = button.closest('.monitors-header')
			selectedStart = localDateTimeToIso(container.querySelector('.custom-start-input').value) || selectedStart
			selectedEnd = localDateTimeToIso(container.querySelector('.custom-end-input').value) || selectedEnd
			syncCustomRangeInputs(container)
			window.location.href = '/api/history/export.csv?' + buildHistoryQuery()
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
setupRangeButtons()
setupAccessControl()
setupAuth()

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
	if (overviewTab && overviewTab.classList.contains('active')) {
		updateOverviewCharts()
	}
	const snmpTab = document.querySelector('.tab-panel[data-tab="snmp-settings"]')
	if (snmpTab && snmpTab.classList.contains('active')) updateSnmpLiveValues()

	const ntpTab = document.querySelector('.tab-panel[data-tab="ntp-settings"]')
	if (ntpTab && ntpTab.classList.contains('active')) loadNtpStatus()
	const servicesTab = document.querySelector('.tab-panel[data-tab="service-diagnostics"]')
	if (servicesTab && servicesTab.classList.contains('active')) loadServiceDiagnostics()

	const statisticsTab = document.querySelector('.tab-panel[data-tab="statistics"]')
	if (statisticsTab && statisticsTab.classList.contains('active')) {
		updateStatisticsTable()
	}
}, 3000)
