// Profile dispatch, startup and periodic refresh scheduling.
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

checkAuth().then((isAuthenticated) => {
	if (isAuthenticated) {
		startDataRefresh()
	}
})

setInterval(updateDashboard, 1000)
setInterval(updateWarningsTable, 3000)
setInterval(() => {
	if (!currentUser) return

	const overviewTab = document.querySelector('.tab-panel[data-tab="overview"]')
	if (
		overviewTab &&
		overviewTab.classList.contains('active') &&
		!overviewRequestController &&
		Date.now() - lastOverviewChartRefresh >= historyRefreshInterval(overviewRange)
	) {
		updateOverviewCharts()
	}
	const snmpTab = document.querySelector('.tab-panel[data-tab="snmp-settings"]')
	if (snmpTab && snmpTab.classList.contains('active')) updateSnmpLiveValues()

	const ntpTab = document.querySelector('.tab-panel[data-tab="ntp-settings"]')
	if (ntpTab && ntpTab.classList.contains('active')) loadNtpStatus()
	const servicesTab = document.querySelector('.tab-panel[data-tab="service-diagnostics"]')
	if (servicesTab && servicesTab.classList.contains('active')) loadServiceDiagnostics()

	const statisticsTab = document.querySelector('.tab-panel[data-tab="statistics"]')
	if (
		statisticsTab &&
		statisticsTab.classList.contains('active') &&
		!statisticsRequestController &&
		Date.now() - lastStatisticsRefresh >= historyRefreshInterval(statisticsRange)
	) {
		updateStatisticsTable()
	}
}, 3000)
