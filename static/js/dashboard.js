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
	if (!targetLink || (targetLink.hasAttribute('data-admin-only') && !isAdministrator())) {
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

	const accessTab = document.querySelector('.tab-panel[data-tab="access-control"]')
	if (accessTab && accessTab.classList.contains('active') && !isAdministrator()) {
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
	container.hidden = !isStatic
	container.querySelectorAll('input').forEach(input => {
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
	} catch (error) {
		showNetworkMessage(error.message, true)
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

function showNtpMessage(message, isError = false) {
    const element = document.getElementById("ntp-message");
    if (!element) return;
    element.textContent = message;
    element.classList.toggle("error", isError);
}

async function loadNtpStatus(force = false) {
    if (!document.getElementById("ntp-server")) return;
    showNtpMessage(force ? "Querying NTP server..." : "Loading NTP status...");
    try {
        const response = await fetch(`/api/ntp/status${force ? "?force=true" : ""}`);
        handleAuthResponse(response);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not read NTP status");

        setTextIfExists("ntp-server", `${data.server}${data.port ? ":" + data.port : ""}`);
        setTextIfExists("ntp-reachable", data.reachable ? "Yes" : "No");
        setTextIfExists("ntp-stratum", data.stratum !== undefined ? `${data.stratum} (${data.stratum_label || "--"})` : "--");
        setTextIfExists("ntp-reference-id", data.reference_id || "--");
        setTextIfExists("ntp-leap-indicator", data.leap_indicator_label || "--");
        setTextIfExists("ntp-reference-time", data.reference_time_utc ? new Date(data.reference_time_utc).toLocaleString() : "--");
        setTextIfExists("ntp-offset", data.offset_ms !== undefined && data.offset_ms !== null ? `${data.offset_ms} ms` : "--");
        setTextIfExists("ntp-round-trip", data.round_trip_ms !== undefined && data.round_trip_ms !== null ? `${data.round_trip_ms} ms` : "--");
        setTextIfExists("ntp-root-delay", (data.root_delay_ms !== undefined && data.root_delay_ms !== null) ? `${data.root_delay_ms} ms / ${data.root_dispersion_ms} ms` : "--");
        setTextIfExists("ntp-poll-interval", data.poll_interval_seconds ? `${data.poll_interval_seconds} s` : "--");
        setTextIfExists("ntp-checked-at", data.checked_at ? new Date(data.checked_at).toLocaleString() : "--");

        if (data.reachable) {
            showNtpMessage(`Synchronized with ${data.server}.`);
        } else {
            showNtpMessage(data.error || "NTP server unreachable.", true);
        }
    } catch (error) {
        showNtpMessage(error.message, true);
    }
}

document.getElementById("refresh-ntp-button")?.addEventListener("click", () => loadNtpStatus(true));

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
		throw new Error('Invalid username or password')
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

	if (gainInputEdited && gainValueText !== '') {
		const gainResponse = await fetch('/api/set_gain', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ gain_set: Number(gainValueText) }),
		})
		handleAuthResponse(gainResponse)

		if (!gainResponse.ok) {
			throw new Error('Could not set gain_set')
		}

		gainInputEdited = false
		gainInput.value = Number(gainValueText)
	}

	const response = await fetch('/api/settings', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			gain_tolerance: Number(document.getElementById('gain-tolerance-input').value || 0),
			warn_limits: warnLimits,
		}),
	})
	handleAuthResponse(response)

	dashboardSettings = await response.json()
	updateSettingsForm()
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
				await saveSettings()
			} catch (error) {
				alert('Could not save setpoints and thresholds. Check the serial port.')
				console.error('Error saving setpoints and thresholds:', error)
			}
		})
	}

	if (clearButton) {
		clearButton.addEventListener('click', async () => {
			if (!canOperate()) return
			const response = await fetch('/api/errors/clear', { method: 'POST' })
			handleAuthResponse(response)
			await updateWarningsTable()
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
			body.innerHTML = '<tr><td colspan="5">No users</td></tr>'
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
                        <input data-access-password type="password" placeholder="${user.password_set ? 'unchanged' : 'new password'}">
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
	const passwordInput = row.querySelector('[data-access-password]')
	const payload = {
		role: row.querySelector('[data-access-role]').value,
		active: row.querySelector('[data-access-active]').checked,
	}

	if (passwordInput.value.trim() !== '') {
		payload.password = passwordInput.value
	}

	return payload
}

function setupAccessControl() {
	const form = document.getElementById('access-user-form')
	const tableBody = document.getElementById('access-users-table-body')

	if (form) {
		form.addEventListener('submit', async event => {
			event.preventDefault()
			if (!isAdministrator()) return

			const usernameInput = document.getElementById('access-username-input')
			const passwordInput = document.getElementById('access-password-input')
			const roleInput = document.getElementById('access-role-input')
			const activeInput = document.getElementById('access-active-input')

			try {
				const response = await fetch('/api/access/users', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						username: usernameInput.value.trim(),
						password: passwordInput.value,
						role: roleInput.value,
						active: activeInput.checked,
					}),
				})
				handleAuthResponse(response)

				if (!response.ok) throw new Error('Could not add user')

				form.reset()
				activeInput.checked = true
				await loadAccessUsers()
			} catch (error) {
				alert('Could not add user.')
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

					if (!response.ok) throw new Error('Could not update user')

					await loadAccessUsers()
				} catch (error) {
					alert('Could not save user.')
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

					if (!response.ok) throw new Error('Could not delete user')

					await loadAccessUsers()
				} catch (error) {
					alert('Could not delete user. At least one user must remain.')
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
		const response = await fetch('/api/snmp/settings', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		})
		handleAuthResponse(response)
		if (!response.ok) throw new Error('Could not save SNMP settings')
		await loadSnmpSettings()
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
			} catch {
				error.textContent = 'Invalid username or password'
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

	const statisticsTab = document.querySelector('.tab-panel[data-tab="statistics"]')
	if (statisticsTab && statisticsTab.classList.contains('active')) {
		updateStatisticsTable()
	}
}, 3000)
